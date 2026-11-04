"""T166 freeze: actual PG, независимые runs/часы/продукты и read-only экспорт."""

import asyncio
import datetime as dt
from io import BytesIO

import psycopg
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from openpyxl import load_workbook

from app.api.metrics import router
from app.economics import dcltv
from app.ingest.normalizer import create_signal, from_api_signal
from tests.helpers import dsn
from tests.integration.test_cabinet_api import assert_schema, fingerprint
from tests.integration.test_metrics_cx_index import cx_db as cx_db
from tests.integration.test_metrics_cx_index import sql as sql


@pytest.fixture
def client(cx_db, monkeypatch):
    monkeypatch.setenv("DATABASE_URL", cx_db)
    app = FastAPI()
    app.include_router(router)
    with TestClient(app) as client:
        yield client


@pytest.fixture
def cohort(sql, cx_db):
    old = sql.execute("select current_run_id,sim_time from sim_state where id=1").fetchone()
    at = old[1].replace(hour=9, minute=0, second=0, microsecond=0)
    runs = [
        sql.execute(
            "insert into sim_runs(kind,label,seed,started_sim) values('free',%s,42,%s) returning id",
            (f"T166 scope {i}", at),
        ).fetchone()[0]
        for i in range(2)
    ]
    base = sql.execute(
        "select code,system_code,product_code from error_codes where product_code is not null order by code limit 1"
    ).fetchone()
    product = sql.execute("select code from products where code<>%s order by code limit 1", (base[2],)).fetchone()[0]
    alternate = "TEST-FACT-PRODUCT"
    sql.execute(
        "insert into error_codes(code,system_code,product_code,title_ru,default_complexity,default_criticality) values(%s,%s,%s,'Учебная ошибка Fact','easy','low')",
        (alternate, base[1], product),
    )
    clients = [x[0] for x in sql.execute("select id from clients order by id limit 3")]
    incidents = []
    try:
        for run in runs:
            incidents.append(
                sql.execute(
                    "insert into incidents(run_id,title,incident_type,product_code,system_code,team_code,complexity,criticality,priority,created_by,created_sim,sla_due_sim,take_due_sim,status,outcome_class) values(%s,'Учебный Fact','tech_fault',%s,%s,'team_cx','easy','low',4,'scenario',%s,%s,%s,'closed','closed_in_sla') returning id",
                    (run, base[2], base[1], at, at, at),
                ).fetchone()[0]
            )
        for index, run in enumerate(runs):
            for client_id in clients[:1] if index == 0 else clients:
                sql.execute(
                    "insert into client_states(run_id,client_id,state,since_sim,trigger,incident_id) values(%s,%s,%s,%s,'timer',%s)",
                    (run, client_id, "retained" if index == 0 else "churned", at, incidents[index]),
                )
        faults = []
        for run, hour, code, count in [
            (runs[0], 9, base[0], 1),
            (runs[0], 10, base[0], 2),
            (runs[0], 9, alternate, 3),
            (runs[1], 9, base[0], 4),
        ]:
            when = at.replace(hour=hour)
            fault = sql.execute(
                "insert into faults(run_id,system_code,error_code,started_sim,impact_count,affected_clients) values(%s,%s,%s,%s,10,5) returning id",
                (run, base[1], code, when),
            ).fetchone()[0]
            faults.append((run, when, fault, count))

        async def signals():
            async with await psycopg.AsyncConnection.connect(dsn(cx_db)) as conn:
                for run, when, fault, count in faults:
                    for _ in range(count):
                        msg = from_api_signal({"channel_code": "chat", "text": "Учебный сигнал для Fact scope"})
                        result = await create_signal(
                            conn, msg, source_code="api", run_id=run, sim_time=when, emit_event=False
                        )
                        await conn.execute(
                            "update signals set source_fault_id=%s where id=%s", (fault, result["signal_id"])
                        )

        asyncio.run(signals())
        # Все собственные факты09/10 уже наступили; seed заканчивается в06UTC.
        sql.execute(
            "update sim_state set current_run_id=%s,sim_time=%s where id=1", (runs[0], at + dt.timedelta(hours=2))
        )
        yield runs, at, base[2], product
    finally:
        sql.execute("update sim_state set current_run_id=%s,sim_time=%s where id=1", old)
        sql.execute("delete from sim_runs where id=any(%s)", (runs,))
        sql.execute("delete from error_codes where code=%s", (alternate,))


