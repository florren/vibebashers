"""Регрессии ошибок, обнаруженных живым прогоном двадцати входов."""

import asyncio

import psycopg
import pytest
from starlette.requests import Request

from app.agent.runner import AgentService
from app.api.demo_execution import DemoExecutionBody, post_demo_execution
from app.config import get_settings
from app.demo.execution import configuration, cycle
from app.llm.failover import ProviderChain
from app.llm.mock import MockProvider
from app.main import create_app
from app.sim.engine import Simulator
from tests.helpers import MOCK_PROFILE, dsn

pytestmark = pytest.mark.integration


@pytest.mark.parametrize("code", ["ATM-DEPOSIT-HANG", "APP-CRASH-PAY"])
async def test_unknown_model_error_code_does_not_break_incident(seeded, monkeypatch, code):
    class InventedCode(MockProvider):
        async def complete_structured(self, messages, schema, profile, *, timeout_s):
            obj, usage, raw = await super().complete_structured(messages, schema, profile, timeout_s=timeout_s)
            if "cause_hypothesis" in obj:
                obj.update(error_code=code, signal_type="tech_fault", confidence=1.0)
            return obj, usage, raw

    monkeypatch.setenv("DATABASE_URL", seeded)
    get_settings.cache_clear()
    app = create_app()
    svc = app.state.agent = AgentService(ProviderChain([InventedCode()]), MOCK_PROFILE, dsn=seeded)
    sim = app.state.sim = Simulator(dsn=seeded)
    await sim.load_state()
    app.state.llm_chain, app.state.llm_profile = svc.chain, svc.profile
    try:
        request = Request({"type": "http", "app": app, "headers": []})
        state = await post_demo_execution(request, DemoExecutionBody(scenario_id="demo20_03_atm_cash"))
        for _ in range(40):
            if svc._inflight:
                await asyncio.gather(*list(svc._inflight))
            await cycle(app)
        async with await psycopg.AsyncConnection.connect(dsn(seeded)) as conn:
            config = await configuration(conn, state["run_id"])
            assert config["status"] == "finished"
            row = await (
                await conn.execute("select error_code,status from incidents where run_id=%s", (state["run_id"],))
            ).fetchone()
            assert row == (None if code == "ATM-DEPOSIT-HANG" else code, "closed")
            step = await (
                await conn.execute(
                    "select s.output from agent_steps s join agent_runs a on a.id=s.run_id where a.sim_run_id=%s and s.node='classify'",
                    (state["run_id"],),
                )
            ).fetchone()
            if code == "ATM-DEPOSIT-HANG":
                assert any("ATM-DEPOSIT-HANG" in note for note in step[0]["postcheck_notes"])
    finally:
        await svc.stop()
        await sim.shutdown()
        get_settings.cache_clear()


@pytest.mark.parametrize("failure", ["signal", "agent_run"])
async def test_failed_signal_is_not_a_finished_demo(seeded, monkeypatch, failure):
    monkeypatch.setenv("DATABASE_URL", seeded)
    get_settings.cache_clear()
    app = create_app()
    from tests.helpers import mock_chain

    svc = app.state.agent = AgentService(mock_chain(), MOCK_PROFILE, dsn=seeded)
    sim = app.state.sim = Simulator(dsn=seeded)
    await sim.load_state()
    app.state.llm_chain, app.state.llm_profile = svc.chain, svc.profile
    try:
        request = Request({"type": "http", "app": app, "headers": []})
        state = await post_demo_execution(request, DemoExecutionBody(scenario_id="demo20_01_branch_queue"))
        if svc._inflight:
            await asyncio.gather(*list(svc._inflight))
        async with await psycopg.AsyncConnection.connect(dsn(seeded)) as conn:
            if failure == "signal":
                await conn.execute("update signals set status='error' where run_id=%s", (state["run_id"],))
            else:
                await conn.execute(
                    "update agent_runs set outcome='failed' where sim_run_id=%s and kind='agent'", (state["run_id"],)
                )
        for _ in range(30):
            await cycle(app)
        async with await psycopg.AsyncConnection.connect(dsn(seeded)) as conn:
            config = await configuration(conn, state["run_id"])
            assert config["status"] == "error"
            assert config["error"] == "agent_processing_failed"
    finally:
        await svc.stop()
        await sim.shutdown()
        get_settings.cache_clear()


