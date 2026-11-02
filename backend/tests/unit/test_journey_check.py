"""T-229: отсутствующая/поддельная запись и ранний ответ не дают зелёную приёмку."""

from __future__ import annotations

import copy
import json
from pathlib import Path

import httpx
import pytest
from scripts import journey_check
from scripts.journey_check import RecordedPath, check_path, path_errors, recorded_paths

ROOT = Path(__file__).resolve().parents[3]
CASE = RecordedPath("deposit_promo_rate", "human", "SIG-000123", 41)


def human():
    payload = copy.deepcopy(
        json.loads((ROOT / "contracts/events/trace/journey.schema.json").read_text())["examples"][0]
    )
    payload["stages"][4]["status"] = "waiting_human"
    payload["client_lane"] = []
    return payload


@pytest.mark.parametrize("fault", [None, "dto", "subject", "stage_order", "mock", "early_message", "pii"])
def test_human_requires_exact_subject_stages_waiting_and_no_premature_delivery(fault):
    payload = human()
    if fault == "dto":
        payload["unexpected"] = True
    elif fault == "subject":
        payload["subject"]["ref"] = "SIG-999999"
    elif fault == "stage_order":
        payload["stages"].reverse()
    elif fault == "mock":
        payload["summary"]["llm_source"] = "mock"
    elif fault in {"early_message", "pii"}:
        payload["client_lane"] = [
            {
                "channel_code": "chat",
                "kind": "ack",
                "text_ru": "synthetic@example.com" if fault == "pii" else "Уже ответили",
                "delivered_at": "2026-10-27T08:05:00Z",
            }
        ]
    errors = path_errors(payload, CASE)
    assert bool(errors) is (fault is not None)
    if fault == "pii":
        assert "contacts" in errors


@pytest.mark.parametrize(
    "trajectory,expected",
    [
        ("autonomous", ["refund", "public_reply", "private_notification"]),
        ("escalation", ["escalation", "clarification"]),
    ],
)
def test_other_paths_require_real_business_evidence(trajectory, expected):
    case = RecordedPath("synthetic", trajectory, CASE.ref, CASE.run_id)
    assert path_errors(human(), case) == expected


@pytest.mark.parametrize("fault", [None, "http", "network", "json"])
async def test_checker_uses_only_get_and_explicit_run(fault):
    requests = []

    def respond(request):
        requests.append(request)
        if fault == "network":
            raise httpx.ReadTimeout("synthetic timeout", request=request)
        return (
            httpx.Response(503 if fault == "http" else 200, text="invalid")
            if fault in {"http", "json"}
            else httpx.Response(200, json=human())
        )

    async with httpx.AsyncClient(base_url="http://test", transport=httpx.MockTransport(respond)) as http:
        assert await check_path(http, CASE) == ([] if fault is None else [fault])
    assert [(r.method, r.url.path, r.url.params["run_id"], r.url.params["presenter"]) for r in requests] == [
        ("GET", "/api/journey/SIG-000123", "41", "true")
    ]


async def test_manifest_must_cover_exact_three_paths_before_querying_database():
    class NoDatabase:
        async def execute(self, *args):
            raise AssertionError("invalid manifest must not query database")

    assert await recorded_paths(NoDatabase(), {"paths": []}) == ([], ["manifest:paths"])


@pytest.mark.parametrize("failure", [None, "human"])
async def test_runner_uses_readonly_discovery_continues_all_paths_and_reports_failure(monkeypatch, capsys, failure):
    statements, checked = [], []

    class ReadConnection:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            return False

        async def execute(self, statement, *args):
            statements.append(statement)

    async def connect(dsn):
        assert dsn == "no-real-db"
        return ReadConnection()

    cases = [RecordedPath(source, trajectory, "SIG-000123", 41) for source, trajectory in journey_check.SOURCES.items()]

    async def discover(conn, scenario):
        return cases, []

    async def check(http, case, *, expected_source):
        assert expected_source == "replay"
        checked.append(case.trajectory)
        return ["synthetic_missing"] if case.trajectory == failure else []

    monkeypatch.setattr(journey_check.psycopg.AsyncConnection, "connect", connect)
    monkeypatch.setattr(journey_check, "recorded_paths", discover)
    monkeypatch.setattr(journey_check, "check_path", check)
    assert await journey_check.run_journeys("http://test", "no-real-db", {"number": 12, "title_ru": "Проверка"}) is (
        failure is None
    )
    assert checked == ["autonomous", "human", "escalation"]
    assert statements == [
        "SET TRANSACTION ISOLATION LEVEL REPEATABLE READ, READ ONLY",
        "SET LOCAL statement_timeout='3000ms'",
    ]
    assert ("FAIL" if failure else "OK") in capsys.readouterr().out
