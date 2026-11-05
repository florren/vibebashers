"""Общие кнопки, сотрудники и оба ручных входа проходят один управляемый цикл."""

import asyncio
import datetime as dt

import psycopg
import pytest
from fastapi import HTTPException
from starlette.requests import Request

from app.agent.runner import AgentService
from app.api.demo_execution import DemoExecutionBody, post_demo_execution
from app.api.ingest import post_ingest_messages
from app.api.signals import SignalCreate, post_signals
from app.api.sim import SimControlRequest, post_sim_control, post_sim_runs_id_resume, post_sim_runs_id_stop
from app.config import get_settings
from app.demo.execution import configuration, cycle, employees
from app.main import create_app
from app.sim.engine import Simulator
from app.sim.events import EventBus
from app.sim.rng import SimRng
from app.sim.teams import TeamEmulator
from tests.helpers import MOCK_PROFILE, dsn, mock_chain

pytestmark = pytest.mark.integration


def app_for(monkeypatch, seeded):
    monkeypatch.setenv("DATABASE_URL", seeded)
    get_settings.cache_clear()
    app = create_app()
    app.state.agent = AgentService(mock_chain(), MOCK_PROFILE, dsn=seeded)
    sim = app.state.sim = Simulator(dsn=seeded)
    sim._intensities = dict.fromkeys(("op", "fault", "client_error", "signal_noise"), 0.0)
    # Время меняется только явными вызовами API: фоновые тики проверяются отдельным HTTP-smoke.
    monkeypatch.setattr(sim, "_start_loop", lambda: setattr(sim.clock, "running", True))
    app.state.llm_chain, app.state.llm_profile = app.state.agent.chain, MOCK_PROFILE
    return app, Request({"type": "http", "app": app, "headers": []})


async def native_listener_barrier(app, seeded):
    """Настоящий LISTEN: probe после commit подтверждает доставку предшествующих событий."""
    import json
    import uuid

    svc = app.state.agent
    box = getattr(svc, "_fixture_listener_barrier", None)
    if box is None:
        box = {"nonce": None, "ready": asyncio.Event()}
        original = svc._notification

        async def observed(notification):
            body = json.loads(notification.payload)
            if body.get("event_type") == "test.listener.barrier":
                if body.get("nonce") == box["nonce"]:
                    box["ready"].set()
                return
            await original(notification)

        svc._notification = observed
        svc._fixture_listener_barrier = box
        svc.start(recover=False)
    box["nonce"] = str(uuid.uuid4())
    box["ready"].clear()
    async with await psycopg.AsyncConnection.connect(dsn(seeded), autocommit=True) as conn:
        async with asyncio.timeout(10):
            while not box["ready"].is_set():
                await conn.execute(
                    "select pg_notify('sim_events',%s)",
                    (json.dumps({"event_type": "test.listener.barrier", "nonce": box["nonce"]}),),
                )
                try:
                    await asyncio.wait_for(box["ready"].wait(), 0.05)
                except TimeoutError:
                    continue
    while svc._inflight:
        await asyncio.gather(*list(svc._inflight))