async def test_information_request_gets_team_result_only_in_explicit_demo(seeded, monkeypatch):
    from app.agent.graph import process_signal
    from app.sim import scenarios
    from tests.helpers import new_run, sim_now

    class Information(MockProvider):
        async def complete_structured(self, messages, schema, profile, *, timeout_s):
            obj, usage, raw = await super().complete_structured(messages, schema, profile, timeout_s=timeout_s)
            if "cause_hypothesis" in obj:
                obj.update(signal_type="info_request", criticality="low", confidence=1.0, flags=[], error_code=None)
            return obj, usage, raw

    monkeypatch.setenv("DATABASE_URL", seeded)
    get_settings.cache_clear()
    app = create_app()
    svc = app.state.agent = AgentService(ProviderChain([Information()]), MOCK_PROFILE, dsn=seeded)
    sim = app.state.sim = Simulator(dsn=seeded)
    await sim.load_state()
    app.state.llm_chain, app.state.llm_profile = svc.chain, svc.profile
    try:
        async with await psycopg.AsyncConnection.connect(dsn(seeded)) as conn:
            rid = await new_run(conn, "ordinary inquiry", scenario_id="demo20_15_refinancing")
            item = (
                await scenarios.inject(conn, scenarios.get("demo20_15_refinancing"), rid, sim_time=await sim_now(conn))
            )[0]
            await conn.commit()
            await process_signal(conn, signal_id=item["signal_id"], chain=svc.chain, profile=svc.profile)
            assert (await (await conn.execute("select count(*) from incidents where run_id=%s", (rid,))).fetchone())[
                0
            ] == 0
        state = await post_demo_execution(
            Request({"type": "http", "app": app, "headers": []}), DemoExecutionBody(scenario_id="demo20_15_refinancing")
        )
        for _ in range(30):
            if svc._inflight:
                await asyncio.gather(*list(svc._inflight))
            await cycle(app)
        async with await psycopg.AsyncConnection.connect(dsn(seeded)) as conn:
            assert (
                await (
                    await conn.execute("select incident_type,status from incidents where run_id=%s", (state["run_id"],))
                ).fetchone()
            ) == ("info_request", "closed")
            assert (
                await (
                    await conn.execute(
                        "select count(*) from notifications where run_id=%s and template_code='resolved'",
                        (state["run_id"],),
                    )
                ).fetchone()
            )[0] == 1
    finally:
        await svc.stop()
        await sim.shutdown()
        get_settings.cache_clear()


async def test_counter_alert_uses_contract_policy_and_keeps_db_kind(seeded):
    from app.compliance.session import ComplianceService
    from app.contracts.registry import validate
    from app.sim.events import EventBus
    from tests.helpers import mock_chain, new_run, sim_now

    async with await psycopg.AsyncConnection.connect(dsn(seeded)) as conn:
        rid = await new_run(conn, "counter contract", scenario_id="branch_misselling")
        service = ComplianceService(
            conn, run_id=rid, sim_time=await sim_now(conn), chain=mock_chain(), profile=MOCK_PROFILE, bus=EventBus(conn)
        )
        session = await service.create_session(branch_code=None)
        session.trigger_count = session.alert_threshold
        aid = await service.raise_alert(session, kind="threshold")
        assert aid
        assert (await (await conn.execute("select kind from compliance_alerts where id=%s", (aid,))).fetchone())[
            0
        ] == "threshold"
        payload = (
            await (
                await conn.execute(
                    "select payload from sim_events where run_id=%s and event_type='compliance.alert'", (rid,)
                )
            ).fetchone()
        )[0]
        assert payload["alert"]["kind"] == "counter"
        assert validate(payload, "compliance/session_event") == []


async def test_client_policy_fallback_does_not_keep_live_label(seeded, monkeypatch):
    from tests.helpers import mock_chain

    async def unsafe_reply(*args, **kwargs):
        return {"body": "Гарантируем результат сегодня же.", "decision": "accept"}, {
            "source": "live",
            "model": "live-test",
            "provider": "gigachat",
            "usage": {},
            "fallback": False,
            "grounded": True,
        }

    monkeypatch.setenv("DATABASE_URL", seeded)
    monkeypatch.setattr("app.demo.execution.respond", unsafe_reply)
    get_settings.cache_clear()
    app = create_app()
    svc = app.state.agent = AgentService(mock_chain(), MOCK_PROFILE, dsn=seeded)
    sim = app.state.sim = Simulator(dsn=seeded)
    await sim.load_state()
    app.state.llm_chain, app.state.llm_profile = svc.chain, svc.profile
    try:
        state = await post_demo_execution(
            Request({"type": "http", "app": app, "headers": []}),
            DemoExecutionBody(scenario_id="demo20_01_branch_queue"),
        )
        for _ in range(30):
            if svc._inflight:
                await asyncio.gather(*list(svc._inflight))
            await cycle(app)
        async with await psycopg.AsyncConnection.connect(dsn(seeded)) as conn:
            row = await (
                await conn.execute(
                    "select s.output from agent_steps s join agent_runs a on a.id=s.run_id where a.sim_run_id=%s and s.node='close' and s.output ? 'policy_fallback'",
                    (state["run_id"],),
                )
            ).fetchone()
            assert row[0]["source"] == "mock"
            assert row[0]["fallback"]
            body = (
                await (
                    await conn.execute(
                        "select body from notifications where run_id=%s and template_code='resolved'",
                        (state["run_id"],),
                    )
                ).fetchone()
            )[0]
            assert "Гарантируем" not in body
    finally:
        await svc.stop()
        await sim.shutdown()
        get_settings.cache_clear()
