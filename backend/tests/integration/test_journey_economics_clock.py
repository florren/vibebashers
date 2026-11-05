"""Native incident GET/действия Journey используют только часы своего кейса."""

from __future__ import annotations

import datetime as dt

import psycopg
import pytest
from starlette.requests import Request

from app.api.incidents import ActionBody, get_incidents_id_economics, post_incidents_id_actions
from app.config import get_settings
from tests.helpers import dsn
from tests.integration.test_journey_execution_scope import bank_snapshot, native_case, setup

pytestmark = pytest.mark.integration


@pytest.mark.parametrize("world_days", [-3, 3])
async def test_journey_economics_poll_and_manual_reply_preserve_own_case_clock(seeded, monkeypatch, world_days):
    app, sim, request = await setup(monkeypatch, seeded)
    try:
        sid, state = await native_case(request, seeded, "journey-economics-clock", "mass")
        assert state["outcome"] == "deferred"
        async with await psycopg.AsyncConnection.connect(dsn(seeded)) as conn:
            iid, rid, created = await (
                await conn.execute(
                    "select i.id,i.run_id,i.created_sim from incidents i join incident_signals x on x.incident_id=i.id where x.signal_id=%s",
                    (sid,),
                )
            ).fetchone()
            own_at = created + dt.timedelta(hours=3)
            # Явный совершившийся факт собственного кейса; не planned due и не часы World.
            await conn.execute(
                "insert into notifications(run_id,recipient_type,channel_code,body,status,sent_sim) values(%s,'cx','internal','actual own case clock fixture','sent',%s)",
                (rid, own_at),
            )
            await conn.execute(
                "update sim_state set sim_time=sim_time+make_interval(days=>%s) where id=1", (world_days,)
            )
            await conn.commit()
            bank_before = await bank_snapshot(conn)
        operator = Request({"type": "http", "app": app, "headers": []})
        first = await get_incidents_id_economics(operator, iid)
        assert first["computed_sim"] == own_at
        async with await psycopg.AsyncConnection.connect(dsn(seeded)) as conn:
            saved_first = (
                await (
                    await conn.execute(
                        "select to_jsonb(e)-'computed_at' from incident_economics e where incident_id=%s", (iid,)
                    )
                ).fetchone()
            )[0]
            assert await bank_snapshot(conn) == bank_before
            await conn.execute("update sim_state set sim_time=sim_time+interval '7 days' where id=1")
            await conn.commit()
            bank_later = await bank_snapshot(conn)
        second = await get_incidents_id_economics(operator, iid)
        assert second == first
        async with await psycopg.AsyncConnection.connect(dsn(seeded)) as conn:
            assert (
                await (
                    await conn.execute(
                        "select to_jsonb(e)-'computed_at' from incident_economics e where incident_id=%s", (iid,)
                    )
                ).fetchone()
            )[0] == saved_first
            assert await bank_snapshot(conn) == bank_later
        await post_incidents_id_actions(
            operator, iid, ActionBody(action="reply_client", text="Ручной ответ по собственному обращению")
        )
        async with await psycopg.AsyncConnection.connect(dsn(seeded)) as conn:
            replies = await (
                await conn.execute(
                    "select sent_sim from notifications where incident_id=%s and template_code='manual_reply'", (iid,)
                )
            ).fetchall()
            assert replies == [(own_at,)]
            assert (
                await (
                    await conn.execute("select computed_sim from incident_economics where incident_id=%s", (iid,))
                ).fetchone()
            )[0] == own_at
            assert await bank_snapshot(conn) == bank_later
    finally:
        await sim.shutdown()
        get_settings.cache_clear()


async def test_journey_default_producer_and_recompute_preserve_own_economics_clock(seeded, monkeypatch):
    from app.economics import dcltv

    app, sim, request = await setup(monkeypatch, seeded)
    try:
        sid, state = await native_case(request, seeded, "journey-recompute-clock", "mass")
        assert state["outcome"] == "deferred"
        async with await psycopg.AsyncConnection.connect(dsn(seeded)) as conn:
            iid, rid, created = await (
                await conn.execute(
                    "select i.id,i.run_id,i.created_sim from incidents i join incident_signals x on x.incident_id=i.id where x.signal_id=%s",
                    (sid,),
                )
            ).fetchone()
            own_at = created + dt.timedelta(hours=3)
            await conn.execute(
                "insert into notifications(run_id,recipient_type,channel_code,body,status,sent_sim) values(%s,'cx','internal','actual own recompute clock fixture','sent',%s)",
                (rid, own_at),
            )
            await conn.execute("update sim_state set sim_time=sim_time+interval '3 days' where id=1")
            await conn.commit()
            before = await bank_snapshot(conn)
            first = await dcltv.compute_incident(conn, iid)
            assert first is not None and first["computed_sim"] == own_at
            saved = (
                await (
                    await conn.execute(
                        "select to_jsonb(e)-'computed_at' from incident_economics e where incident_id=%s", (iid,)
                    )
                ).fetchone()
            )[0]
            assert await bank_snapshot(conn) == before
            await conn.execute("update sim_state set sim_time=sim_time+interval '7 days' where id=1")
            await conn.commit()
            later = await bank_snapshot(conn)
            assert await dcltv.recompute(conn, run_id=rid, only_stale=False) == 1
            assert (
                await (
                    await conn.execute(
                        "select to_jsonb(e)-'computed_at' from incident_economics e where incident_id=%s", (iid,)
                    )
                ).fetchone()
            )[0] == saved
            assert (await dcltv.compute_incident(conn, iid)) == first
            assert await bank_snapshot(conn) == later
    finally:
        await sim.shutdown()
        get_settings.cache_clear()