async def finish_shared(app, request, seeded):
    sim, svc = app.state.sim, app.state.agent
    await native_listener_barrier(app, seeded)
    for _ in range(45):
        if svc._inflight:
            await asyncio.gather(*list(svc._inflight))
        await cycle(app)
        # Фоновый loop заглушён фикстурой: команды running World продвигает
        # настоящий tick, а не отдельный demo-cycle executor.
        await post_sim_control(request, SimControlRequest(action="step", step_minutes=15))
        await native_listener_barrier(app, seeded)
        async with await psycopg.AsyncConnection.connect(dsn(seeded)) as conn:
            runner = TeamEmulator(SimRng(42), conn, EventBus(conn), sim.run_id)
            await runner.load()
            future = [
                s.at
                for p in runner.plans.values()
                for s in p.steps
                if s.at > sim.clock.sim_time
                and not s.skipped
                and (p.incident_id, s.action, s.report_day) not in runner.done
            ]
            if not future:
                future = [
                    r[0]
                    for r in await (
                        await conn.execute(
                            "select f.wake_sim from followups f join agent_runs a on a.id=f.agent_run_id "
                            "where f.sim_run_id=%s and f.status='scheduled' and a.outcome='deferred' "
                            "and f.wake_sim>%s",
                            (sim.run_id, sim.clock.sim_time),
                        )
                    ).fetchall()
                ]
            open_count = (
                await (
                    await conn.execute(
                        "select (select count(*) from incidents where run_id=%s and status<>'closed') + "
                        "(select count(*) from agent_runs where sim_run_id=%s and kind='agent' "
                        "and (outcome is null or outcome in ('deferred','awaiting_human')))",
                        (sim.run_id, sim.run_id),
                    )
                ).fetchone()
            )[0]
        if future:
            await post_sim_control(request, SimControlRequest(action="jump_to", sim_time=min(future)))
        elif not open_count and not svc._inflight:
            return
    raise AssertionError("shared execution did not finish")


@pytest.mark.parametrize("entry", ["jury", "journey"])
@pytest.mark.parametrize("identified", [True, False])
async def test_manual_inputs_wait_for_resume_then_finish(seeded, monkeypatch, entry, identified):
    app, request = app_for(monkeypatch, seeded)
    sim, svc = app.state.sim, app.state.agent
    await sim.load_state()
    sim._intensities = dict.fromkeys(("op", "fault", "client_error", "signal_noise"), 0.0)
    try:
        # Здесь проверяется обычная пауза; ускоренный режим покрыт test_manual_execution.py.
        await post_demo_execution(request, DemoExecutionBody(mode="simulation", auto_advance=False))
        async with await psycopg.AsyncConnection.connect(dsn(seeded)) as conn:
            cid = (
                (
                    await (
                        await conn.execute("select id from clients where segment_code='ultra_vip' order by id limit 1")
                    ).fetchone()
                )[0]
                if identified
                else None
            )
        text = "Приложение зависает при открытии вклада, ошибка 503. Прошу устранить проблему и сообщить результат."
        if entry == "jury":
            result = await post_signals(request, SignalCreate(channel_code="chat", client_id=cid, text=text))
            sid = result["signal_id"]
        else:
            import json

            result = await post_ingest_messages(
                request,
                {
                    "channel": "chat",
                    "external_id": "manual-journey-regression",
                    "client": {"client_id": cid},
                    "text": text,
                    "timestamp": dt.datetime.now(dt.UTC).isoformat(),
                    "geo": {"source": "none"},
                    "origin": "jury",
                },
            )
            accepted = json.loads(result.body)["items"][0]
            assert accepted["status"] == "accepted", accepted
            sid = accepted["signal_id"]
        if svc._inflight:
            await asyncio.gather(*list(svc._inflight))
        assert sim.run_id != 1
        assert not sim.clock.running and sim.run_status == "paused"
        async with await psycopg.AsyncConnection.connect(dsn(seeded)) as conn:
            config = await configuration(conn, sim.run_id)
            assert config["mode"] == "simulation" and config["status"] == "paused"
            before = (
                await (
                    await conn.execute("select count(*) from team_actions where run_id=%s", (sim.run_id,))
                ).fetchone()
            )[0]
        await cycle(app)
        async with await psycopg.AsyncConnection.connect(dsn(seeded)) as conn:
            assert (
                await (
                    await conn.execute("select count(*) from team_actions where run_id=%s", (sim.run_id,))
                ).fetchone()
            )[0] == before
            assert (
                await (
                    await conn.execute(
                        "select count(*) from human_decisions where sim_run_id=%s and decision is not null",
                        (sim.run_id,),
                    )
                ).fetchone()
            )[0] == 0
        await post_sim_control(request, SimControlRequest(action="resume"))
        if entry == "jury" and identified:
            # Независимый ожидающий вход не должен блокировать уже готовые планы команд.
            from app.ingest.normalizer import create_signal

            async with await psycopg.AsyncConnection.connect(dsn(seeded)) as conn:
                await create_signal(
                    conn,
                    {
                        "channel": "chat",
                        "external_id": "unrelated-pending",
                        "text": "Независимое ожидающее обращение",
                        "origin": "jury",
                        "timestamp": sim.clock.sim_time.isoformat(),
                        "geo": {"source": "none"},
                    },
                    source_code="api",
                    run_id=sim.run_id,
                    emit_event=False,
                )
        await finish_shared(app, request, seeded)
        async with await psycopg.AsyncConnection.connect(dsn(seeded)) as conn:
            incident = await (
                await conn.execute(
                    "select i.status,i.resolution_summary from incidents i join incident_signals x on x.incident_id=i.id where x.signal_id=%s",
                    (sid,),
                )
            ).fetchone()
            assert incident[0] == "closed"
            notice = await (
                await conn.execute(
                    "select body,status from notifications where signal_id=%s and template_code='resolved'", (sid,)
                )
            ).fetchone()
            assert notice[1] == "sent"
            from app.agent import nodes
            from app.agent.checkpoints import TransactionalSaver
            from app.agent.tools.base import ToolContext
            from app.agent.tools.write import render_template

            arid, thread = await (
                await conn.execute("select id,thread_id from agent_runs where signal_id=%s and kind='agent'", (sid,))
            ).fetchone()
            saved = await TransactionalSaver(conn).aget_tuple({"configurable": {"thread_id": thread}})
            final = saved.checkpoint["channel_values"]
            client = final.get("client") or {}
            channel = ((final.get("decision") or {}).get("client_action") or {}).get("channel") or final["signal"][
                "channel"
            ]
            _, expected = await render_template(
                ToolContext(conn, run_id=sim.run_id, agent_run_id=arid, sim_time=sim.clock.sim_time),
                "resolved",
                channel,
                client.get("segment"),
                {
                    "name": nodes.mask_name(client.get("name")),
                    "resolution": incident[1] or (final.get("decision") or {}).get("title_ru") or "",
                },
                nodes.communication_lang(final["signal"]["text"]),
            )
            assert notice[0] == expected and "ваш вопрос решён" in notice[0]
            assert incident[1] is None or incident[1] not in notice[0]
            assert "стенд" not in notice[0].lower()
            if identified:
                decisions = await (
                    await conn.execute(
                        "select decision,decided_by from human_decisions where sim_run_id=%s", (sim.run_id,)
                    )
                ).fetchall()
                assert decisions and all(d[0] and d[1].startswith("demo-agent:operator:") for d in decisions)
    finally:
        await svc.stop()
        await sim.shutdown()
        get_settings.cache_clear()


