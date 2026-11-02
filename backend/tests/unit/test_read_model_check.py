"""Приёмка проверяет конкретный результат, контракт и скрытие capability token."""

from __future__ import annotations

import httpx
import pytest
from scripts.read_model_check import FORMATS, SearchCase, check_search, check_trace, recorded_cases, recorded_contexts

from app.search.grammar import PREFIXES


def search_payload(ref="SIG-000001"):
    return {
        "query": "[токен скрыт]",
        "parsed": {"mode": "id", "kind": "tracking", "ref": None, "normalized": "[токен скрыт]"},
        "hits": [{"kind": "signal", "ref": ref, "title_ru": "Записанное обращение", "run_id": "SR-0001"}],
        "counts_by_kind": {"signal": 1},
        "took_ms": 1,
    }


@pytest.mark.parametrize(
    "problem", [None, "wrong_ref", "schema", "capability", "contact", "not_json", "http", "network"]
)
async def test_search_acceptance_requires_real_match_and_safe_response(problem):
    case = SearchCase("format:tracking_token", "synthetic_tracking_capability_235", "signal", "SIG-000001")
    payload = search_payload("SIG-000002" if problem == "wrong_ref" else case.ref)
    if problem == "schema":
        payload["debug"] = True
    if problem == "capability":
        payload["query"] = case.query
    if problem == "contact":
        payload["hits"][0]["title_ru"] = "synthetic@example.com"
    requests = []

    def respond(request):
        requests.append(request)
        if problem == "network":
            raise httpx.ReadTimeout("synthetic timeout", request=request)
        return (
            httpx.Response(503 if problem == "http" else 200, text="not JSON")
            if problem in ("not_json", "http")
            else httpx.Response(200, json=payload)
        )

    async with httpx.AsyncClient(base_url="http://test", transport=httpx.MockTransport(respond)) as http:
        assert await check_search(http, case) is (problem is None)
    assert [(r.method, r.url.path, r.url.params["run_id"]) for r in requests] == [("GET", "/api/search", "all")]
    assert case.query not in repr(case)


@pytest.mark.parametrize(
    "problem",
    [None, "wrong_ref", "schema", "not_found", "network", "not_json", "causal", "pending", "fanout", "contact"],
)
async def test_trace_acceptance_rejects_wrong_subject_and_missing_sections(problem):
    case = SearchCase("prefix:SIG", "SIG-000001", "signal", "SIG-000001")
    payload = {
        "subject": {
            "kind": "signal",
            "ref": "SIG-000002" if problem == "wrong_ref" else case.ref,
            "title_ru": "Обращение",
        },
        "before": [],
        "after": [],
        "edges": [],
        "groups": [],
        "pending": [],
        "terminal": {"reached": False},
        "stats": {"before_count": 0, "after_count": 0, "build_ms": 1},
    }
    if problem == "schema":
        del payload["terminal"]
    if problem == "contact":
        payload["subject"]["title_ru"] = "synthetic@example.com"

    def respond(request):
        if problem == "network":
            raise httpx.ReadTimeout("synthetic timeout", request=request)
        if problem == "not_json":
            return httpx.Response(200, text="not JSON")
        return httpx.Response(404 if problem == "not_found" else 200, json=payload)

    async with httpx.AsyncClient(
        base_url="http://test",
        transport=httpx.MockTransport(respond),
    ) as http:
        assert await check_trace(
            http,
            case,
            causal=problem == "causal",
            pending=problem == "pending",
            minimum_fanout=120 if problem == "fanout" else 0,
        ) is (problem is None)


async def test_missing_recorded_evidence_is_not_a_pass_or_silent_skip():
    class Empty:
        async def execute(self, *args):
            return self

        async def fetchone(self):
            return None

    cases, missing = await recorded_cases(Empty(), {})
    assert cases == []
    assert set(missing) == {
        "manifest:prefixes",
        "manifest:formats",
        *(f"prefix:{p}" for p in PREFIXES),
        *(f"format:{f}" for f in FORMATS),
    }
    contexts, missing_contexts = await recorded_contexts(Empty())
    assert contexts == []
    assert set(missing_contexts) == {
        "context:causal_signal",
        "context:causal_incident",
        "context:pending",
        "context:fanout",
    }