def test_actual_fact_scope_hour_product_and_retention(client, sql, cohort, monkeypatch):
    runs, at, product, alternate = cohort

    async def forbidden(*args, **kwargs):
        raise AssertionError("Fact may not compute money or invoke LLM")

    monkeypatch.setattr("app.economics.dcltv.recompute", forbidden)
    monkeypatch.setattr("app.economics.dcltv.compute_incident", forbidden)
    monkeypatch.setattr("app.llm.failover.ProviderChain.complete_structured", forbidden)
    before = fingerprint(sql)
    sequences = sql.execute("select schemaname,sequencename,last_value from pg_sequences order by 1,2").fetchall()
    current = client.get("/api/metrics/economics/fact").json()
    assert_schema(current, "EconomicsFact")
    explicit = client.get("/api/metrics/economics/fact", params={"run_id": runs[0]}).json()
    assert current == explicit
    observed = {(r["product_code"], r["sim_hour"]): r["signals"] for r in current["faults_matrix"]}
    assert observed == {(product, 9): 1, (product, 10): 2, (alternate, 9): 3}
    assert current["assumptions_vs_fact"]["retention_factors"]["closed_in_sla"] == {
        "manual": 0.9,
        "simulated": 1.0,
        "sample": 1,
    }
    assert current["assumptions_vs_fact"]["detractor_share"]["fact"] is None
    other = client.get("/api/metrics/economics/fact", params={"run_id": runs[1]}).json()
    assert [(r["product_code"], r["sim_hour"], r["signals"]) for r in other["faults_matrix"]] == [(product, 9, 4)]
    assert other["assumptions_vs_fact"]["retention_factors"]["closed_in_sla"]["simulated"] == 0
    all_runs = client.get("/api/metrics/economics/fact?run_id=all").json()
    factor = all_runs["assumptions_vs_fact"]["retention_factors"]["closed_in_sla"]
    assert factor["sample"] == 4 and factor["simulated"] == 0.25
    for requested in (str(runs[0]), str(runs[1]), "current", "all"):
        for fmt in ("csv", "xlsx"):
            response = client.get("/api/metrics/economics/fact/export", params={"run_id": requested, "format": fmt})
            assert response.status_code == 200, response.text[:300] if fmt == "csv" else response.status_code
            if fmt == "xlsx":
                wb = load_workbook(BytesIO(response.content), read_only=True)
                assert wb.active is not None and list(wb.active.values)
                wb.close()
    assert fingerprint(sql) == before
    assert (
        sql.execute("select schemaname,sequencename,last_value from pg_sequences order by 1,2").fetchall() == sequences
    )


def test_missing_current_never_leaks_baseline_or_other_run(client, sql, cohort, monkeypatch):
    runs, _, _, _ = cohort
    baseline = sql.execute("select id from sim_runs where kind='baseline' order by id limit 1").fetchone()[0]
    assert client.get("/api/metrics/economics/fact", params={"run_id": baseline}).json()["faults_matrix"]
    sql.execute("update sim_state set current_run_id=null where id=1")

    async def forbidden(*args, **kwargs):
        raise AssertionError("Missing current must not recompute global money")

    monkeypatch.setattr(dcltv, "recompute", forbidden)
    before = fingerprint(sql)
    response = client.get("/api/metrics/economics/fact")
    assert response.status_code == 200
    result = response.json()
    assert result["faults_matrix"] == result["outcomes"] == result["churned"] == []
    assert all(
        v["simulated"] is None and v["sample"] == 0 for v in result["assumptions_vs_fact"]["retention_factors"].values()
    )
    assert client.get("/api/metrics/economics/fact", params={"run_id": max(runs) + 100000}).status_code == 404
    assert client.get("/api/metrics/dashboard").json() == {}
    economics = client.get("/api/metrics/economics").json()
    assert economics["groups"] == []
    assert economics["potential_loss_rub"] == economics["prevented_loss_rub"] == 0
    assert fingerprint(sql) == before


def test_dashboard_explicit_scope_wins_all_window_with_native_rows(client, sql, cohort):
    runs, _, _, _ = cohort
    response = client.get("/api/metrics/dashboard", params={"window": "all", "run_id": runs[0]})
    assert response.status_code == 200
    assert response.json()["run_id"] == runs[0] and response.json()["signals_total"] == 6
    other = client.get("/api/metrics/dashboard", params={"window": "all", "run_id": runs[1]})
    assert other.json()["run_id"] == runs[1] and other.json()["signals_total"] == 4
    all_runs = client.get("/api/metrics/dashboard?window=all")
    assert all_runs.status_code == 200
    assert all_runs.json()["run_id"] is None and all_runs.json()["signals_total"] >= 10
    for endpoint in ("dashboard", "economics"):
        missing = client.get("/api/metrics/" + endpoint, params={"run_id": max(runs) + 100000})
        assert missing.status_code == 404