@pytest.mark.parametrize("endpoint", ["header", "run"])
async def test_scenario_controls_stop_everything(seeded, monkeypatch, endpoint):
    app, request = app_for(monkeypatch, seeded)
    sim, svc = app.state.sim, app.state.agent
    await sim.load_state()
    sim._intensities = dict.fromkeys(("op", "fault", "client_error", "signal_noise"), 0.0)
    try:
        state = await post_demo_execution(request, DemoExecutionBody(scenario_id="demo20_01_branch_queue"))
        assert sim.clock.running and sim._task is None
        if svc._inflight:
            await asyncio.gather(*list(svc._inflight))
        await cycle(app)
        await post_sim_control(request, SimControlRequest(action="pause"))
        at = sim.clock.sim_time
        await cycle(app)
        assert sim.clock.sim_time == at
        if endpoint == "header":
            await post_sim_control(request, SimControlRequest(action="resume"))
        else:
            await post_sim_runs_id_resume(request, state["run_id"])
        assert sim.clock.running
        await cycle(app)
        if endpoint == "header":
            await post_sim_control(request, SimControlRequest(action="stop"))
        else:
            await post_sim_runs_id_stop(request, state["run_id"])
        at = sim.clock.sim_time
        for _ in range(3):
            await cycle(app)
        assert sim.clock.sim_time == at and not sim.clock.running
        async with await psycopg.AsyncConnection.connect(dsn(seeded)) as conn:
            config = await configuration(conn, state["run_id"])
            assert config["status"] == "stopped" and not config["enabled"]
        if endpoint == "run":
            # T-041: stopped — terminal; новый сценарий запускается явно, без Resume.
            with pytest.raises(HTTPException) as rejected:
                await post_sim_runs_id_resume(request, state["run_id"])
            assert rejected.value.status_code == 409
            assert sim.clock.sim_time == at and not sim.clock.running
            async with await psycopg.AsyncConnection.connect(dsn(seeded)) as conn:
                stopped = await configuration(conn, state["run_id"])
                assert stopped["status"] == "stopped" and not stopped["enabled"]
            restarted = await post_demo_execution(request, DemoExecutionBody(scenario_id="demo20_01_branch_queue"))
            assert restarted["run_id"] != state["run_id"]
            assert sim.clock.running and sim._task is None
        else:
            await post_sim_control(request, SimControlRequest(action="start"))
            assert sim.clock.running and sim.run_id != state["run_id"]
    finally:
        await svc.stop()
        await sim.shutdown()
        get_settings.cache_clear()


