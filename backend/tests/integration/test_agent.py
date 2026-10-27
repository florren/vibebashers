"""B04: полный проход графа на сид-данных с MockProvider (сигнал → инцидент/уведомления/шаги), HITL-пауза и возобновление, идемпотентность ingest."""

from __future__ import annotations

import asyncio
import datetime as dt
from typing import Any

import psycopg
import pytest

from app.agent.graph import GRAPH_SPEC, process_signal, resume_after_human
from app.agent.state import GRAPH_VERSION
from app.ingest.normalizer import create_signal, from_api_signal
from app.llm.base import LLMProfile
from app.llm.failover import ProviderChain
from app.llm.mock import MockProvider

pytestmark = pytest.mark.integration


def _dsn(url: str) -> str:
    return url.replace("postgresql+psycopg://", "postgresql://", 1)


PROFILE = LLMProfile(code="mock", provider="mock", model="mock-1", role="main")


def _chain() -> ProviderChain:
    return ProviderChain([MockProvider()])


async def _ingest_and_run(dsn: str, body: dict[str, Any]) -> tuple[int, dict[str, Any]]:
    async with await psycopg.AsyncConnection.connect(dsn) as conn:
        res = await create_signal(conn, from_api_signal(body), source_code="api", emit_event=False)
        await conn.commit()
        assert res["status"] == "accepted", res
        state = await process_signal(conn, signal_id=int(res["signal_id"]), chain=_chain(), profile=PROFILE)
        assert state is not None
        return int(res["signal_id"]), dict(state)


def _client(conn: psycopg.Connection, segment: str, with_qr_fee: bool = False) -> int:
    if with_qr_fee:
        row = conn.execute(
            "select o.client_id from operations o join clients c on c.id = o.client_id where o.error_code = 'PROC-QR-FEE-CHARGED' and c.segment_code <> 'ultra_vip' order by o.started_sim desc limit 1"
        ).fetchone()
        if row:
            return int(row[0])
    row = conn.execute(
        "select id from clients where segment_code = %s and is_active order by id limit 1", (segment,)
    ).fetchone()
    assert row, f"нет клиента сегмента {segment}"
    return int(row[0])


def test_full_pass_creates_incident_and_notifications(seeded: str, conn: psycopg.Connection) -> None:
    cid = _client(conn, "mass", with_qr_fee=True)
    signal_id, state = asyncio.run(
        _ingest_and_run(
            _dsn(seeded),
            {
                "channel_code": "chat",
                "client_id": cid,
                "text": "Оплатил по QR 3 200 рублей, а с карты списали комиссию 138 руб. СБП же бесплатно! Верните комиссию.",
            },
        )
    )
    assert state["outcome"] == "completed", state["errors"]
    run = conn.execute(
        "select id, outcome, prompt_version, graph_version, thread_id, incident_id, total_tokens from agent_runs where signal_id = %s",
        (signal_id,),
    ).fetchone()
    assert (
        run
        and run[1] == "completed"
        and run[2].startswith("v1")
        and run[3] == GRAPH_VERSION
        and run[4].endswith(f":{signal_id}")
    )
    steps = [
        r[0] for r in conn.execute("select node from agent_steps where run_id = %s order by seq", (run[0],)).fetchall()
    ]
    assert (
        steps[:3] == ["ingest", "normalize", "identify_client"] and steps[-1] == "close" and "instant_decide" in steps
    )
    inc = conn.execute(
        "select id, status, team_code, priority, sla_due_sim, problem_summary, agent_run_id from incidents where id = %s",
        (run[5],),
    ).fetchone()
    assert (
        inc
        and inc[1] == "closed"  # Быстрый возврат проверен и замкнут (T-174).
        and inc[2]
        and 1 <= inc[3] <= 4
        and inc[4] is not None
        and inc[5]["problem"]
        and inc[6] == run[0]
    )
    hist = [
        r[0]
        for r in conn.execute(
            "select to_status from incident_status_history where incident_id = %s order by id", (inc[0],)
        ).fetchall()
    ]
    assert hist[:3] == ["new", "classified", "routed"]
    kinds = {
        r[0]
        for r in conn.execute("select recipient_type from notifications where signal_id = %s", (signal_id,)).fetchall()
    }
    assert kinds == {"client"}  # Автономный возврат уже исполнен; ручная работа команды не запрашивается.
    sig = conn.execute(
        "select status, classification->>'signal_type', decision->>'incident_action', sentiment from signals where id = %s",
        (signal_id,),
    ).fetchone()
    assert (
        sig
        and sig[0] == "closed"
        and sig[1] in ("tariff_terms", "tech_fault")
        and sig[2] == "create"
        and sig[3] == "negative"
    )
    assert conn.execute("select count(*) from rule_evaluations where signal_id = %s", (signal_id,)).fetchone()[0] > 0

    # повторный запуск того же сигнала — no-op
    async def again() -> Any:
        async with await psycopg.AsyncConnection.connect(_dsn(seeded)) as c:
            return await process_signal(c, signal_id=signal_id, chain=_chain(), profile=PROFILE)

    assert asyncio.run(again()) is None


