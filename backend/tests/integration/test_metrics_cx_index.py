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


@pytest.mark.asyncio
async def test_delayed_native_receipt_prevents_future_classification_leak(cx_db, sql, monkeypatch, metrics_client):
    """Frozen ctx T0 не доказывает publication: native observation появляется в T5."""
    import asyncio
    from dataclasses import replace

    from app.agent.graph import load_deps
    from app.contracts.registry import deref, validate
    from app.economics.calibration import PIPELINE
    from app.llm.mock import MockProvider
    from app.sim.behavior.signals import record_classified
    from tests.helpers import MOCK_PROFILE, dsn, mock_chain
    from tests.integration.test_behavior_effect_time import load_sim
    from tests.integration.test_behavior_inactive import case

    saved = sql.execute(
        "SELECT sim_time,current_run_id,seed,rng_state,running,day_no FROM sim_state WHERE id=1"
    ).fetchone()
    entered, release = asyncio.Event(), asyncio.Event()

    class Delayed(MockProvider):
        async def complete_structured(self, *args, **kwargs):
            entered.set()
            await release.wait()
            result, usage, meta = await super().complete_structured(*args, **kwargs)
            result["sentiment"] = "negative"
            return result, usage, meta

    run = None
    try:
        async with await psycopg.AsyncConnection.connect(dsn(cx_db)) as conn:
            run, client, t0, signal, agent = await case(conn, monkeypatch, cx_db)
            deps = await load_deps(
                conn, chain=mock_chain(), profile=MOCK_PROFILE, run_id=run, agent_run_id=agent, sim_time=t0
            )
            await conn.commit()
            sim = await load_sim(cx_db)
            pending = asyncio.create_task(
                Delayed().complete_structured(
                    [{"role": "user", "content": "Сотрудник грубо накричал, обслуживанием недоволен"}],
                    deref("agent/classification"),
                    MOCK_PROFILE,
                    timeout_s=1,
                )
            )
            try:
                await asyncio.wait_for(entered.wait(), timeout=2)
                await sim.step(3)
                t3 = sim.clock.sim_time
                await sim.step(2)
                t5 = sim.clock.sim_time
                release.set()
                value, _, _ = await asyncio.wait_for(pending, timeout=2)
                assert not validate(value, "agent/classification")
                await conn.execute("UPDATE signals SET classification=%s WHERE id=%s", (Jsonb(value), signal))
                await deps.record_step(
                    "classify", "ok", {}, value | {"score_pipeline": PIPELINE, "churn_predicted_sim": t0.isoformat()}
                )
                await record_classified(deps.ctx, signal)
                observed = (
                    await (
                        await conn.execute("SELECT observed_sim FROM behavior_agent_intents WHERE run_id=%s", (run,))
                    ).fetchone()
                )[0]
                assert observed == t5 and t0 < t3 < t5
                await conn.commit()
            finally:
                release.set()
                await asyncio.gather(pending, return_exceptions=True)
                await sim.conn.close()

        # Контрпример unsafe proposal: frozen producer stamp уже <= T3, но receipt ещё в будущем.
        unsafe_known = sql.execute(
            "SELECT count(*) FROM agent_steps WHERE run_id=%s AND (output->>'churn_predicted_sim')::timestamptz<=%s",
            (agent, t3),
        ).fetchone()[0]
        assert unsafe_known == 1

        async def at(cutoff):
            async with await psycopg.AsyncConnection.connect(dsn(cx_db), row_factory=dict_row) as reader:
                await reader.execute("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ, READ ONLY")
                scope = replace(await metrics_scope(reader, str(run)), now=cutoff)
                return await signal_facts(reader, scope, historical=True)

        before = fingerprint(sql)
        old, published = await at(t3), await at(t5)
        assert old["signals"] == published["signals"] == 1
        assert all(c.known == 0 and c.complete_value is None for c in old["components"].values())
        assert published["components"]["negativity"].complete_value == value["negativity"]
        assert published["components"]["criticality"].known == published["components"]["churn"].known == 1
        assert fingerprint(sql) == before

        # Уже записанное native observed T5 не совместимо с регрессировавшим global T3.
        # Это отдельная defensive проверка, а не публикационный receipt для positive.
        sql.execute("UPDATE sim_state SET sim_time=%s WHERE id=1", (t3,))
        try:
            before = fingerprint(sql)
            for endpoint in ("cx-index", "overview"):
                for requested in (str(run), "current", "all"):
                    response = metrics_client.get("/api/metrics/" + endpoint, params={"run_id": requested})
                    assert response.status_code == 409, response.text[:300]
                    assert response.json()["title"] == "temporal_context_conflict"
            assert fingerprint(sql) == before
        finally:
            sql.execute("UPDATE sim_state SET sim_time=%s WHERE id=1", (t5,))

        # Два canonical snapshots не позволяют угадать, какой был опубликован receipt.
        sql.execute(
            "INSERT INTO agent_steps(run_id,seq,node,status,input,output) SELECT run_id,2,node,status,input,output FROM agent_steps WHERE run_id=%s",
            (agent,),
        )
        ambiguous = await at(t5)
        assert all(c.known == 0 for c in ambiguous["components"].values())
        sql.execute("DELETE FROM agent_steps WHERE run_id=%s AND seq=2", (agent,))

        # Отсутствующий snapshot и запись другого run не дают historical provenance.
        sql.execute("UPDATE agent_steps SET status='error' WHERE run_id=%s", (agent,))
        assert all(c.known == 0 for c in (await at(t5))["components"].values())
        sql.execute("UPDATE agent_steps SET status='ok' WHERE run_id=%s", (agent,))
        other = sql.execute(
            "INSERT INTO sim_runs(kind,label,seed,started_sim) VALUES('free','T256 foreign receipt',42,%s) RETURNING id",
            (t0,),
        ).fetchone()[0]
        try:
            sql.execute("UPDATE behavior_agent_intents SET run_id=%s WHERE run_id=%s", (other, run))
            assert all(c.known == 0 for c in (await at(t5))["components"].values())
            sql.execute("UPDATE behavior_agent_intents SET run_id=%s WHERE run_id=%s", (run, other))
        finally:
            sql.execute("DELETE FROM sim_runs WHERE id=%s", (other,))

        # Два независимых matching receipts в одну дату — ambiguous, не last-row-wins.
        second = sql.execute(
            "INSERT INTO agent_runs(kind,sim_run_id,signal_id,client_id,started_sim,prompt_version) VALUES('agent',%s,%s,%s,%s,'T256 duplicate') RETURNING id",
            (run, signal, client, t0),
        ).fetchone()[0]
        sql.execute(
            "INSERT INTO agent_steps(run_id,seq,node,status,input,output) SELECT %s,1,node,status,input,output FROM agent_steps WHERE run_id=%s",
            (second, agent),
        )
        sql.execute(
            "INSERT INTO behavior_agent_intents(run_id,agent_run_id,client_id,signal_id,incident_id,requested_state,trigger,observed_sim) SELECT run_id,%s,client_id,signal_id,incident_id,requested_state,trigger,observed_sim FROM behavior_agent_intents WHERE run_id=%s",
            (second, run),
        )
        assert all(c.known == 0 for c in (await at(t5))["components"].values())
    finally:
        sql.execute(
            "UPDATE sim_state SET sim_time=%s,current_run_id=%s,seed=%s,rng_state=%s,running=%s,day_no=%s WHERE id=1",
            (*saved[:3], Jsonb(saved[3]), *saved[4:]),
        )
        if run is not None:
            sql.execute("DELETE FROM sim_runs WHERE id=%s", (run,))