async def test_jury_does_not_inherit_other_scenario_facts(seeded, monkeypatch):
    app, request = app_for(monkeypatch, seeded)
    sim, svc = app.state.sim, app.state.agent
    await sim.load_state()
    sim._intensities = dict.fromkeys(("op", "fault", "client_error", "signal_noise"), 0.0)
    try:
        await post_demo_execution(request, DemoExecutionBody(scenario_id="demo20_01_branch_queue"))
        res = await post_signals(
            request,
            SignalCreate(
                channel_code="chat",
                text="Мобильное приложение не работает при оплате, ошибка 503. Прошу исправить сбой.",
            ),
        )
        for _ in range(40):
            if svc._inflight:
                await asyncio.gather(*list(svc._inflight))
            await cycle(app)
        async with await psycopg.AsyncConnection.connect(dsn(seeded)) as conn:
            row = await (
                await conn.execute(
                    "select i.status,i.resolution_summary from incidents i join incident_signals x on x.incident_id=i.id where x.signal_id=%s",
                    (res["signal_id"],),
                )
            ).fetchone()
            assert row[0] == "closed"
            assert "согласованного маршрута обслуживания" not in row[1]
            assert "Внешние действия и движение денег не выполнялись" in row[1]
    finally:
        await svc.stop()
        await sim.shutdown()
        get_settings.cache_clear()


@pytest.mark.parametrize("action", ["pause", "stop"])
async def test_employee_reply_in_flight_cannot_commit_after_control(seeded, monkeypatch, action):
    from app.agent.graph import process_signal
    from app.demo.settings import save
    from app.sim import scenarios
    from tests.helpers import new_run, sim_now

    app, request = app_for(monkeypatch, seeded)
    sim, svc = app.state.sim, app.state.agent
    await sim.load_state()
    started, release = asyncio.Event(), asyncio.Event()

    async def delayed(*args, **kwargs):
        started.set()
        await release.wait()
        return {"body": "Согласовано", "decision": "accept"}, {"source": "mock", "model": "mock"}

    monkeypatch.setattr("app.demo.execution.respond", delayed)
    try:
        async with await psycopg.AsyncConnection.connect(dsn(seeded)) as conn:
            rid = await new_run(conn, "inflight operator", scenario_id="deposit_promo_rate")
            sim.run_id, sim.run_status = rid, "running"
            sim.clock.running = True
            await save(conn, rid, {"mode": "demo", "enabled": True, "status": "running", "emulate_humans": True})
            item = (
                await scenarios.inject(
                    conn,
                    {
                        "id": "deposit_promo_rate",
                        "inject": [
                            {
                                "channel": "chat",
                                "client": {"segment": "ultra_vip"},
                                "text": "Не могу открыть вклад, приложение зависло с ошибкой 503. Прошу решить проблему.",
                            }
                        ],
                    },
                    rid,
                    sim_time=await sim_now(conn),
                )
            )[0]
            await conn.commit()
            state = await process_signal(conn, signal_id=item["signal_id"], chain=mock_chain(), profile=MOCK_PROFILE)
            assert state["outcome"] == "awaiting_human"
            task = asyncio.create_task(employees(app, conn, rid, sim.clock.sim_time))
            await asyncio.wait_for(started.wait(), 2)
            await post_sim_control(request, SimControlRequest(action=action))
            release.set()
            assert await task is False
            assert (
                await (
                    await conn.execute("select decision from human_decisions where sim_run_id=%s", (rid,))
                ).fetchone()
            )[0] is None
    finally:
        release.set()
        await svc.stop()
        await sim.shutdown()
        get_settings.cache_clear()