def test_hitl_pause_and_resume(seeded: str, conn: psycopg.Connection) -> None:
    cid = _client(conn, "ultra_vip")
    signal_id, state = asyncio.run(
        _ingest_and_run(
            _dsn(seeded),
            {
                "channel_code": "email",
                "client_id": cid,
                "text": "Добрый день. Третий день не могу открыть вклад в приложении, ошибка при подтверждении. Прошу разобраться.",
            },
        )
    )
    assert state["outcome"] == "awaiting_human" and state["decision"]["human_reason"] == "ultra_vip"
    hd = conn.execute(
        "select id, reason, options, recommendation, decision from human_decisions where signal_id = %s", (signal_id,)
    ).fetchone()
    assert hd and hd[1] == "ultra_vip" and len(hd[2]) >= 2 and hd[3] and hd[4] is None
    assert conn.execute("select status from signals where id = %s", (signal_id,)).fetchone()[0] == "awaiting_human"
    assert (
        conn.execute(
            "select count(*) from incidents where agent_run_id = (select id from agent_runs where signal_id = %s)",
            (signal_id,),
        ).fetchone()[0]
        == 0
    )
    conn.execute(
        "update human_decisions set decision = 'modify', modified_proposal = %s::jsonb, decided_by = 'test', decided_at = now(), use_as_fewshot = true where id = %s",
        ('{"priority": 2, "gift": null}', hd[0]),
    )

    async def resume() -> Any:
        async with await psycopg.AsyncConnection.connect(_dsn(seeded)) as c:
            return await resume_after_human(
                c, human_decision_id=hd[0], chain=_chain(), profile=PROFILE, sim_time=dt.datetime.now(dt.UTC)
            )

    st = asyncio.run(resume())
    assert (
        st is not None
        and st["outcome"] == "deferred"
        and st["decision"]["priority"] == 2
        and st["decision"]["gift"] is None
    )
    run = conn.execute(
        "select outcome, needed_human, incident_id from agent_runs where signal_id = %s", (signal_id,)
    ).fetchone()
    assert run[0] == "deferred" and run[1] is True and run[2] is not None
    assert (
        conn.execute(
            "select count(*) from followups where signal_id = %s and status = 'scheduled'", (signal_id,)
        ).fetchone()[0]
        == 1
    )
    assert conn.execute("select status from incidents where id = %s", (run[2],)).fetchone()[0] != "closed"
    assert conn.execute("select incident_id from human_decisions where id = %s", (hd[0],)).fetchone()[0] == run[2]
    nodes = [
        r[0]
        for r in conn.execute(
            "select node from agent_steps where run_id = (select id from agent_runs where signal_id = %s) order by seq",
            (signal_id,),
        ).fetchall()
    ]
    assert nodes.count("wait_human") == 2 and nodes[-2:] == ["act", "followup_monitor"]
    assert (
        conn.execute("select count(*) from tasks where incident_id = %s and kind = 'gift'", (run[2],)).fetchone()[0]
        == 0
    )


def test_gratitude_no_incident_and_ingest_dedup(seeded: str, conn: psycopg.Connection) -> None:
    cid = _client(conn, "mass")
    signal_id, state = asyncio.run(
        _ingest_and_run(
            _dsn(seeded),
            {"channel_code": "chat", "client_id": cid, "text": "Спасибо огромное, всё быстро решили, деньги вернули!"},
        )
    )
    assert state["outcome"] == "completed" and state["decision"]["incident_action"] == "none"
    assert conn.execute("select count(*) from incident_signals where signal_id = %s", (signal_id,)).fetchone()[0] == 0
    assert (
        conn.execute(
            "select count(*) from notifications where signal_id = %s and recipient_type = 'client'", (signal_id,)
        ).fetchone()[0]
        == 1
    )

    async def dedup() -> list[dict[str, Any]]:
        msg = {
            "channel": "social",
            "external_id": "vk-dedup-1",
            "client": {},
            "text": "Не работает приложение второй день!",
            "timestamp": "2026-11-09T10:00:00+03:00",
            "geo": {"source": "none"},
            "origin": "api",
        }
        out = []
        async with await psycopg.AsyncConnection.connect(_dsn(seeded)) as c:
            out.append(await create_signal(c, dict(msg), source_code="rest_messages"))
            out.append(await create_signal(c, dict(msg), source_code="rest_messages"))
            out.append(
                await create_signal(
                    c, {**msg, "external_id": "vk-dedup-2", "channel": "bad"}, source_code="rest_messages"
                )
            )
            await c.commit()
        return out

    a, b, c = asyncio.run(dedup())
    assert (
        a["status"] == "accepted"
        and b["status"] == "duplicate"
        and b["signal_id"] == a["signal_id"]
        and c["status"] == "rejected"
    )
    ev = conn.execute(
        "select count(*) from sim_events where event_type = 'signal.received' and (payload->>'signal_id')::int = %s",
        (a["signal_id"],),
    ).fetchone()[0]
    assert ev == 1
    assert {n["id"] for n in GRAPH_SPEC["nodes"]} >= {"ingest", "decide", "wait_human", "act", "close"}