@pytest.mark.asyncio
async def test_snapshot_uses_current_weights_and_refuses_unobserved_previous(cx_db, sql, owned_run):
    from app.analytics.cx_index_reader import cx_index_snapshot

    run, now = owned_run
    await put(cx_db, run, now - dt.timedelta(hours=2), classification(50))
    old = sql.execute("SELECT value FROM settings WHERE key='cx_index'").fetchone()
    try:
        sql.execute("DELETE FROM settings WHERE key='cx_index'")

        async def snapshot():
            async with await psycopg.AsyncConnection.connect(
                cx_db.replace("postgresql+psycopg:", "postgresql:"), row_factory=dict_row
            ) as conn:
                await conn.execute("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ, READ ONLY")
                return await cx_index_snapshot(conn, await metrics_scope(conn, str(run)))

        out = await snapshot()
        assert out["index"] == 80
        assert out["previous_index"] is None and out["delta_hour"] is None
        assert out["previous_components"]["negativity"]["known"] == 0
        assert out["previous_components"]["sla"]["value"] == 0
        assert out["scope"]["resolved_run_id"] == run
        assert out["weights_source"] == "tz_default"
        sql.execute(
            "INSERT INTO settings(key,value) VALUES('cx_index',%s)",
            (Jsonb({"weights": {"negativity": 1, "criticality": 0, "sla": 0, "churn": 0}}),),
        )
        out = await snapshot()
        assert out["index"] == 50 and out["weights_source"] == "configured"
        assert out["comparison_basis"] == "current_weights_on_observed_states"
    finally:
        sql.execute("DELETE FROM settings WHERE key='cx_index'")
        if old:
            sql.execute("INSERT INTO settings(key,value) VALUES('cx_index',%s)", (Jsonb(old[0]),))