async def test_pause_rolls_back_partial_bank_tick(seeded, monkeypatch):
    from app.sim.generators import World

    sim = Simulator(dsn=seeded)
    await sim.load_state()
    entered = asyncio.Event()

    async def no_faults(*args):
        return 0

    async def pending_ops(world, *args):
        await world.conn.execute("insert into settings(key,value) values ('partial_tick_probe','true'::jsonb)")
        world.rng.random()
        entered.set()
        await asyncio.Event().wait()

    monkeypatch.setattr(World, "gen_faults", no_faults)
    monkeypatch.setattr(World, "gen_operations", pending_ops)
    try:
        await sim.control("start")
        await asyncio.wait_for(entered.wait(), 5)
        # World.load уже завершён, дальше отменяется только незавершённый тик.
        at = sim.clock.sim_time
        await sim.control("pause")
        assert not sim.clock.running and sim.clock.sim_time == at
        async with await psycopg.AsyncConnection.connect(dsn(seeded)) as conn:
            assert (
                await (await conn.execute("select value from settings where key='partial_tick_probe'")).fetchone()
                is None
            )
        assert sim.world is not None
        assert not sim.world.pending
    finally:
        await sim.shutdown()


async def test_concurrent_manual_prepare_reuses_run(seeded, monkeypatch):
    from app.demo.inputs import prepare

    app, request = app_for(monkeypatch, seeded)
    sim = app.state.sim
    await sim.load_state()
    initial = sim.run_id

    async def submit():
        async with await psycopg.AsyncConnection.connect(dsn(seeded), autocommit=True) as conn:
            return await prepare(request, conn, initial)

    try:
        ids = await asyncio.gather(submit(), submit())
        assert ids[0] == ids[1] == sim.run_id
        assert ids[0] != initial
    finally:
        await app.state.agent.stop()
        await sim.shutdown()
        get_settings.cache_clear()


async def test_shared_profile_survives_stop_and_new_start(seeded, monkeypatch):
    app, request = app_for(monkeypatch, seeded)
    sim = app.state.sim
    await sim.load_state()
    try:
        state = await post_demo_execution(
            request, DemoExecutionBody(mode="simulation", team_outcome="late", emulate_humans=False)
        )
        assert state["configuration"]["status"] == "paused"
        await post_sim_control(request, SimControlRequest(action="stop"))
        await post_sim_control(request, SimControlRequest(action="start"))
        assert sim.run_id != state["run_id"] and sim.clock.running
        async with await psycopg.AsyncConnection.connect(dsn(seeded)) as conn:
            config = await configuration(conn, sim.run_id)
        assert config["status"] == "running" and config["team_outcome"] == "late"
        assert not config["emulate_humans"] and config["mode"] == "simulation"
    finally:
        await app.state.agent.stop()
        await sim.shutdown()
        get_settings.cache_clear()


