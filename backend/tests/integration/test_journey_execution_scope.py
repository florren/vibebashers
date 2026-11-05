"""Journey владеет только явным ручным case, не глобальными часами/профилем."""

from __future__ import annotations

import json
from types import SimpleNamespace
from unittest.mock import AsyncMock

import psycopg
import pytest
from fastapi import HTTPException
from starlette.requests import Request

from app.api.ingest import post_ingest_messages
from app.config import get_settings
from app.demo import execution
from app.demo.settings import configuration
from app.main import create_app
from app.sim.engine import Simulator
from tests.helpers import MOCK_PROFILE, dsn, mock_chain

pytestmark = pytest.mark.integration
OPTIONS = {
    "scenario_id": "demo20_01_branch_queue",
    "team_outcome": "failed",
    "emulate_humans": False,
    "auto_advance": True,
}


def message(key, *, options=None, parent=None):
    meta = {"journey_execution": dict(OPTIONS if options is None else options)}
    if parent is not None:
        meta["parent_signal_id"] = parent
    return {
        "channel": "chat",
        "external_id": key,
        "client": {},
        "text": "Не открывается вклад в приложении, ошибка 503.",
        "timestamp": "2026-11-10T10:00:00Z",
        "geo": {"source": "none"},
        "origin": "jury",
        "meta": meta,
    }


async def bank_snapshot(conn):
    state = await (await conn.execute("select to_jsonb(s) from sim_state s where id=1")).fetchone()
    settings = await (await conn.execute("select key,value,updated_at from settings order by key")).fetchall()
    return state, settings


async def setup(monkeypatch, seeded):
    monkeypatch.setenv("DATABASE_URL", seeded)
    get_settings.cache_clear()
    app = create_app()
    app.state.agent = SimpleNamespace(enabled=False)
    sim = app.state.sim = Simulator(dsn=seeded)
    sim.full_execution = True
    await sim.load_state()
    await sim.control("start", label="Ambient world", start_paused=True)
    request = Request({"type": "http", "app": app, "headers": [(b"x-source-code", b"journey")]})
    return app, sim, request


async def send(request, body):
    response = await post_ingest_messages(request, body)
    return json.loads(response.body)["items"][0]


async def test_journey_manual_ingest_preserves_global_pointer_clock_rng_and_settings(seeded, monkeypatch):
    app, sim, request = await setup(monkeypatch, seeded)
    try:
        async with await psycopg.AsyncConnection.connect(dsn(seeded)) as conn:
            before = await bank_snapshot(conn)
        item = await send(request, message("journey-isolated-root"))
        assert item["status"] == "accepted"
        async with await psycopg.AsyncConnection.connect(dsn(seeded)) as conn:
            assert await bank_snapshot(conn) == before
            row = await (
                await conn.execute(
                    "select s.run_id,r.status,r.settings_snapshot from signals s join sim_runs r on r.id=s.run_id where s.id=%s",
                    (item["signal_id"],),
                )
            ).fetchone()
            assert row[0] != sim.run_id and row[1] == "paused"
            assert row[2]["created_by"] == "journey_demo"
            assert all(row[2]["demo_execution"][k] == v for k, v in OPTIONS.items())
            assert (await configuration(conn, sim.run_id))["scenario_id"] is None
        plain = message("ordinary-api-after-journey")
        plain["meta"] = {}
        other = Request({"type": "http", "app": app, "headers": [(b"x-source-code", b"api")]})
        outside = await send(other, plain)
        assert outside["status"] == "accepted"
        async with await psycopg.AsyncConnection.connect(dsn(seeded)) as conn:
            assert (
                await (await conn.execute("select run_id from signals where id=%s", (outside["signal_id"],))).fetchone()
            )[0] == sim.run_id
            assert (await configuration(conn, sim.run_id))["scenario_id"] is None
    finally:
        await sim.shutdown()
        get_settings.cache_clear()


async def test_journey_duplicates_and_children_preserve_immutable_case_context(seeded, monkeypatch):
    app, sim, request = await setup(monkeypatch, seeded)
    try:
        root = await send(request, message("journey-idempotent-root"))
        assert (await send(request, message("journey-idempotent-root")))["signal_id"] == root["signal_id"]
        child = await send(request, message("journey-idempotent-child", parent=root["signal_id"]))
        async with await psycopg.AsyncConnection.connect(dsn(seeded)) as conn:
            rows = await (
                await conn.execute(
                    "select run_id,parent_signal_id from signals where id=any(%s) order by id",
                    ([root["signal_id"], child["signal_id"]],),
                )
            ).fetchall()
            assert rows[0][0] == rows[1][0] and rows[1][1] == root["signal_id"]
            assert (
                await (
                    await conn.execute(
                        "select count(*) from sim_runs where settings_snapshot->>'created_by'='journey_demo'"
                    )
                ).fetchone()
            )[0] == 1
        changed = {**OPTIONS, "team_outcome": "on_time"}
        for body in [
            message("journey-idempotent-root", options=changed),
            message("new-child-profile", options=changed, parent=root["signal_id"]),
        ]:
            with pytest.raises(HTTPException) as rejected:
                await send(request, body)
            assert rejected.value.status_code == 422
    finally:
        await sim.shutdown()
        get_settings.cache_clear()