@pytest.mark.asyncio
async def test_historical_open_sla_is_unknown_without_native_deadline_snapshot(cx_db, native_sla_case):
    from dataclasses import replace

    from app.analytics.cx_index_reader import historical_sla_facts

    async with await psycopg.AsyncConnection.connect(
        cx_db.replace("postgresql+psycopg:", "postgresql:"), row_factory=dict_row
    ) as conn:
        await conn.execute("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ, READ ONLY")
        scope = replace(await metrics_scope(conn, str(native_sla_case["run"])), now=native_sla_case["now"])
        out = await historical_sla_facts(conn, scope)
        assert out["open_incidents"] == 1
        assert out["component"].complete_value is None
        assert out["reason"] == "historical_sla_evidence_unavailable"


@pytest.fixture
def metrics_client(cx_db):
    from fastapi.testclient import TestClient

    from app.main import create_app

    with TestClient(create_app()) as client:
        yield client


def test_actual_http_shapes_scopes_and_readonly(metrics_client, sql, owned_run, monkeypatch):
    from tests.integration.test_cabinet_api import assert_schema

    run, _ = owned_run

    def bomb(*args, **kwargs):
        raise AssertionError("Metrics GET must not call LLM/money producer")

    monkeypatch.setattr("app.economics.dcltv.compute_incident", bomb)
    monkeypatch.setattr("app.economics.dcltv.recompute", bomb)
    monkeypatch.setattr("app.llm.failover.ProviderChain.complete_structured", bomb)
    before = fingerprint(sql)
    for path, schema in [("cx-index", "CxIndex"), ("overview", "MetricsOverview")]:
        response = metrics_client.get("/api/metrics/" + path, params={"run_id": str(run)})
        assert response.status_code == 200, response.text[:300]
        value = response.json()
        assert_schema(value, schema)
        assert value["scope"]["resolved_run_id"] == run
        if path == "overview":
            assert value["kpi"]["saved_rub_exact"] == "0"
            assert value["kpi"]["autonomous_share"] is None
            assert value["shift"]["items"] == []
        assert metrics_client.get("/api/metrics/" + path, params={"run_id": "9223372036854775807"}).status_code == 404
    assert fingerprint(sql) == before


@pytest.mark.parametrize("run", ["", "²", "١", "0", "-1", "9223372036854775808", "1" * 200])
@pytest.mark.asyncio
async def test_invalid_http_scope_rejected_before_connection(monkeypatch, run):
    from fastapi import HTTPException

    from app.api.metrics import get_metrics_cx_index, get_metrics_overview

    def bomb():
        raise AssertionError("Invalid run must not access DB")

    monkeypatch.setattr("app.trace.store.read_db", bomb)
    for reader in (get_metrics_cx_index, get_metrics_overview):
        with pytest.raises(HTTPException) as error:
            await reader(run)
        assert error.value.status_code == 422