@pytest.mark.parametrize("status", ["routed", "escalated"])
async def test_shared_teams_progress_with_continuous_employee_work(seeded, monkeypatch, status):
    app, request = app_for(monkeypatch, seeded)
    sim, svc = app.state.sim, app.state.agent
    await sim.load_state()
    try:
        await post_signals(
            request,
            SignalCreate(
                channel_code="chat", text="Мобильное приложение зависает с ошибкой 503, невозможно оплатить покупку."
            ),
        )
        if svc._inflight:
            await asyncio.gather(*list(svc._inflight))
        await post_sim_control(request, SimControlRequest(action="resume"))

        async def another_employee_decided(*args, **kwargs):
            return True

        monkeypatch.setattr("app.demo.execution.employees", another_employee_decided)
        await native_listener_barrier(app, seeded)
        await post_sim_control(request, SimControlRequest(action="step", step_minutes=15))
        async with await psycopg.AsyncConnection.connect(dsn(seeded)) as conn:
            plans = TeamEmulator(SimRng(42), conn, EventBus(conn), sim.run_id)
            await plans.load()
            future = [
                step.at
                for plan in plans.plans.values()
                for step in plan.steps
                if not step.skipped and step.at > sim.clock.sim_time
            ]
        if future:
            await post_sim_control(request, SimControlRequest(action="jump_to", sim_time=min(future)))
        await native_listener_barrier(app, seeded)
        if status == "escalated":
            # Законный native take уже зафиксирован: эскалация не создаёт фиктивный demo-take.
            async with await psycopg.AsyncConnection.connect(dsn(seeded)) as conn:
                await conn.execute("update incidents set status='escalated' where run_id=%s", (sim.run_id,))
                plans = TeamEmulator(SimRng(42), conn, EventBus(conn), sim.run_id)
                await plans.load()
                future = [
                    step.at
                    for plan in plans.plans.values()
                    for step in plan.steps
                    if not step.skipped and step.at > sim.clock.sim_time
                ]
            if future:
                await post_sim_control(request, SimControlRequest(action="jump_to", sim_time=min(future)))
            await native_listener_barrier(app, seeded)
        await cycle(app)
        async with await psycopg.AsyncConnection.connect(dsn(seeded)) as conn:
            actions = await (
                await conn.execute("select count(*) from team_actions where run_id=%s", (sim.run_id,))
            ).fetchone()
            take = await (
                await conn.execute("select payload from team_actions where run_id=%s and action='take'", (sim.run_id,))
            ).fetchone()
        assert actions[0] > 0 and take and take[0]["plan"]
    finally:
        await svc.stop()
        await sim.shutdown()
        get_settings.cache_clear()


async def test_shared_information_request_gets_team_final(seeded, monkeypatch):
    app, request = app_for(monkeypatch, seeded)
    sim, svc = app.state.sim, app.state.agent
    await sim.load_state()
    sim._intensities = dict.fromkeys(("op", "fault", "client_error", "signal_noise"), 0.0)
    try:
        async with await psycopg.AsyncConnection.connect(dsn(seeded)) as conn:
            cid = (
                await (
                    await conn.execute("select id from clients where segment_code='mass' order by id limit 1")
                ).fetchone()
            )[0]
        result = await post_signals(
            request,
            SignalCreate(
                channel_code="chat", client_id=cid, text="Подскажите, какие документы нужны, чтобы оформить вклад?"
            ),
        )
        await post_sim_control(request, SimControlRequest(action="resume"))
        await finish_shared(app, request, seeded)
        async with await psycopg.AsyncConnection.connect(dsn(seeded)) as conn:
            row = await (
                await conn.execute(
                    "select i.status from incidents i join incident_signals x on x.incident_id=i.id where x.signal_id=%s",
                    (result["signal_id"],),
                )
            ).fetchone()
            notice = await (
                await conn.execute(
                    "select status from notifications where signal_id=%s and template_code='resolved'",
                    (result["signal_id"],),
                )
            ).fetchone()
        assert row and row[0] == "closed" and notice and notice[0] == "sent"
    finally:
        await svc.stop()
        await sim.shutdown()
        get_settings.cache_clear()