@pytest.mark.parametrize("source", ["api", "jury", "public"])
async def test_other_sources_cannot_apply_journey_options(seeded, monkeypatch, source):
    app, sim, request = await setup(monkeypatch, seeded)
    try:
        other = Request({"type": "http", "app": app, "headers": [(b"x-source-code", source.encode())]})
        async with await psycopg.AsyncConnection.connect(dsn(seeded)) as conn:
            before = await bank_snapshot(conn)
        with pytest.raises(HTTPException) as rejected:
            await send(other, message("not-journey-" + source))
        assert rejected.value.status_code == 422
        async with await psycopg.AsyncConnection.connect(dsn(seeded)) as conn:
            assert await bank_snapshot(conn) == before
            assert (
                await (
                    await conn.execute(
                        "select count(*) from sim_runs where settings_snapshot->>'created_by'='journey_demo'"
                    )
                ).fetchone()
            )[0] == 0
    finally:
        await sim.shutdown()
        get_settings.cache_clear()


async def test_simulation_cycle_never_constructs_second_team_executor(seeded, monkeypatch):
    app, sim, request = await setup(monkeypatch, seeded)
    monkeypatch.setattr(sim, "_start_loop", lambda: setattr(sim.clock, "running", True))
    await sim.control("resume")
    monkeypatch.setattr(execution, "employees", AsyncMock(return_value=False))

    class ForbiddenTeam:
        def __init__(self, *args, **kwargs):
            pytest.fail("whole-world cycle must not create second TeamEmulator")

    monkeypatch.setattr(execution, "TeamEmulator", ForbiddenTeam)
    try:
        # Paused native world: manual Journey configuration still cannot activate another world executor.
        await send(request, message("journey-before-world-cycle"))
        app.state.agent = SimpleNamespace(enabled=True, chain=mock_chain(), profile=MOCK_PROFILE)
        async with await psycopg.AsyncConnection.connect(dsn(seeded)) as conn:
            before = await bank_snapshot(conn)
        await execution.cycle(app)
        execution.employees.assert_awaited_once()
        async with await psycopg.AsyncConnection.connect(dsn(seeded)) as conn:
            assert await bank_snapshot(conn) == before
    finally:
        await sim.shutdown()
        get_settings.cache_clear()


async def test_duplicate_child_cannot_change_parent_to_another_case(seeded, monkeypatch):
    app, sim, request = await setup(monkeypatch, seeded)
    try:
        first = await send(request, message("parent-a"))
        second = await send(request, message("parent-b"))
        await send(request, message("stable-child", parent=first["signal_id"]))
        with pytest.raises(HTTPException) as rejected:
            await send(request, message("stable-child", parent=second["signal_id"]))
        assert rejected.value.status_code == 422
    finally:
        await sim.shutdown()
        get_settings.cache_clear()