@pytest.mark.asyncio
async def test_overview_recorded_runs_summary_modes_and_partial_criticality(cx_db, sql, owned_run):
    from app.analytics.overview import overview_snapshot

    run, now = owned_run
    signal = await put(cx_db, run, now, classification(50, "high"))
    await put(cx_db, run, now, None)
    for seq in range(10):
        agent = sql.execute(
            "INSERT INTO agent_runs(kind,sim_run_id,signal_id,prompt_version,started_sim,outcome,finished_at,total_latency_ms,needed_human) VALUES('agent',%s,%s,'T256 recorded',%s,'completed',now(),%s,%s) RETURNING id",
            (run, signal, now, 100 + seq * 10, bool(seq % 2)),
        ).fetchone()[0]
        sql.execute(
            "INSERT INTO agent_steps(run_id,seq,node,status,input,output,model,finished_at) VALUES(%s,1,'classify','ok','{}',%s,%s,now())",
            (
                agent,
                Jsonb({"summary_ru": "Учебная сводка: contact@example.test, +7 999 123-45-67"}),
                "mock:mock-rules-v1" if seq != 9 else None,
            ),
        )
    before = fingerprint(sql)
    async with await psycopg.AsyncConnection.connect(
        cx_db.replace("postgresql+psycopg:", "postgresql:"), row_factory=dict_row
    ) as conn:
        await conn.execute("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ, READ ONLY")
        out = await overview_snapshot(conn, await metrics_scope(conn, str(run)))
    assert out["kpi"]["signals_today"] == 2
    assert out["kpi"]["critical_today"] is None
    assert out["coverage"]["criticality_known_today"] == 1
    assert out["kpi"]["autonomous_share"] == 50
    assert out["kpi"]["agent_response_p50_ms"] == 145
    assert out["shift"]["total"] == 10 and out["shift"]["truncated"] is True
    assert len(out["shift"]["items"]) == 8
    assert out["shift"]["items"][0]["mode"] == "unknown"
    assert out["shift"]["items"][1]["mode"] == "mock"
    assert all(
        "contact@example.test" not in item["text"] and "999 123" not in item["text"] for item in out["shift"]["items"]
    )
    assert fingerprint(sql) == before


@pytest.mark.asyncio
async def test_http_current_default_weights_patch_and_unknown_config(metrics_client, cx_db, sql, owned_run):
    run, now = owned_run
    await put(cx_db, run, now, classification(50))
    pointer = sql.execute("SELECT current_run_id FROM sim_state WHERE id=1").fetchone()[0]
    old = sql.execute("SELECT value FROM settings WHERE key='cx_index'").fetchone()
    try:
        sql.execute("UPDATE sim_state SET current_run_id=%s WHERE id=1", (run,))
        body = {"cx_index": {"weights": {"negativity": 1, "criticality": 0, "sla": 0, "churn": 0}}}
        assert metrics_client.patch("/api/settings", json=body).status_code == 200
        actual = metrics_client.get("/api/metrics/cx-index").json()
        assert actual["signals"] == 1 and actual["index"] == 50
        assert actual["scope"]["requested_run_id"] == "current"
        assert actual["weights"] == body["cx_index"]["weights"]
        assert metrics_client.get("/api/settings").json()["cx_index"]["weights"] == actual["weights"]
        before = fingerprint(sql)
        assert (
            metrics_client.patch("/api/settings", json={"cx_index": {"weights": {"negativity": 1}}}).status_code == 422
        )
        assert fingerprint(sql) == before
        sql.execute("UPDATE settings SET value='null'::jsonb WHERE key='cx_index'")
        unknown = metrics_client.get("/api/metrics/cx-index").json()
        assert unknown["weights_source"] == "invalid" and unknown["weights"] is None and unknown["index"] is None
        sql.execute("UPDATE sim_state SET current_run_id=NULL WHERE id=1")
        for path in ("cx-index", "overview"):
            empty = metrics_client.get("/api/metrics/" + path).json()
            assert empty["scope"]["current_missing"] and empty["scope"]["resolved_run_id"] is None
            assert empty["signals" if path == "cx-index" else "signals_24h"] == 0
    finally:
        sql.execute("UPDATE sim_state SET current_run_id=%s WHERE id=1", (pointer,))
        sql.execute("DELETE FROM settings WHERE key='cx_index'")
        if old:
            sql.execute("INSERT INTO settings(key,value) VALUES('cx_index',%s)", (Jsonb(old[0]),))


