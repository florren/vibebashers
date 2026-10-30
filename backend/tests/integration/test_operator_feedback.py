"""T-268: реальные эффекты нового плана, неизменность старого графа/денег, повторы и ошибки."""

from __future__ import annotations

import asyncio
from typing import Any

import psycopg
import pytest

from app.agent import nodes
from app.agent.operator_feedback import feedback_context, planned_priority, process_feedback
from tests.helpers import MOCK_PROFILE, dsn, mock_chain
from tests.integration.test_hitl_continuity import make_case

pytestmark = pytest.mark.integration


def test_feedback_changes_future_case_plan_once(seeded: str, conn: Any, monkeypatch: Any) -> None:
    cid = conn.execute("select id from clients order by id limit 1").fetchone()[0]
    case = make_case(conn, seeded, "operator-update", cid)
    other = make_case(conn, seeded, "operator-other", cid)
    conn.execute("update incidents set priority=3 where id in (%s,%s)", (case["iid"], other["iid"]))
    fid = conn.execute(
        "insert into hitl_feedback(human_decision_id,idempotency_key,comment,recorded_by,recorded_sim) values (%s,'new-info','Обнаружена угроза повторного ущерба, нужна срочная проверка','operator',now()) returning id",
        (case["hid"],),
    ).fetchone()[0]
    source_ar = conn.execute("select agent_run_id from human_decisions where id=%s", (case["hid"],)).fetchone()[0]
    before = conn.execute(
        "select (select count(*) from ledger_entries),(select count(*) from notifications),(select count(*) from agent_steps where run_id=%s)",
        (source_ar,),
    ).fetchone()

    async def review(deps: Any, task: str, schema: str, variables: Any, text: str) -> Any:
        assert task == "operator_feedback" and schema == "agent/operator_feedback"
        assert "повторного ущерба" in text
        assert variables["context"]["incidents"][0]["id"] == case["iid"]
        return {
            "summary_ru": "Новые сведения требуют срочной ручной проверки.",
            "priority": 1,
            "next_step": "manual_review",
        }, {"provider": "mock", "model": "mock:test", "usage": {}}

    monkeypatch.setattr(nodes, "_llm", review)

    async def check() -> None:
        async with await psycopg.AsyncConnection.connect(dsn(seeded)) as ac:
            assert await process_feedback(ac, fid, mock_chain(), MOCK_PROFILE)
            assert not await process_feedback(ac, fid, mock_chain(), MOCK_PROFILE)
            context = await feedback_context(ac, case["sid"], case["rid"])
            assert context[0]["id"] == fid and context[0]["status"] == "applied"
            assert planned_priority({"operator_feedback": context}, 3) == 1
            assert (
                nodes._context_for_prompt({"context": {"operator_feedback": context}})["operator_feedback"] == context
            )
            assert await feedback_context(ac, other["sid"], other["rid"]) == []

    asyncio.run(check())
    assert conn.execute("select priority from incidents where id=%s", (case["iid"],)).fetchone()[0] == 1
    assert conn.execute("select priority from incidents where id=%s", (other["iid"],)).fetchone()[0] == 3
    assert conn.execute("select count(*) from tasks where payload->>'feedback_id'=%s", (str(fid),)).fetchone()[0] == 1
    assert (
        conn.execute(
            "select count(*) from incident_artifacts where meta->>'operator_feedback_id'=%s", (str(fid),)
        ).fetchone()[0]
        == 1
    )
    assert conn.execute("select count(*) from agent_runs where kind='operator_review'").fetchone()[0] == 1
    assert conn.execute("select decision,decided_by from human_decisions where id=%s", (case["hid"],)).fetchone() == (
        None,
        None,
    )
    assert (
        before
        == conn.execute(
            "select (select count(*) from ledger_entries),(select count(*) from notifications),(select count(*) from agent_steps where run_id=%s)",
            (source_ar,),
        ).fetchone()
    )


def test_closed_case_and_real_mock_schema_retry(seeded: str, conn: Any, monkeypatch: Any) -> None:
    cid = conn.execute("select id from clients order by id limit 1").fetchone()[0]
    case = make_case(conn, seeded, "operator-closed", cid)
    conn.execute("update incidents set status='closed' where id=%s", (case["iid"],))
    fid = conn.execute(
        "insert into hitl_feedback(human_decision_id,idempotency_key,comment,recorded_by,recorded_sim) values (%s,'retry','Уточнение после закрытия: прошу проверить результат','operator',now()) returning id",
        (case["hid"],),
    ).fetchone()[0]
    original = nodes._llm

    async def broken(*args: Any, **kwargs: Any) -> Any:
        raise RuntimeError("synthetic provider failure")

    monkeypatch.setattr(nodes, "_llm", broken)

    async def check() -> None:
        async with await psycopg.AsyncConnection.connect(dsn(seeded)) as ac:
            assert not await process_feedback(ac, fid, mock_chain(), MOCK_PROFILE)

    asyncio.run(check())
    assert conn.execute(
        "select status,error from hitl_feedback_processing where feedback_id=%s", (fid,)
    ).fetchone() == ("failed", "RuntimeError")
    assert conn.execute("select count(*) from tasks where payload->>'feedback_id'=%s", (str(fid),)).fetchone()[0] == 0
    monkeypatch.setattr(nodes, "_llm", original)

    async def retry() -> None:
        async with await psycopg.AsyncConnection.connect(dsn(seeded)) as ac:
            assert await process_feedback(ac, fid, mock_chain(), MOCK_PROFILE)

    asyncio.run(retry())
    assert conn.execute(
        "select status,attempts from hitl_feedback_processing where feedback_id=%s", (fid,)
    ).fetchone() == ("applied", 2)
    assert conn.execute("select status from incidents where id=%s", (case["iid"],)).fetchone()[0] == "closed"
    assert (
        conn.execute("select kind from tasks where payload->>'feedback_id'=%s", (str(fid),)).fetchone()[0]
        == "closure_review"
    )