async def test_native_journey_executor_scopes_outcome_to_own_case(seeded, monkeypatch):
    import asyncio

    from app.agent.runner import AgentService
    from app.demo.public import public_context
    from app.sim.teams import TeamEmulator

    app, sim, request = await setup(monkeypatch, seeded)
    svc = app.state.agent = AgentService(mock_chain(), MOCK_PROFILE, dsn=seeded)
    try:
        async with await psycopg.AsyncConnection.connect(dsn(seeded)) as conn:
            cid = (
                await (
                    await conn.execute("select id from clients where segment_code='mass' order by id limit 1")
                ).fetchone()
            )[0]
            before = await bank_snapshot(conn)
            public_rid, _ = await public_context(conn)
            public_profile = await configuration(conn, public_rid)
            await conn.commit()
        ids = []
        for index, outcome in enumerate(["failed", "on_time"]):
            body = message("native-case-" + str(index), options={**OPTIONS, "team_outcome": outcome})
            body["client"] = {"client_id": cid}
            item = await send(request, body)
            ids.append(item["signal_id"])
        if svc._inflight:
            await asyncio.gather(*list(svc._inflight))
        async with await psycopg.AsyncConnection.connect(dsn(seeded)) as conn:
            rows = await (
                await conn.execute(
                    "select s.id,s.run_id,a.outcome from signals s join agent_runs a on a.signal_id=s.id where s.id=any(%s) order by s.id",
                    (ids,),
                )
            ).fetchall()
            assert len(rows) == 2 and all(row[2] == "deferred" for row in rows)
            assert rows[0][1] != rows[1][1] and all(row[1] != sim.run_id for row in rows)
        seen = []
        original = TeamEmulator.tick

        async def observe(self, at, world):
            seen.append((self.run_id, self.demo_outcome, tuple(self.incident_ids or [])))
            return await original(self, at, world)

        monkeypatch.setattr(TeamEmulator, "tick", observe)
        await execution.public_cycle(app)
        assert {(rid, outcome) for rid, outcome, _ in seen} == {(rows[0][1], "failed"), (rows[1][1], "on_time")}
        assert all(incidents for _, _, incidents in seen)
        async with await psycopg.AsyncConnection.connect(dsn(seeded)) as conn:
            assert await bank_snapshot(conn) == before
            assert await configuration(conn, public_rid) == public_profile
            for rid, _outcome, incidents in seen:
                assert all(
                    r[0] == rid
                    for r in await (
                        await conn.execute("select run_id from incidents where id=any(%s)", (list(incidents),))
                    ).fetchall()
                )
    finally:
        await svc.stop()
        await sim.shutdown()
        get_settings.cache_clear()


async def test_journey_child_clock_uses_only_actual_own_case_facts(seeded, monkeypatch):
    import datetime as dt

    app, sim, request = await setup(monkeypatch, seeded)
    try:
        root = await send(request, message("own-clock-root"))
        foreign = await send(request, message("foreign-clock-root"))
        async with await psycopg.AsyncConnection.connect(dsn(seeded)) as conn:
            before = await bank_snapshot(conn)
            rid, at = await (
                await conn.execute("select run_id,received_sim from signals where id=%s", (root["signal_id"],))
            ).fetchone()
            foreign_rid = (
                await (await conn.execute("select run_id from signals where id=%s", (foreign["signal_id"],))).fetchone()
            )[0]
            # Только синтетические DB receipts: ни внешних доставок, ни денег.
            for case, hours, status in [(rid, 3, "sent"), (rid, 12, "queued"), (foreign_rid, 9, "sent")]:
                await conn.execute(
                    "insert into notifications(run_id,recipient_type,channel_code,body,status,sent_sim) values(%s,'cx','internal','clock fixture',%s,%s)",
                    (case, status, at + dt.timedelta(hours=hours)),
                )
            await conn.execute(
                "insert into followups(sim_run_id,signal_id,wake_sim,reason) values(%s,%s,%s,'awaiting_client')",
                (rid, root["signal_id"], at + dt.timedelta(hours=24)),
            )
            await conn.commit()
        child = await send(request, message("own-clock-child", parent=root["signal_id"]))
        async with await psycopg.AsyncConnection.connect(dsn(seeded)) as conn:
            assert (
                await (
                    await conn.execute("select received_sim from signals where id=%s", (child["signal_id"],))
                ).fetchone()
            )[0] == at + dt.timedelta(hours=3)
            assert await bank_snapshot(conn) == before
    finally:
        await sim.shutdown()
        get_settings.cache_clear()


async def test_journey_rejects_parent_from_ordinary_world_input(seeded, monkeypatch):
    app, sim, request = await setup(monkeypatch, seeded)
    try:
        plain = message("ambient-parent")
        plain["meta"] = {}
        other = Request({"type": "http", "app": app, "headers": [(b"x-source-code", b"api")]})
        ambient = await send(other, plain)
        with pytest.raises(HTTPException) as rejected:
            await send(request, message("journey-foreign-parent", parent=ambient["signal_id"]))
        assert rejected.value.status_code == 422
        async with await psycopg.AsyncConnection.connect(dsn(seeded)) as conn:
            assert (
                await (
                    await conn.execute(
                        "select count(*) from sim_runs where settings_snapshot->>'created_by'='journey_demo'"
                    )
                ).fetchone()
            )[0] == 0
    finally:
        await sim.shutdown()
        get_settings.cache_clear()


