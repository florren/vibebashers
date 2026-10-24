"""T-065: unit-тесты begin_step, delta, step_finished и бюджета текстов шага."""

from __future__ import annotations

import datetime as dt
from typing import Any

import orjson
import pytest

from app.agent.nodes import RUN_STEP_TEXT_BUDGET, Deps, _chunk_utf8, _fit_step_texts, _utf8_len
from app.agent.tools.base import ToolContext
from app.llm.base import LLMProfile
from app.llm.failover import ProviderChain
from app.llm.mock import MockProvider
from app.sim.events import dumps


class _Cursor:
    def __init__(self, row: tuple[Any, ...] | None = None) -> None:
        self._row = row

    async def fetchone(self) -> tuple[Any, ...] | None:
        return self._row


class _Conn:
    def __init__(self) -> None:
        self.sql: list[tuple[str, tuple[Any, ...]]] = []
        self.notifies: list[tuple[str, str]] = []

    async def execute(self, sql: str, args: tuple[Any, ...] = ()) -> _Cursor:
        self.sql.append((sql, args))
        if sql.strip().startswith("select pg_notify"):
            self.notifies.append((str(args[0]), str(args[1])))
        if "insert into agent_steps" in sql:
            return _Cursor(None)
        return _Cursor(None)


def _deps(conn: _Conn) -> Deps:
    ctx = ToolContext(conn, run_id=10, agent_run_id=42, sim_time=dt.datetime(2026, 1, 1, tzinfo=dt.UTC))  # type: ignore[arg-type]
    return Deps(
        ctx=ctx,
        chain=ProviderChain([MockProvider()]),
        profile=LLMProfile(code="mock", provider="mock", model="mock-1"),
    )


def _parse_notify(channel: str, payload: str) -> dict[str, Any]:
    body = orjson.loads(payload)
    assert body.get("type")
    return body


@pytest.mark.asyncio
async def test_begin_step_step_started_without_insert() -> None:
    conn = _Conn()
    deps = _deps(conn)
    await deps.begin_step("normalize")
    inserts = [s for s, _ in conn.sql if "insert into agent_steps" in s]
    assert not inserts
    assert len(conn.notifies) == 1
    ch, payload = conn.notifies[0]
    assert ch == "agent"
    msg = _parse_notify(ch, payload)
    assert msg["type"] == "step_started"
    assert msg["data"]["run_id"] == 42
    assert msg["data"]["seq"] == 1
    assert msg["data"]["node"] == "normalize"
    assert msg["data"]["status"] == "started"


@pytest.mark.asyncio
async def test_record_step_deltas_match_response_raw_and_step_finished() -> None:
    conn = _Conn()
    deps = _deps(conn)
    raw = "alpha-" + ("x" * 1200) + "-omega"
    await deps.record_step(
        "classify",
        "ok",
        {"in": 1},
        {"out": 2},
        prompt="p",
        raw=raw,
        reasoning="r",
        usage={"prompt_tokens": 3, "completion_tokens": 5},
        latency_ms=11,
    )
    inserts = [a for s, a in conn.sql if "insert into agent_steps" in s]
    assert inserts
    assert inserts[0][7] == raw
    deltas: list[str] = []
    finished: dict[str, Any] | None = None
    for ch, payload in conn.notifies:
        msg = _parse_notify(ch, payload)
        if ch == "agent_tokens" and msg["type"] == "delta":
            assert msg["data"]["step_seq"] == 1
            assert msg["data"]["run_id"] == 42
            deltas.append(msg["data"]["delta"])
        if ch == "agent" and msg["type"] == "step_finished":
            finished = msg["data"]
    assert "".join(deltas) == raw
    assert finished is not None
    assert finished["run_id"] == 42
    assert finished["seq"] == 1
    assert finished["node"] == "classify"
    assert finished["status"] == "ok"
    assert finished["latency_ms"] == 11
    assert finished["tokens"] == 8


@pytest.mark.asyncio
async def test_record_step_deltas_match_trimmed_response_raw() -> None:
    conn = _Conn()
    deps = _deps(conn)
    deps.text_bytes_used = RUN_STEP_TEXT_BUDGET - 200
    raw = "delta-" + ("Q" * 8000) + "-end"
    await deps.record_step("normalize", "ok", {"a": 1}, {"b": 2}, raw=raw, prompt="p")
    row = next(a for s, a in conn.sql if "insert into agent_steps" in s)
    stored_raw = row[7]
    deltas = [
        _parse_notify(ch, pl)["data"]["delta"]
        for ch, pl in conn.notifies
        if ch == "agent_tokens" and _parse_notify(ch, pl)["type"] == "delta"
    ]
    assert stored_raw is not None
    assert stored_raw != raw
    assert "".join(deltas) == stored_raw


@pytest.mark.asyncio
async def test_huge_output_keeps_valid_json_on_tight_budget() -> None:
    conn = _Conn()
    deps = _deps(conn)
    deps.text_bytes_used = RUN_STEP_TEXT_BUDGET - 8
    huge_output = {"payload": "O" * 50_000, "nested": {"x": [1, 2, 3]}}
    await deps.record_step("decide", "ok", {"in": 1}, huge_output, prompt="x")
    row = next(a for s, a in conn.sql if "insert into agent_steps" in s)
    stored_output = row[5]
    parsed = orjson.loads(stored_output) if isinstance(stored_output, str) else stored_output
    assert parsed == {} or parsed == huge_output


def test_fit_step_texts_replaces_oversized_json_with_empty_objects() -> None:
    big = dumps({"k": "v" * 10_000})
    p, r, reason, out, tools = _fit_step_texts(
        50,
        prompt="abcdefghij",
        response_raw=None,
        reasoning=None,
        output_json=big,
        tool_calls_json='[{"name":"x"}]',
    )
    assert orjson.loads(out) == {}
    assert orjson.loads(tools) == []
    assert _utf8_len(p) + _utf8_len(out) + _utf8_len(tools) <= 50


@pytest.mark.asyncio
async def test_huge_prompt_trimmed_within_run_text_budget() -> None:
    conn = _Conn()
    deps = _deps(conn)
    deps.text_bytes_used = RUN_STEP_TEXT_BUDGET - 500
    huge = "Z" * (RUN_STEP_TEXT_BUDGET + 10_000)
    await deps.record_step(
        "normalize",
        "ok",
        {"x": 1},
        {"y": 2},
        prompt=huge,
        raw="short",
        reasoning="ok",
    )
    row = next(a for s, a in conn.sql if "insert into agent_steps" in s)
    stored_prompt = row[6]
    assert stored_prompt is not None
    assert len(stored_prompt.encode("utf-8")) <= 500
    assert deps.text_bytes_used <= RUN_STEP_TEXT_BUDGET


def test_chunk_utf8_splits_long_raw() -> None:
    text = "аб" * 400
    chunks = _chunk_utf8(text, 100)
    assert len(chunks) > 1
    assert "".join(chunks) == text
