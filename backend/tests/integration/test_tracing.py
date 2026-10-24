"""T-065: трассировка agent_steps, NOTIFY, cost_estimate и API /api/agent/runs*."""

from __future__ import annotations

import asyncio
import contextlib
import os
from typing import Any

import orjson
import psycopg
import pytest
from fastapi.testclient import TestClient

from app.agent import nodes
from app.agent.graph import process_signal, resume_after_human
from app.config import get_settings
from app.ingest.normalizer import create_signal, from_api_signal
from app.llm.base import LLMProfile
from app.llm.failover import ProviderChain
from app.llm.mock import MockProvider
from app.main import create_app

pytestmark = pytest.mark.integration


def _dsn(url: str) -> str:
    return url.replace("postgresql+psycopg://", "postgresql://", 1)


PROFILE = LLMProfile(
    code="mock",
    provider="mock",
    model="mock-1",
    role="main",
    price_in_per_1m=50.0,
    price_out_per_1m=120.0,
)


def _chain() -> ProviderChain:
    return ProviderChain([MockProvider()])


def _client_id(conn: psycopg.Connection) -> int:
    row = conn.execute(
        "select id from clients where segment_code = 'mass' and is_active order by id limit 1"
    ).fetchone()
    assert row
    return int(row[0])


def test_cost_estimate_and_llm_profile_id(seeded: str, conn: psycopg.Connection) -> None:
    cid = _client_id(conn)

    async def run() -> int:
        async with await psycopg.AsyncConnection.connect(_dsn(seeded)) as db:
            res = await create_signal(
                db,
                from_api_signal(
                    {
                        "channel_code": "chat",
                        "client_id": cid,
                        "text": "Списали комиссию за перевод, верните 99 рублей.",
                    }
                ),
                source_code="api",
                emit_event=False,
            )
            await db.commit()
            state = await process_signal(db, signal_id=int(res["signal_id"]), chain=_chain(), profile=PROFILE)
            assert state is not None
            return int(res["signal_id"])

    signal_id = asyncio.run(run())
    run_row = conn.execute(
        "select id, llm_profile_id, cost_estimate from agent_runs where signal_id = %s and kind = 'agent'",
        (signal_id,),
    ).fetchone()
    assert run_row
    run_id, llm_profile_id, cost_estimate = run_row
    mock_profile = conn.execute("select id from llm_profiles where code = 'mock'").fetchone()
    assert mock_profile and llm_profile_id == mock_profile[0]
    steps = conn.execute(
        "select prompt_tokens, completion_tokens from agent_steps where run_id = %s order by seq",
        (run_id,),
    ).fetchall()
    expected = sum(PROFILE.cost(int(p or 0), int(c or 0)) for p, c in steps)
    assert abs(float(cost_estimate or 0) - expected) < 1e-4


def _client_with_qr_fee(conn: psycopg.Connection) -> int:
    row = conn.execute(
        "select o.client_id from operations o join clients c on c.id = o.client_id "
        "where o.error_code = 'PROC-QR-FEE-CHARGED' and c.segment_code <> 'ultra_vip' "
        "order by o.started_sim desc limit 1"
    ).fetchone()
    if row:
        return int(row[0])
    return _client_id(conn)


def test_api_agent_runs_list_and_detail(seeded: str, conn: psycopg.Connection) -> None:
    cid = _client_with_qr_fee(conn)
    signal_text = "Оплатил по QR 3 200 рублей, а с карты списали комиссию 138 руб. СБП же бесплатно! Верните комиссию."

    async def run() -> tuple[int, int]:
        async with await psycopg.AsyncConnection.connect(_dsn(seeded)) as db:
            res = await create_signal(
                db,
                from_api_signal({"channel_code": "chat", "client_id": cid, "text": signal_text}),
                source_code="api",
                emit_event=False,
            )
            await db.commit()
            state = await process_signal(db, signal_id=int(res["signal_id"]), chain=_chain(), profile=PROFILE)
            assert state and state.get("outcome") == "completed"
            run_id = conn.execute("select id from agent_runs where signal_id = %s", (res["signal_id"],)).fetchone()[0]
            return int(res["signal_id"]), int(run_id)

    _signal_id, agent_run_id = asyncio.run(run())
    os.environ["DATABASE_URL"] = seeded
    os.environ["APP_ENV"] = "test"
    get_settings.cache_clear()
    try:
        client_ctx = TestClient(create_app())
    except Exception:
        get_settings.cache_clear()
        raise
    with client_ctx as client:
        listed = client.get("/api/agent/runs", params={"kind": "agent", "outcome": "completed", "limit": 500})
        assert listed.status_code == 200
        items = listed.json()["items"]
        assert any(it["id"] == agent_run_id for it in items)
        page1 = client.get("/api/agent/runs", params={"kind": "agent", "limit": 1})
        assert page1.status_code == 200
        body = page1.json()
        assert body["items"]
        assert body.get("next_cursor")
        bad = client.get("/api/agent/runs", params={"cursor": "not-a-number"})
        assert bad.status_code == 422
        detail = client.get(f"/api/agent/runs/{agent_run_id}")
        assert detail.status_code == 200
        steps = detail.json()["steps"]
        llm_step = next(s for s in steps if s["node"] == "normalize")
        assert llm_step.get("prompt")
        assert llm_step.get("response_raw")
    get_settings.cache_clear()


