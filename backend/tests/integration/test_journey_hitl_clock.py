"""Native HITL/feedback Journey сохраняют часы собственного ручного кейса."""

from __future__ import annotations

import datetime as dt

import psycopg
import pytest
from starlette.requests import Request

from app.agent.runner import AgentService
from app.api.hitl import FeedbackBody, HitlDecisionBody, post_hitl_feedback, post_hitl_id
from app.config import get_settings
from tests.helpers import MOCK_PROFILE, dsn, mock_chain
from tests.integration.test_journey_execution_scope import bank_snapshot, native_case, setup

pytestmark = pytest.mark.integration


@pytest.mark.parametrize("explicit_override", [False, True])
async def test_journey_manual_hitl_decision_uses_own_clock_after_world_advances(seeded, monkeypatch, explicit_override):
    app, sim, request = await setup(monkeypatch, seeded)
    svc = None
    try:
        sid, state = await native_case(request, seeded, "journey-hitl-clock", "ultra_vip")
        assert state["outcome"] == "awaiting_human"
        async with await psycopg.AsyncConnection.connect(dsn(seeded)) as conn:
            hid, own_at = await (
                await conn.execute(
                    "select id,requested_sim from human_decisions where agent_run_id=%s", (state["agent_run_id"],)
                )
            ).fetchone()
            await conn.execute("update sim_state set sim_time=sim_time+interval '3 days' where id=1")
            await conn.commit()
            before = await bank_snapshot(conn)
        svc = app.state.agent = AgentService(mock_chain(), MOCK_PROFILE, dsn=seeded, sim=sim)
        decision_request = Request({"type": "http", "app": app, "headers": []})
        expected = own_at + dt.timedelta(hours=2) if explicit_override else own_at
        if explicit_override:
            decision_request.state.demo_sim_time = expected
        result = await post_hitl_id(decision_request, hid, HitlDecisionBody(decision="accept"))
        assert result["decided_sim"] == expected
        async with await psycopg.AsyncConnection.connect(dsn(seeded)) as conn:
            assert await bank_snapshot(conn) == before
            times = await (
                await conn.execute("select sent_sim from notifications where signal_id=%s", (sid,))
            ).fetchall()
            assert times and all(row[0] == expected for row in times)
            assert (
                await (
                    await conn.execute("select outcome from agent_runs where id=%s", (state["agent_run_id"],))
                ).fetchone()
            )[0] == "deferred"
    finally:
        if svc:
            await svc.stop()
        await sim.shutdown()
        get_settings.cache_clear()


async def test_journey_manual_feedback_uses_actual_case_clock_and_preserves_retry(seeded, monkeypatch):
    app, sim, request = await setup(monkeypatch, seeded)
    try:
        _sid, state = await native_case(request, seeded, "journey-feedback-clock", "ultra_vip")
        assert state["outcome"] == "awaiting_human"
        async with await psycopg.AsyncConnection.connect(dsn(seeded)) as conn:
            hid, rid, own_at = await (
                await conn.execute(
                    "select id,sim_run_id,requested_sim from human_decisions where agent_run_id=%s",
                    (state["agent_run_id"],),
                )
            ).fetchone()
            later = own_at + dt.timedelta(hours=3)
            await conn.execute("update sim_state set sim_time=sim_time+interval '3 days' where id=1")
            await conn.execute(
                "insert into notifications(run_id,recipient_type,channel_code,body,status,sent_sim) values(%s,'cx','internal','own feedback time fixture','sent',%s)",
                (rid, later),
            )
            await conn.commit()
            before = await bank_snapshot(conn)
        body = FeedbackBody(comment="Уточнение ручного кейса", idempotency_key="journey-feedback-once")
        first = await post_hitl_feedback(hid, body)
        assert first["recorded_sim"] == later
        async with await psycopg.AsyncConnection.connect(dsn(seeded)) as conn:
            assert await bank_snapshot(conn) == before
            await conn.execute("update sim_state set sim_time=sim_time+interval '7 days' where id=1")
        assert await post_hitl_feedback(hid, body) == first
    finally:
        await sim.shutdown()
        get_settings.cache_clear()