def test_overview_exact_stored_money_partial_and_foreign_scope(metrics_client, sql, owned_run, monkeypatch):
    from decimal import Decimal

    run, now = owned_run
    incidents = sql.execute(
        "INSERT INTO incidents(run_id,title,incident_type,team_code,complexity,criticality,priority,status,created_by,created_sim,sla_due_sim,take_due_sim) SELECT %s,'T256 stored money fixture','service_quality','team_debit','easy','low',4,'closed','scenario',%s,%s,%s FROM generate_series(1,11) RETURNING id",
        (run, now, now, now),
    ).fetchall()
    sql.execute(
        "INSERT INTO incident_economics(incident_id,run_id,affected_count,rate_code,rate_rub,detractor_share,no_return_share,potential_loss_rub,prevented_loss_rub,computed_sim) SELECT id,run_id,1,'bank_average',4050,.15,.2,999999999999.99,999999999999.97,%s FROM incidents WHERE run_id=%s",
        (now, run),
    )
    expected = sql.execute("SELECT sum(prevented_loss_rub) FROM incident_economics WHERE run_id=%s", (run,)).fetchone()[
        0
    ]
    assert expected == Decimal("10999999999999.67") and Decimal(float(expected)) != expected

    def bomb(*args, **kwargs):
        raise AssertionError("No monetary computation allowed in reader")

    monkeypatch.setattr("app.economics.dcltv.compute", bomb)
    monkeypatch.setattr("app.economics.dcltv.compute_incident", bomb)
    monkeypatch.setattr("app.economics.dcltv.recompute", bomb)
    before = fingerprint(sql)
    out = metrics_client.get("/api/metrics/overview", params={"run_id": str(run)}).json()
    assert out["kpi"]["saved_rub_exact"] == str(expected)
    assert out["coverage"]["incidents"] == out["coverage"]["economics_known"] == 11
    assert sum(x["incidents"] for x in out["pressure"]) == 11
    assert fingerprint(sql) == before
    sql.execute("DELETE FROM incident_economics WHERE incident_id=%s", (incidents[0][0],))
    partial = metrics_client.get("/api/metrics/overview", params={"run_id": str(run)}).json()
    assert partial["kpi"]["saved_rub_exact"] is None
    assert partial["coverage"]["incidents"] == 11 and partial["coverage"]["economics_known"] == 10


@pytest.mark.parametrize("future_field", ["started_sim", "finished_sim"])
def test_temporal_metadata_conflict_precedes_both_live_projections(
    metrics_client, sql, owned_run, monkeypatch, future_field
):
    """Old/all fail closed; coherent current и отсутствие pointer не расширяют scope."""
    from psycopg import sql as sql_builder

    run, now = owned_run
    saved_pointer = sql.execute("SELECT current_run_id FROM sim_state WHERE id=1").fetchone()[0]
    other = sql.execute(
        "INSERT INTO sim_runs(kind,label,seed,started_sim) VALUES('free','T256 coherent current',42,%s) RETURNING id",
        (now,),
    ).fetchone()[0]
    try:
        sql.execute(
            sql_builder.SQL("UPDATE sim_runs SET {}=%s WHERE id=%s").format(sql_builder.Identifier(future_field)),
            (now + dt.timedelta(minutes=2), run),
        )
        sql.execute("UPDATE sim_state SET current_run_id=%s WHERE id=1", (run,))

        async def bomb(*args, **kwargs):
            raise AssertionError("Temporal conflict must precede either live projection")

        with monkeypatch.context() as patch:
            patch.setattr("app.analytics.cx_index_reader.cx_index_snapshot", bomb)
            patch.setattr("app.analytics.overview.overview_snapshot", bomb)
            for endpoint in ("cx-index", "overview"):
                for requested in (str(run), "current", "all"):
                    before = fingerprint(sql)
                    response = metrics_client.get("/api/metrics/" + endpoint, params={"run_id": requested})
                    assert response.status_code == 409, response.text[:300]
                    assert response.json()["title"] == "temporal_context_conflict"
                    assert fingerprint(sql) == before
        sql.execute("UPDATE sim_state SET current_run_id=%s WHERE id=1", (other,))
        before = fingerprint(sql)
        for endpoint in ("cx-index", "overview"):
            coherent = metrics_client.get("/api/metrics/" + endpoint).json()
            assert coherent["scope"]["resolved_run_id"] == other
        assert fingerprint(sql) == before
        sql.execute("UPDATE sim_state SET current_run_id=NULL WHERE id=1")
        for endpoint in ("cx-index", "overview"):
            response = metrics_client.get("/api/metrics/" + endpoint)
            assert response.status_code == 200
            assert response.json()["scope"]["current_missing"] is True
        # Метаданные в тот же as_of допустимы; глобальную политику часов не меняем.
        sql.execute(
            sql_builder.SQL("UPDATE sim_runs SET {}=%s WHERE id=%s").format(sql_builder.Identifier(future_field)),
            (now, run),
        )
        for endpoint in ("cx-index", "overview"):
            assert metrics_client.get("/api/metrics/" + endpoint, params={"run_id": str(run)}).status_code == 200
    finally:
        sql.execute("UPDATE sim_state SET current_run_id=%s WHERE id=1", (saved_pointer,))
        sql.execute("DELETE FROM sim_runs WHERE id=%s", (other,))