def test_notify_step_pairs_and_text_budget(seeded: str, conn: psycopg.Connection) -> None:
    cid = _client_id(conn)
    events: list[tuple[str, dict[str, Any]]] = []

    async def run() -> int:
        listener = await psycopg.AsyncConnection.connect(_dsn(seeded), autocommit=True)
        await listener.execute("LISTEN agent")
        await listener.execute("LISTEN agent_tokens")
        stop = asyncio.Event()

        async def collect() -> None:
            gen = listener.notifies(timeout=30.0)
            try:
                async for n in gen:
                    events.append((n.channel, orjson.loads(n.payload)))
                    if stop.is_set():
                        break
            except asyncio.CancelledError:
                raise
            except Exception:
                return

        collector = asyncio.create_task(collect())
        signal_id = 0
        async with await psycopg.AsyncConnection.connect(_dsn(seeded)) as db:
            res = await create_signal(
                db,
                from_api_signal(
                    {
                        "channel_code": "chat",
                        "client_id": cid,
                        "text": "Оплатил по QR, сняли лишнюю комиссию 150 руб, верните.",
                    }
                ),
                source_code="api",
                emit_event=False,
            )
            await db.commit()
            signal_id = int(res["signal_id"])
            await process_signal(db, signal_id=signal_id, chain=_chain(), profile=PROFILE)
        stop.set()
        await asyncio.sleep(0.3)
        collector.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await collector
        await listener.close()
        return signal_id

    signal_id = asyncio.run(run())
    run_id = conn.execute("select id from agent_runs where signal_id = %s", (signal_id,)).fetchone()[0]
    db_steps = conn.execute(
        "select seq, node, response_raw from agent_steps where run_id = %s order by seq", (run_id,)
    ).fetchall()
    started = {
        (m["data"]["seq"], m["data"]["node"])
        for ch, m in events
        if ch == "agent" and m.get("type") == "step_started" and m["data"].get("run_id") == run_id
    }
    finished = {
        (m["data"]["seq"], m["data"]["node"])
        for ch, m in events
        if ch == "agent" and m.get("type") == "step_finished" and m["data"].get("run_id") == run_id
    }
    for seq, node, _ in db_steps:
        assert (seq, node) in started
        assert (seq, node) in finished
    deltas_by_seq: dict[int, list[str]] = {}
    order: list[tuple[str, int | None]] = []
    for ch, m in events:
        if ch == "agent_tokens" and m.get("type") == "delta" and m["data"].get("run_id") == run_id:
            seq = int(m["data"]["step_seq"])
            deltas_by_seq.setdefault(seq, []).append(m["data"]["delta"])
            order.append(("delta", seq))
        if ch == "agent" and m.get("type") == "step_finished" and m["data"].get("run_id") == run_id:
            order.append(("finished", int(m["data"]["seq"])))
    for seq, _node, raw in db_steps:
        if raw:
            assert "".join(deltas_by_seq.get(seq, [])) == raw
    for idx, item in enumerate(order):
        if item[0] != "finished":
            continue
        seq = item[1]
        prev = order[idx - 1] if idx else None
        if prev and prev[0] == "delta":
            assert prev[1] == seq
    budget = conn.execute(
        "select coalesce(sum(octet_length(coalesce(prompt,'')) + octet_length(coalesce(response_raw,'')) + "
        "octet_length(coalesce(reasoning,'')) + octet_length(coalesce(output::text,'')) + "
        "octet_length(coalesce(tool_calls::text,''))), 0) from agent_steps where run_id = %s",
        (run_id,),
    ).fetchone()[0]
    assert int(budget) <= 200 * 1024


def test_resume_after_human_restores_text_byte_budget(
    seeded: str, conn: psycopg.Connection, monkeypatch: pytest.MonkeyPatch
) -> None:
    cid = conn.execute(
        "select id from clients where segment_code = 'ultra_vip' and is_active order by id limit 1"
    ).fetchone()
    if not cid:
        pytest.skip("нет ultra_vip клиента в сиде")
    cid = int(cid[0])
    captured: list[int] = []
    orig = nodes.Deps.record_step

    async def _record(self: nodes.Deps, *args: Any, **kwargs: Any) -> None:
        if not captured:
            captured.append(self.text_bytes_used)
        await orig(self, *args, **kwargs)

    async def pause() -> tuple[int, int]:
        async with await psycopg.AsyncConnection.connect(_dsn(seeded)) as db:
            res = await create_signal(
                db,
                from_api_signal(
                    {
                        "channel_code": "email",
                        "client_id": cid,
                        "text": "Третий день не открывается вклад в приложении, прошу помочь.",
                    }
                ),
                source_code="api",
                emit_event=False,
            )
            await db.commit()
            state = await process_signal(db, signal_id=int(res["signal_id"]), chain=_chain(), profile=PROFILE)
            assert state and state.get("outcome") == "awaiting_human"
            run_id = conn.execute("select id from agent_runs where signal_id = %s", (res["signal_id"],)).fetchone()[0]
            return int(res["signal_id"]), int(run_id)

    signal_id, run_id = asyncio.run(pause())
    used_before = conn.execute(
        "select coalesce(sum(octet_length(coalesce(prompt,'')) + octet_length(coalesce(response_raw,'')) + "
        "octet_length(coalesce(reasoning,'')) + octet_length(coalesce(output::text,'')) + "
        "octet_length(coalesce(tool_calls::text,''))), 0) from agent_steps where run_id = %s",
        (run_id,),
    ).fetchone()[0]
    assert int(used_before) > 0
    hd_id = conn.execute("select id from human_decisions where signal_id = %s", (signal_id,)).fetchone()[0]

    conn.execute("update human_decisions set decision = 'accept', decided_at = now() where id = %s", (hd_id,))

    monkeypatch.setattr(nodes.Deps, "record_step", _record)
    captured.clear()

    async def resume() -> None:
        async with await psycopg.AsyncConnection.connect(_dsn(seeded)) as db:
            await resume_after_human(db, human_decision_id=int(hd_id), chain=_chain(), profile=PROFILE)

    asyncio.run(resume())
    assert captured and captured[0] == int(used_before)
