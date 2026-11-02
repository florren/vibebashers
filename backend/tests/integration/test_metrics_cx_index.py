"""T-256: native customer facts, current-only scope и отсутствие writes."""

from __future__ import annotations

import datetime as dt
from collections.abc import Iterator

import psycopg
import pytest
from psycopg.rows import dict_row
from psycopg.types.json import Jsonb

from app.analytics.cx_index_reader import metrics_scope, signal_facts
from app.ingest.normalizer import create_signal, from_api_signal
from tests.integration.conftest import _seed, rebuild_schema
from tests.integration.test_cabinet_api import fingerprint


@pytest.fixture(scope="module")
def cx_db(migrated_db: str) -> str:
    rebuild_schema(migrated_db)
    seeded = _seed(migrated_db, "--profile", "lite", "--clients", "200")
    assert seeded.returncode == 0, seeded.stderr[-1000:]
    return migrated_db


@pytest.fixture
def sql(cx_db: str) -> Iterator[psycopg.Connection]:
    with psycopg.connect(cx_db.replace("postgresql+psycopg:", "postgresql:"), autocommit=True) as conn:
        yield conn


@pytest.fixture
def owned_run(sql):
    now = sql.execute("SELECT sim_time FROM sim_state WHERE id=1").fetchone()[0]
    run = sql.execute(
        "INSERT INTO sim_runs(kind,label,seed,started_sim) VALUES('free','T256 readonly fixture',42,%s) RETURNING id",
        (now,),
    ).fetchone()[0]
    try:
        yield run, now
    finally:
        sql.execute("DELETE FROM sim_runs WHERE id=%s", (run,))


def classification(negativity=50, criticality="low", flags=None):
    return {
        "negativity": negativity,
        "criticality": criticality,
        "signal_type": "service_quality",
        "flags": flags or [],
    }


async def put(url, run, at, value, *, origin="api"):
    async with await psycopg.AsyncConnection.connect(url.replace("postgresql+psycopg:", "postgresql:")) as conn:
        message = from_api_signal(
            {"channel_code": "chat", "text": "Учебный сигнал для проверки индекса CX"}, origin=origin
        )
        result = await create_signal(conn, message, source_code="api", emit_event=False, run_id=run, sim_time=at)
        if value is not None:
            await conn.execute("UPDATE signals SET classification=%s WHERE id=%s", (Jsonb(value), result["signal_id"]))
        return result["signal_id"]


async def read(url, requested):
    async with await psycopg.AsyncConnection.connect(
        url.replace("postgresql+psycopg:", "postgresql:"), row_factory=dict_row
    ) as conn:
        await conn.execute("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ, READ ONLY")
        scope = await metrics_scope(conn, requested)
        return scope, await signal_facts(conn, scope)


@pytest.mark.asyncio
async def test_manual_components_and_exact_window_hour_boundaries(cx_db, sql, owned_run, monkeypatch):
    run, now = owned_run
    await put(
        cx_db, run, now - dt.timedelta(hours=2) + dt.timedelta(minutes=1), classification(80, "high", ["churn_intent"])
    )
    await put(cx_db, run, now - dt.timedelta(hours=1), classification(20, "low"))
    await put(cx_db, run, now, classification(50, "medium"))
    await put(cx_db, run, now + dt.timedelta(seconds=1), classification(0))
    await put(cx_db, run, now - dt.timedelta(hours=24), classification(0))
    await put(cx_db, run, now, classification(0), origin="proactive")

    async def bomb(*args, **kwargs):
        raise AssertionError("CX reader must not invoke LLM or monetary producers")

    monkeypatch.setattr("app.economics.dcltv.compute_incident", bomb)
    monkeypatch.setattr("app.economics.dcltv.recompute", bomb)
    monkeypatch.setattr("app.llm.failover.ProviderChain.complete_structured", bomb)
    before = fingerprint(sql)
    scope, facts = await read(cx_db, str(run))
    assert facts["signals"] == 3
    assert scope.since == now - dt.timedelta(hours=24)
    assert facts["components"]["negativity"].complete_value == 50
    assert facts["components"]["criticality"].complete_value == pytest.approx(100 / 3)
    assert facts["components"]["churn"].complete_value == pytest.approx(100 / 3)
    assert all(c.known == c.total == 3 for c in facts["components"].values())
    assert facts["channel_mix"] == [{"channel_code": "chat", "signals": 3}]
    assert len(facts["flow"]) == 24
    assert sum(b["signals"] for b in facts["flow"]) == 3
    assert facts["flow"][22]["signals"] == 2
    assert facts["flow"][23]["signals"] == 1
    assert fingerprint(sql) == before


@pytest.mark.asyncio
async def test_default_flags_and_malformed_classification_are_unknown(cx_db, owned_run):
    run, now = owned_run
    await put(cx_db, run, now, None)
    await put(cx_db, run, now, {**classification(True), "flags": "[]"})
    await put(cx_db, run, now, classification(30, flags=["unregistered_legacy_flag"]))
    _, facts = await read(cx_db, str(run))
    assert facts["signals"] == 3
    assert facts["components"]["negativity"].known == 1
    assert facts["components"]["negativity"].value == 30
    assert facts["components"]["negativity"].complete_value is None
    assert facts["components"]["criticality"].known == 2
    assert facts["components"]["churn"].known == 0
    assert facts["components"]["churn"].value is None