def test_configured_zero_assumptions_remain_zero(client, sql, cohort):
    old = sql.execute("select detractor_share,no_return_share from economics_settings where id=1").fetchone()
    try:
        sql.execute("update economics_settings set detractor_share=0,no_return_share=0 where id=1")
        before = fingerprint(sql)
        response = client.get("/api/metrics/economics/fact")
        assert response.status_code == 200
        assumptions = response.json()["assumptions_vs_fact"]
        assert assumptions["detractor_share"] == {"assumed": 0, "fact": None}
        assert assumptions["no_return_share"]["assumed"] == 0
        assert fingerprint(sql) == before
    finally:
        sql.execute("update economics_settings set detractor_share=%s,no_return_share=%s where id=1", old)


def test_foreign_saved_economics_is_rejected_or_excluded(client, sql, cohort):
    runs, at, _, _ = cohort
    incident = sql.execute("select id from incidents where run_id=%s order by id limit 1", (runs[0],)).fetchone()[0]
    try:
        with sql.transaction():
            sql.execute(
                "insert into incident_economics(incident_id,run_id,affected_count,rate_code,rate_rub,detractor_share,no_return_share,potential_loss_rub,computed_sim) "
                "values(%s,%s,1,'bank_average',4050,0.1,0.5,999,%s)",
                (incident, runs[1], at),
            )
    except psycopg.errors.ForeignKeyViolation:
        # Новая composite FK может остановить legacy mismatch раньше reader.
        assert sql.execute("select count(*) from incident_economics where incident_id=%s", (incident,)).fetchone() == (
            0,
        )
    else:
        before = fingerprint(sql)
        response = client.get("/api/metrics/economics/fact", params={"run_id": runs[0]})
        assert response.status_code == 200
        outcome = response.json()["outcomes"][0]
        assert outcome["incidents"] == 1 and outcome["economics_known"] == 0
        assert outcome["potential_loss_rub"] is None
        assert outcome["prevented_loss_rub"] is None and outcome["realized_loss_rub"] is None
        assert fingerprint(sql) == before


def test_missing_partial_and_saved_zero_are_distinct(client, sql, cohort):
    runs, at, _, _ = cohort
    incident = sql.execute("select id from incidents where run_id=%s order by id limit 1", (runs[0],)).fetchone()[0]
    endpoint = f"/api/metrics/economics/fact?run_id={runs[0]}"
    missing = client.get(endpoint).json()["outcomes"][0]
    assert missing["economics_known"] == 0 and missing["potential_loss_rub"] is None
    sql.execute(
        "insert into incident_economics(incident_id,run_id,affected_count,rate_code,rate_rub,detractor_share,no_return_share,potential_loss_rub,computed_sim) "
        "values(%s,%s,0,'bank_average',4050,0.1,0.5,0,%s)",
        (incident, runs[0], at),
    )
    zero = client.get(endpoint).json()["outcomes"][0]
    context = sql.execute(
        "select e.computed_at,i.updated_at,e.computed_sim,i.created_sim,st.sim_time from incident_economics e join incidents i on i.id=e.incident_id cross join sim_state st where i.id=%s and st.id=1",
        (incident,),
    ).fetchone()
    assert zero["economics_known"] == zero["incidents"] == 1, context
    assert zero["potential_loss_rub"] == zero["prevented_loss_rub"] == zero["realized_loss_rub"] == 0
    sql.execute(
        "insert into incidents(run_id,title,incident_type,team_code,complexity,criticality,priority,created_by,created_sim,sla_due_sim,take_due_sim,status,outcome_class) "
        "values(%s,'Учебная неполная оценка','tech_fault','team_cx','easy','low',4,'scenario',%s,%s,%s,'closed','closed_in_sla')",
        (runs[0], at, at, at),
    )
    before = fingerprint(sql)
    partial = client.get(endpoint).json()["outcomes"][0]
    assert_schema(client.get(endpoint).json(), "EconomicsFact")
    assert partial["economics_known"] == 1 and partial["incidents"] == 2
    assert partial["potential_loss_rub"] is None
    response = client.get(f"/api/metrics/economics/fact/export?format=xlsx&run_id={runs[0]}")
    wb = load_workbook(BytesIO(response.content), read_only=True)
    try:
        values = list(wb.active.values)
        assert values[1][:3] == ("outcome", "closed_in_sla", 2)
        assert all(value is None for value in values[1][3:6])
    finally:
        wb.close()
    assert fingerprint(sql) == before