@pytest.mark.parametrize("action,target", [("pause", "paused"), ("stop", "stopped")])
async def test_halt_takes_python_lock_before_row_write_against_manual_worker(seeded, monkeypatch, action, target):
    from app.demo.settings import save
    from app.sim import runs as run_svc

    class OwnedLock(asyncio.Lock):
        owner = None

        async def __aenter__(self):
            await super().__aenter__()
            self.owner = asyncio.current_task()
            return self

        async def __aexit__(self, *args):
            self.owner = None
            await super().__aexit__(*args)

    sim = Simulator(dsn=seeded)
    await sim.load_state()
    await sim.control("start", label="synthetic lock order", start_paused=True)
    rid, now, rng = sim.run_id, sim.clock.sim_time, sim.rng.dump_state()
    conn = await sim.connect()
    await save(conn, rid, {"mode": "full", "enabled": True, "status": "running"})
    await conn.execute("update sim_runs set status='running' where id=%s", (rid,))
    await conn.commit()
    sim.run_status, sim.clock.running = "running", True
    sim._lock = OwnedLock()
    stopped, worker_locked = asyncio.Event(), asyncio.Event()
    stop_loop = sim._stop_loop

    async def stop():
        await stop_loop()
        stopped.set()

    set_status = run_svc.set_run_status

    async def set_status_owned(*args, **kwargs):
        # Обе реальные DB connections используют lock→row, а не row→lock.
        # Старый control нарушает эту инварианту детерминированно, без sleep.
        assert sim._lock.owner is asyncio.current_task()
        return await set_status(*args, **kwargs)

    monkeypatch.setattr(sim, "_stop_loop", stop)
    monkeypatch.setattr(run_svc, "set_run_status", set_status_owned)

    async def worker():
        async with sim._lock:
            worker_locked.set()
            await stopped.wait()
            async with await psycopg.AsyncConnection.connect(dsn(seeded)) as other:
                await other.execute("update sim_runs set notes='synthetic worker committed' where id=%s", (rid,))
                await other.commit()

    task = asyncio.create_task(worker())
    try:
        await worker_locked.wait()
        await asyncio.wait_for(asyncio.gather(task, sim.control(action)), timeout=5)
        row = await (
            await conn.execute("select status,notes,finished_sim from sim_runs where id=%s", (rid,))
        ).fetchone()
        assert row[:2] == (target, "synthetic worker committed")
        assert row[2] == (now if action == "stop" else None)
        assert sim.clock.sim_time == now and sim.rng.dump_state() == rng
        assert sim.clock.running is False
        assert (await (await conn.execute("select running from sim_state where id=1")).fetchone())[0] is False
        config = await configuration(conn, rid)
        assert config["status"] == target and config["enabled"] == (action == "pause")
    finally:
        task.cancel()
        await asyncio.gather(task, return_exceptions=True)
        await sim.shutdown()


@pytest.mark.parametrize("action", ["pause", "stop"])
@pytest.mark.parametrize("cancel", [False, True])
async def test_halt_failure_rolls_back_status_metadata_and_finished_time(seeded, monkeypatch, action, cancel):
    from unittest.mock import AsyncMock

    from app.demo.settings import save

    sim = Simulator(dsn=seeded)
    await sim.load_state()
    await sim.control("start", label="synthetic halt rollback", start_paused=True)
    conn = await sim.connect()
    await save(conn, sim.run_id, {"mode": "full", "enabled": True, "status": "running"})
    await conn.execute("update sim_runs set status='running' where id=%s", (sim.run_id,))
    await conn.commit()
    sim.run_status, sim.clock.running = "running", True
    before = (await (await conn.execute("select to_jsonb(r) from sim_runs r where id=%s", (sim.run_id,))).fetchone())[0]
    await conn.commit()
    persist = sim.persist
    error = asyncio.CancelledError if cancel else RuntimeError
    try:
        monkeypatch.setattr(sim, "persist", AsyncMock(side_effect=error("synthetic persistence failure")))
        with pytest.raises(error):
            await sim.control(action)
        assert sim.run_status == "running" and sim.clock.running is False
        after = (
            await (await conn.execute("select to_jsonb(r) from sim_runs r where id=%s", (sim.run_id,))).fetchone()
        )[0]
        assert after == before
    finally:
        monkeypatch.setattr(sim, "persist", persist)
        await sim.shutdown()