async def native_case(request, seeded, key, segment, text=None):
    from app.agent import graph

    async with await psycopg.AsyncConnection.connect(dsn(seeded)) as conn:
        cid = (
            await (
                await conn.execute("select id from clients where segment_code=%s order by id limit 1", (segment,))
            ).fetchone()
        )[0]
    body = message(key)
    body["client"] = {"client_id": cid}
    if text:
        body["text"] = text
    item = await send(request, body)
    async with await psycopg.AsyncConnection.connect(dsn(seeded)) as conn:
        at = (
            await (await conn.execute("select received_sim from signals where id=%s", (item["signal_id"],))).fetchone()
        )[0]
        state = await graph.process_signal(
            conn, signal_id=item["signal_id"], chain=mock_chain(), profile=MOCK_PROFILE, sim_time=at
        )
    return item["signal_id"], state


async def test_world_sla_event_cannot_wake_or_expire_private_journey_cases(seeded, monkeypatch):
    import asyncio
    import datetime as dt

    from app.agent.runner import AgentService

    app, sim, request = await setup(monkeypatch, seeded)
    svc = None
    try:
        sid, parked = await native_case(request, seeded, "private-timer", "mass")
        _vip, human = await native_case(request, seeded, "private-human", "ultra_vip")
        assert parked["outcome"] == "deferred" and human["outcome"] == "awaiting_human"
        async with await psycopg.AsyncConnection.connect(dsn(seeded)) as conn:
            before_fups = await (
                await conn.execute("select id,status,wake_sim from followups where signal_id=%s order by id", (sid,))
            ).fetchall()
            before_human = await (
                await conn.execute(
                    "select id,decision,decided_at from human_decisions where agent_run_id=%s", (human["agent_run_id"],)
                )
            ).fetchall()
            assert before_fups and before_human
        sim.clock.sim_time += dt.timedelta(days=3)
        await sim.persist()
        await sim.conn.commit()
        svc = app.state.agent = AgentService(mock_chain(), MOCK_PROFILE, dsn=seeded)
        await svc._notification(
            SimpleNamespace(
                channel="sim_events",
                payload=json.dumps(
                    {"event_type": "sla.tick", "run_id": sim.run_id, "sim_time": sim.clock.sim_time.isoformat()}
                ),
            )
        )
        if svc._inflight:
            await asyncio.gather(*list(svc._inflight))
        async with await psycopg.AsyncConnection.connect(dsn(seeded)) as conn:
            assert (
                await (
                    await conn.execute(
                        "select id,status,wake_sim from followups where signal_id=%s order by id", (sid,)
                    )
                ).fetchall()
                == before_fups
            )
            assert (
                await (
                    await conn.execute(
                        "select id,decision,decided_at from human_decisions where agent_run_id=%s",
                        (human["agent_run_id"],),
                    )
                ).fetchall()
                == before_human
            )
    finally:
        if svc:
            await svc.stop()
        await sim.shutdown()
        get_settings.cache_clear()


async def test_tracking_reply_queue_uses_private_child_received_time(seeded, monkeypatch):
    import datetime as dt

    from app.agent.runner import AgentService
    from tests.integration.test_followups import FRAUD_TEXT

    app, sim, request = await setup(monkeypatch, seeded)
    svc = None
    try:
        sid, state = await native_case(request, seeded, "private-reply-root", "premium", FRAUD_TEXT)
        assert state["outcome"] == "deferred"
        async with await psycopg.AsyncConnection.connect(dsn(seeded)) as conn:
            rid, at = await (
                await conn.execute("select run_id,received_sim from signals where id=%s", (sid,))
            ).fetchone()
            assert (
                await (
                    await conn.execute(
                        "select count(*) from followups where signal_id=%s and reason='awaiting_client' and status='scheduled'",
                        (sid,),
                    )
                ).fetchone()
            )[0] == 1
            await conn.execute(
                "insert into notifications(run_id,recipient_type,channel_code,body,status,sent_sim) values(%s,'cx','internal','own reply clock fixture','sent',%s)",
                (rid, at + dt.timedelta(hours=3)),
            )
            await conn.commit()
        child = await send(request, message("private-reply-child", parent=sid))
        sim.clock.sim_time = at + dt.timedelta(days=3)
        await sim.persist()
        await sim.conn.commit()
        svc = AgentService(mock_chain(), MOCK_PROFILE, dsn=seeded)
        seen = []
        monkeypatch.setattr(svc, "submit_client_reply", lambda parent, reply, time: seen.append((parent, reply, time)))
        await svc._reply_cycle()
        assert seen == [(sid, child["signal_id"], at + dt.timedelta(hours=3))]
    finally:
        if svc:
            await svc.stop()
        await sim.shutdown()
        get_settings.cache_clear()