def test_atomic_application_and_concurrent_retry(seeded: str, conn: Any, monkeypatch: Any) -> None:
    cid = conn.execute("select id from clients order by id limit 1").fetchone()[0]
    case = make_case(conn, seeded, "operator-atomic", cid)
    conn.execute("update incidents set priority=3 where id=%s", (case["iid"],))
    fid = conn.execute(
        "insert into hitl_feedback(human_decision_id,idempotency_key,comment,recorded_by,recorded_sim) values (%s,'atomic','Срочные новые сведения для проверки','operator',now()) returning id",
        (case["hid"],),
    ).fetchone()[0]

    async def review(*args: Any, **kwargs: Any) -> Any:
        return {"summary_ru": "Нужна срочная проверка", "priority": 1, "next_step": "manual_review"}, {
            "provider": "mock",
            "usage": {},
        }

    monkeypatch.setattr(nodes, "_llm", review)
    recorder = nodes.Deps.record_step

    async def broken_record(*args: Any, **kwargs: Any) -> None:
        raise RuntimeError("synthetic trace failure after case updates")

    monkeypatch.setattr(nodes.Deps, "record_step", broken_record)

    async def first() -> None:
        async with await psycopg.AsyncConnection.connect(dsn(seeded)) as ac:
            assert not await process_feedback(ac, fid, mock_chain(), MOCK_PROFILE)

    asyncio.run(first())
    assert conn.execute("select priority from incidents where id=%s", (case["iid"],)).fetchone()[0] == 3
    assert conn.execute("select count(*) from tasks where payload->>'feedback_id'=%s", (str(fid),)).fetchone()[0] == 0
    assert (
        conn.execute(
            "select count(*) from incident_artifacts where meta->>'operator_feedback_id'=%s", (str(fid),)
        ).fetchone()[0]
        == 0
    )
    monkeypatch.setattr(nodes.Deps, "record_step", recorder)

    async def race() -> None:
        started = asyncio.Event()
        release = asyncio.Event()

        async def slow(*args: Any, **kwargs: Any) -> Any:
            started.set()
            await release.wait()
            return await review(*args, **kwargs)

        monkeypatch.setattr(nodes, "_llm", slow)
        async with (
            await psycopg.AsyncConnection.connect(dsn(seeded)) as first_conn,
            await psycopg.AsyncConnection.connect(dsn(seeded)) as second_conn,
        ):
            pending = asyncio.create_task(process_feedback(first_conn, fid, mock_chain(), MOCK_PROFILE))
            await asyncio.wait_for(started.wait(), timeout=5)
            assert not await process_feedback(second_conn, fid, mock_chain(), MOCK_PROFILE)
            release.set()
            assert await asyncio.wait_for(pending, timeout=5)

    asyncio.run(race())
    assert conn.execute("select count(*) from tasks where payload->>'feedback_id'=%s", (str(fid),)).fetchone()[0] == 1
    assert conn.execute("select priority from incidents where id=%s", (case["iid"],)).fetchone()[0] == 1


def test_startup_recovery_does_not_reset_fresh_public_run(seeded: str, conn: Any, monkeypatch: Any) -> None:
    import datetime as dt
    from unittest.mock import AsyncMock, Mock

    from app.agent import runner
    from app.agent.runner import AgentService

    cid = conn.execute("select id from clients order by id limit 1").fetchone()[0]
    old = make_case(conn, seeded, "recover-old", cid)
    fresh = make_case(conn, seeded, "recover-fresh", cid)
    service = AgentService(mock_chain(), MOCK_PROFILE, dsn=dsn(seeded))
    for case, stamp in [
        (old, service.started_at - dt.timedelta(seconds=1)),
        (fresh, service.started_at + dt.timedelta(seconds=1)),
    ]:
        conn.execute("update agent_runs set started_at=%s,outcome=null where signal_id=%s", (stamp, case["sid"]))
        conn.execute(
            "update signals set status='processing',channel_subtype='ui_pers_demo' where id=%s", (case["sid"],)
        )
    monkeypatch.setattr(runner, "expire_hitl", AsyncMock())
    monkeypatch.setattr(runner, "wake_due_followups", AsyncMock())
    monkeypatch.setattr(service, "submit", Mock())
    asyncio.run(service._recover())
    assert conn.execute("select outcome from agent_runs where signal_id=%s", (old["sid"],)).fetchone()[0] == "failed"
    assert conn.execute("select outcome from agent_runs where signal_id=%s", (fresh["sid"],)).fetchone()[0] is None
    assert conn.execute("select status from signals where id=%s", (fresh["sid"],)).fetchone()[0] == "processing"
    assert conn.execute("select status from signals where id=%s", (old["sid"],)).fetchone()[0] == "new"