@pytest.mark.parametrize(
    "boundary", ["updated", "future", "before_creation", "clock_unknown", "finished_future", "finished_valid"]
)
def test_stale_or_unknown_own_clock_never_becomes_known_money(client, sql, cohort, boundary):
    runs, at, _, _ = cohort
    incident = sql.execute("select id from incidents where run_id=%s order by id limit 1", (runs[0],)).fetchone()[0]
    sql.execute(
        "insert into incident_economics(incident_id,run_id,affected_count,rate_code,rate_rub,detractor_share,no_return_share,potential_loss_rub,computed_sim) "
        "values(%s,%s,0,'bank_average',4050,0.1,0.5,0,%s)",
        (incident, runs[0], at),
    )
    if boundary == "updated":
        sql.execute(
            "update incident_economics set computed_at=(select updated_at-interval '1 second' from incidents where id=%s) where incident_id=%s",
            (incident, incident),
        )
    elif boundary == "future":
        sql.execute(
            "update incident_economics set computed_sim=(select sim_time+interval '1 hour' from sim_state where id=1) where incident_id=%s",
            (incident,),
        )
    elif boundary == "before_creation":
        sql.execute(
            "update incident_economics set computed_sim=%s-interval '1 hour' where incident_id=%s", (at, incident)
        )
    else:
        sql.execute("update sim_state set current_run_id=%s where id=1", (runs[1],))
        if boundary.startswith("finished_"):
            sql.execute("update sim_runs set status='stopped',finished_sim=%s where id=%s", (at, runs[0]))
            if boundary == "finished_future":
                sql.execute(
                    "update incident_economics set computed_sim=%s+interval '1 hour' where incident_id=%s",
                    (at, incident),
                )
    before = fingerprint(sql)
    response = client.get("/api/metrics/economics/fact", params={"run_id": runs[0]})
    assert response.status_code == 200
    result = response.json()["outcomes"][0]
    assert result["incidents"] == 1
    if boundary == "finished_valid":
        assert result["economics_known"] == 1 and result["potential_loss_rub"] == 0
    else:
        assert result["economics_known"] == 0 and result["potential_loss_rub"] is None
    assert fingerprint(sql) == before


@pytest.mark.parametrize(
    ("detractor", "no_return", "expected"),
    [(0, 0.5, 0), (0.1, 0, 0), (0, 0, 0), (0.2, 0.4, 3240), (None, 0.5, 2025), (0.1, None, 2025), (None, None, 2025)],
)
def test_compute_incident_preserves_explicit_zero_shares(
    cx_db, sql, cohort, monkeypatch, detractor, no_return, expected
):
    runs, at, _, _ = cohort
    incident = sql.execute("select id from incidents where run_id=%s order by id limit 1", (runs[0],)).fetchone()[0]
    sql.execute(
        "update incidents set product_code=null,system_code=null,primary_client_id=null,mass_impact=10 where id=%s",
        (incident,),
    )
    old = sql.execute("select detractor_share,no_return_share from economics_settings where id=1").fetchone()
    ledger = sql.execute("select count(*),coalesce(sum(amount),0) from ledger_entries").fetchone()
    try:
        sql.execute(
            "update economics_settings set detractor_share=%s,no_return_share=%s where id=1",
            (0.1 if detractor is None else detractor, 0.5 if no_return is None else no_return),
        )
        original = dcltv.load_settings
        if detractor is None or no_return is None:

            async def nullable(conn):
                result = await original(conn)
                result["settings"]["detractor_share"] = detractor
                result["settings"]["no_return_share"] = no_return
                return result

            monkeypatch.setattr(dcltv, "load_settings", nullable)

        async def compute():
            async with await psycopg.AsyncConnection.connect(dsn(cx_db)) as conn:
                return await dcltv.compute_incident(conn, incident, sim_time=at)

        result = asyncio.run(compute())
        assert result is not None and result["affected_count"] == 10 and result["rate_rub"] == 4050
        assert result["detractor_share"] == (0.1 if detractor is None else detractor)
        assert result["no_return_share"] == (0.5 if no_return is None else no_return)
        assert result["potential_loss_rub"] == expected
        saved = sql.execute(
            "select potential_loss_rub,detractor_share,no_return_share from incident_economics where incident_id=%s",
            (incident,),
        ).fetchone()
        assert saved[0] == expected
        assert float(saved[1]) == result["detractor_share"] and float(saved[2]) == result["no_return_share"]
        assert sql.execute("select count(*),coalesce(sum(amount),0) from ledger_entries").fetchone() == ledger
    finally:
        sql.execute("update economics_settings set detractor_share=%s,no_return_share=%s where id=1", old)