async def test_restart_recovers_private_durable_checkpoint_without_global_pointer_change(seeded, monkeypatch):
    from app.agent import graph
    from app.agent.runner import AgentService

    class ProcessCrash(BaseException):
        pass

    app, sim, request = await setup(monkeypatch, seeded)
    svc = None
    try:
        async with await psycopg.AsyncConnection.connect(dsn(seeded)) as conn:
            cid = (
                await (
                    await conn.execute("select id from clients where segment_code='mass' order by id limit 1")
                ).fetchone()
            )[0]
        body = message("restart-private-root")
        body["client"] = {"client_id": cid}
        item = await send(request, body)
        original = graph._execute_node

        async def crash(node, state, deps, conn):
            if node == "followup_monitor":
                raise ProcessCrash()
            return await original(node, state, deps, conn)

        monkeypatch.setattr(graph, "_execute_node", crash)
        async with await psycopg.AsyncConnection.connect(dsn(seeded)) as conn:
            at = (
                await (
                    await conn.execute("select received_sim from signals where id=%s", (item["signal_id"],))
                ).fetchone()
            )[0]
            with pytest.raises(ProcessCrash):
                await graph.process_signal(
                    conn, signal_id=item["signal_id"], chain=mock_chain(), profile=MOCK_PROFILE, sim_time=at
                )
            arid, rid, outcome = await (
                await conn.execute(
                    "select id,sim_run_id,outcome from agent_runs where signal_id=%s and kind='agent'",
                    (item["signal_id"],),
                )
            ).fetchone()
            assert outcome is None
            assert (
                await (
                    await conn.execute(
                        "select count(*) from langgraph.checkpoints where thread_id=%s", (f"{rid}:{item['signal_id']}",)
                    )
                ).fetchone()
            )[0] > 0
            before = await bank_snapshot(conn)
            before_notifications = (
                await (await conn.execute("select count(*) from notifications where run_id=%s", (rid,))).fetchone()
            )[0]
        monkeypatch.setattr(graph, "_execute_node", original)
        svc = app.state.agent = AgentService(mock_chain(), MOCK_PROFILE, dsn=seeded)
        await svc._recover()
        await execution.public_cycle(app)
        async with await psycopg.AsyncConnection.connect(dsn(seeded)) as conn:
            assert await bank_snapshot(conn) == before
            assert (
                await (
                    await conn.execute(
                        "select id,outcome,interrupted_at from agent_runs where signal_id=%s and kind='agent'",
                        (item["signal_id"],),
                    )
                ).fetchone()
            ) == (arid, "deferred", None)
            assert (
                await (await conn.execute("select count(*) from notifications where run_id=%s", (rid,))).fetchone()
            )[0] == before_notifications
    finally:
        if svc:
            await svc.stop()
        await sim.shutdown()
        get_settings.cache_clear()


async def test_ordinary_untracked_parent_is_not_enrolled_in_journey_reply_queue(seeded, monkeypatch):
    from app.agent import graph
    from app.agent.runner import AgentService
    from tests.integration.test_followups import FRAUD_TEXT

    app, sim, request = await setup(monkeypatch, seeded)
    svc = None
    other = Request({"type": "http", "app": app, "headers": [(b"x-source-code", b"api")]})
    try:
        async with await psycopg.AsyncConnection.connect(dsn(seeded)) as conn:
            cid = (
                await (
                    await conn.execute("select id from clients where segment_code='premium' order by id limit 1")
                ).fetchone()
            )[0]
        body = message("ordinary-untracked-parent")
        body["meta"] = {}
        body["text"] = FRAUD_TEXT
        body["client"] = {"client_id": cid}
        parent = await send(other, body)
        async with await psycopg.AsyncConnection.connect(dsn(seeded)) as conn:
            at = (
                await (
                    await conn.execute("select received_sim from signals where id=%s", (parent["signal_id"],))
                ).fetchone()
            )[0]
            state = await graph.process_signal(
                conn, signal_id=parent["signal_id"], chain=mock_chain(), profile=MOCK_PROFILE, sim_time=at
            )
            assert state["outcome"] == "deferred"
            assert (
                await (
                    await conn.execute("select tracking_token from signals where id=%s", (parent["signal_id"],))
                ).fetchone()
            )[0] is None
        child_body = message("ordinary-untracked-child")
        child_body["meta"] = {"parent_signal_id": parent["signal_id"]}
        await send(other, child_body)
        svc = AgentService(mock_chain(), MOCK_PROFILE, dsn=seeded)
        seen = []
        monkeypatch.setattr(svc, "submit_client_reply", lambda *args: seen.append(args))
        await svc._reply_cycle()
        assert seen == []
    finally:
        if svc:
            await svc.stop()
        await sim.shutdown()
        get_settings.cache_clear()