@pytest.mark.asyncio
async def test_current_is_not_baseline_or_all_and_missing_pointer_is_empty(cx_db, sql, owned_run):
    run, now = owned_run
    await put(cx_db, run, now, classification(80))
    pointer = sql.execute("SELECT current_run_id FROM sim_state WHERE id=1").fetchone()[0]
    try:
        sql.execute("UPDATE sim_state SET current_run_id=%s WHERE id=1", (run,))
        current, facts = await read(cx_db, "current")
        assert current.run_id == run
        assert facts["signals"] == 1
        _, all_facts = await read(cx_db, "all")
        assert all_facts["signals"] > 1
        sql.execute("UPDATE sim_state SET current_run_id=NULL WHERE id=1")
        missing, empty = await read(cx_db, "current")
        assert missing.current_missing and missing.run_id == -1
        assert empty["signals"] == 0 and len(empty["flow"]) == 24
        assert sum(b["signals"] for b in empty["flow"]) == 0
        assert all(c.complete_value is None for c in empty["components"].values())
    finally:
        sql.execute("UPDATE sim_state SET current_run_id=%s WHERE id=1", (pointer,))


@pytest.fixture(scope="module")
def cabinet_db(cx_db):
    # Existing native SlaEngine fixture получает ту же БД без повторного rebuild.
    return cx_db


from tests.integration.test_cabinet_report import native_sla_case as native_sla_case  # noqa: E402


@pytest.mark.parametrize(
    "state",
    [
        "current",
        "foreign",
        "closed",
        "reopened",
        "release",
        "same_clock",
        "changed_deadline",
        "missing_stage",
        "overdue",
    ],
)
def test_native_registered_sla_scope_lifecycle_and_unknown(cx_db, sql, native_sla_case, state, monkeypatch):
    import asyncio

    from app.agent.tools.base import ToolContext
    from app.agent.tools.write import update_incident
    from app.analytics.cx_index_reader import sla_facts
    from app.sim.events import EventBus

    case = native_sla_case

    async def transition():
        async with await psycopg.AsyncConnection.connect(cx_db.replace("postgresql+psycopg:", "postgresql:")) as conn:
            ctx = ToolContext(
                conn,
                run_id=case["run"],
                agent_run_id=case["agent"],
                sim_time=case["now"] + dt.timedelta(minutes=1),
                llm_source="mock",
            )
            if state in ("closed", "reopened"):
                await update_incident(ctx, case["incident"], "resolved", "T256: завершение fixture стадии")
                ctx.sim_time += dt.timedelta(minutes=1)
                await update_incident(
                    ctx,
                    case["incident"],
                    "closed" if state == "closed" else "in_progress",
                    "T256: следующая fixture стадия",
                )
            elif state == "same_clock":
                ctx.sim_time = case["now"]
                await update_incident(ctx, case["incident"], "fix_proposed", "T256: fixture стадия")
                await update_incident(ctx, case["incident"], "in_progress", "T256: fixture возврат")
            elif state == "foreign":
                await EventBus(conn).emit(case["foreign"], "sla.warning", case["payload"], ctx.sim_time)

    asyncio.run(transition())
    if state == "release":
        sql.execute(
            "INSERT INTO team_actions(run_id,incident_id,team_code,action,action_sim) VALUES(%s,%s,'team_deposits','release',%s)",
            (case["run"], case["incident"], case["now"] + dt.timedelta(minutes=1)),
        )
    if state == "changed_deadline":
        sql.execute("UPDATE incidents SET sla_due_sim=sla_due_sim+interval '1 hour' WHERE id=%s", (case["incident"],))
    if state == "missing_stage":
        sql.execute("DELETE FROM incident_status_history WHERE incident_id=%s", (case["incident"],))
    if state == "overdue":
        sql.execute(
            "UPDATE incidents SET sla_due_sim=%s WHERE id=%s", (case["now"] - dt.timedelta(seconds=1), case["incident"])
        )
    sql.execute("UPDATE sim_state SET sim_time=%s WHERE id=1", (case["now"] + dt.timedelta(minutes=3),))

    async def bomb(*args, **kwargs):
        raise AssertionError("SLA reader must not invoke monetary writers or LLM")

    monkeypatch.setattr("app.economics.dcltv.compute_incident", bomb)
    monkeypatch.setattr("app.llm.failover.ProviderChain.complete_structured", bomb)

    async def observed():
        async with await psycopg.AsyncConnection.connect(
            cx_db.replace("postgresql+psycopg:", "postgresql:"), row_factory=dict_row
        ) as conn:
            await conn.execute("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ, READ ONLY")
            return await sla_facts(conn, await metrics_scope(conn, str(case["run"])))

    before = fingerprint(sql)
    facts = asyncio.run(observed())
    assert facts["basis"] == "registered_sla_risk" and facts["forecast_complete"] is False
    component = facts["component"]
    if state == "closed":
        assert facts["registered_count"] == 0 and component.value == 0 and component.known == component.total == 0
    elif state in ("current", "foreign", "overdue"):
        assert (
            facts["registered_count"] == 1
            and component.complete_value == 100
            and component.known == component.total == 1
        )
    else:
        assert (
            facts["registered_count"] == 0
            and component.complete_value is None
            and component.known == 0
            and component.total == 1
        )
    assert before == fingerprint(sql)
