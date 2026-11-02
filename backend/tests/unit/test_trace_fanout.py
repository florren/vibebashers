"""T-234: границы cursor и честные anchor metadata; без базы и LLM."""

import base64
import copy
import json
from contextlib import asynccontextmanager

import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient

from app.contracts.events.trace.trace_response import TraceResponse
from app.main import create_app
from app.trace.assembler import render
from app.trace.fanout import MAX_PK, Cursor, decode_cursor, encode_cursor, normalize_scope
from tests.unit.test_trace_search import node

CONTEXT = {
    "kind": "incident",
    "ref": "INC-000151",
    "event_id": "EVT-incident:151",
    "direction": "before",
    "event_kind": "signal_created",
    "run": 2,
}


def pack(value):
    return base64.urlsafe_b64encode(json.dumps(value).encode()).decode().rstrip("=")


def test_cursor_roundtrip_binds_effective_context_and_fence():
    for rid in (None, -1, 2):
        context = {**CONTEXT, "run": rid}
        token = encode_cursor(context, 50, 1001)
        assert len(token.encode("ascii")) <= 1024
        assert decode_cursor(token) == Cursor(context, 50, 1001)
    assert decode_cursor(None) is None


@pytest.mark.parametrize(
    "token", ["", "!", "abc", "я", "a" * 1025, base64.b64encode(b"\xff").decode(), pack([]), pack({})]
)
def test_cursor_rejects_broken_or_oversized_tokens(token):
    with pytest.raises(HTTPException) as error:
        decode_cursor(token)
    assert error.value.status_code == 422
    assert token not in error.value.detail or not token


@pytest.mark.parametrize(
    "path,value",
    [
        ("v", True),
        ("v", 2),
        ("last", True),
        ("last", -1),
        ("last", 11),
        ("upper", MAX_PK + 1),
        ("context.run", True),
        ("context.run", -2),
        ("context.ref", "x" * 513),
        ("context.kind", 1),
        ("context.direction", "subject"),
        ("context.event_kind", "classification"),
    ],
)
def test_cursor_validates_types_bounds_and_family(path, value):
    payload = {"v": 1, "context": copy.deepcopy(CONTEXT), "last": 1, "upper": 10}
    parts = path.split(".")
    target = payload if len(parts) == 1 else payload[parts[0]]
    target[parts[-1]] = value
    with pytest.raises(HTTPException) as error:
        decode_cursor(pack(payload))
    assert error.value.status_code == 422


def test_encoder_never_emits_a_cursor_its_decoder_cannot_bound():
    with pytest.raises(HTTPException):
        encode_cursor({**CONTEXT, "ref": "x" * 2000}, 1, 10)


@pytest.mark.parametrize(
    "value,expected",
    [("all", "all"), ("current", "current"), ("", "current"), ("0002", "2"), (str(MAX_PK), str(MAX_PK))],
)
def test_run_scope_is_explicit_and_normalized(value, expected):
    assert normalize_scope(value) == expected


@pytest.mark.parametrize("value", ["-1", "0", "1.5", "true", str(MAX_PK + 1), "9" * 1000])
def test_run_scope_rejects_nonpositive_overflow_and_invalid_input(value):
    with pytest.raises(HTTPException) as error:
        normalize_scope(value)
    assert error.value.status_code == 422


def test_validation_precedes_database_access(monkeypatch):
    @asynccontextmanager
    async def forbidden():
        raise AssertionError("invalid fan parameters must not open the database")
        yield  # pragma: no cover

    monkeypatch.setattr("app.api.trace.read_db", forbidden)
    valid = {"direction": "after", "event_kind": "signal_created"}
    with TestClient(create_app()) as client:
        for params in (
            {"cursor": "!"},
            {"limit": 0},
            {"limit": 101},
            {"direction": "subject"},
            {"event_kind": "classification"},
            {"run_id": "-1"},
            {"run_id": str(MAX_PK + 1)},
        ):
            result = client.get("/api/trace/client/CL-000001/relations", params={**valid, **params})
            assert result.status_code == 422
            assert result.headers["content-type"].startswith("application/problem+json")


def test_only_recorded_parent_becomes_group_anchor_and_legacy_stays_valid():
    subject = node("incident", 5, public_id="INC-000005", status="closed")
    children = [{**node("signal", i, public_id=f"SIG-{i:06d}"), "parent": "incident:5"} for i in range(1, 10)]
    edges = [{"from": f"EVT-signal:{i}", "to": "EVT-incident:5", "relation_ru": "Причина"} for i in range(1, 10)]
    result = render(subject, children, [], edges)
    TraceResponse.model_validate(result)
    group = result["groups"][0]
    assert group["count"] == 9 and len(group["sample_refs"]) == 3
    assert group["phase"] == "before"
    assert group["anchor"] == {"kind": "incident", "ref": "INC-000005", "event_id": "EVT-incident:5"}
    for child in children:
        child["parent"] = "unknown:999"
    legacy = render(subject, children, [], edges)
    TraceResponse.model_validate(legacy)
    assert "anchor" not in legacy["groups"][0] and "phase" not in legacy["groups"][0]
