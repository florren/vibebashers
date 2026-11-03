"""T250 prerequisite: native Map scope не расширяет current/empty до всей истории."""

import asyncio

import psycopg
from fastapi.testclient import TestClient

from app.main import create_app
from app.sim.runs import create_run
from tests.helpers import dsn


def fresh_run(url):
    async def create():
        async with await psycopg.AsyncConnection.connect(dsn(url)) as conn:
            at = (await (await conn.execute("select sim_time from sim_state where id=1")).fetchone())[0]
            run = await create_run(conn, kind="free", label="T250 own scope proof", seed=42, sim_time=at)
            await conn.commit()
            return run

    return asyncio.run(create())


def metrics(client, code, run):
    params = {} if run is None else {"run_id": run}
    heat = client.get("/api/map/heat", params={**params, "window_hours": 720})
    cities = client.get(f"/api/map/regions/{code}/cities", params={**params, "window_hours": 720})
    zones = client.get("/api/map/zones", params=params)
    for response in (heat, cities, zones):
        assert response.status_code == 200, response.text
    return (
        sum(r["signals"] for r in heat.json()),
        sum(r["incidents_open"] for r in heat.json()),
        sum(r["signals"] for r in cities.json()),
        sum(r["signals_total"] for r in zones.json()["items"]),
        sum(r["critical_count"] for r in zones.json()["items"]),
        sum(r["copilot_index"] for r in zones.json()["items"]),
    )


def test_map_no_current_fresh_run_all_and_omitted_scope(seeded):
    with psycopg.connect(dsn(seeded), autocommit=True) as sql, TestClient(create_app()) as client:
        code = sql.execute(
            "select c.region_code from signals s join clients c on c.id=s.client_id order by s.received_sim desc limit 1"
        ).fetchone()[0]
        baseline = metrics(client, code, "all")
        assert baseline[0] > 0 and baseline[2] > 0 and baseline[3] > 0
        assert metrics(client, code, None) == metrics(client, code, "current")
        sql.execute("update sim_state set current_run_id=null where id=1")
        for run in ("current", None):
            assert metrics(client, code, run) == (0, 0, 0, 0, 0, 0), run
        assert metrics(client, code, "all") == baseline
        run = fresh_run(seeded)
        for scope in ("current", str(run), None):
            assert metrics(client, code, scope) == (0, 0, 0, 0, 0, 0), scope
        assert metrics(client, code, "all") == baseline
        for bad in ("", " ", "current ", "garbage", "-1", "0", "9223372036854775808"):
            for path in ("/api/map/heat", f"/api/map/regions/{code}/cities", "/api/map/zones"):
                response = client.get(path, params={"run_id": bad})
                assert response.status_code == 422, (path, bad, response.text)


def test_map_zones_current_never_credits_foreign_audio_alert(seeded):
    run = fresh_run(seeded)
    with psycopg.connect(dsn(seeded), autocommit=True) as sql, TestClient(create_app()) as client:
        baseline = sql.execute("select id from sim_runs where kind='baseline' order by id limit 1").fetchone()[0]
        employee, branch, code = sql.execute(
            "select e.id,e.branch_id,b.region_code from employees e join branches b on b.id=e.branch_id order by e.id limit 1"
        ).fetchone()
        at = sql.execute("select sim_time from sim_state where id=1").fetchone()[0]
        # Явный synthetic native fixture; не запись реального аудио/LLM verdict.
        audio = sql.execute(
            "insert into audio_sessions(run_id,branch_id,employee_id,source,stt_provider,diarization_mode,started_sim) values(%s,%s,%s,'transcript','none','manual',%s) returning id",
            (baseline, branch, employee, at),
        ).fetchone()[0]
        sql.execute("insert into compliance_alerts(session_id,kind) values(%s,'immediate')", (audio,))
        all_values = metrics(client, code, "all")
        assert all_values[4] > 0 and all_values[5] > 0
        for scope in ("current", str(run), None):
            values = metrics(client, code, scope)
            assert values[4:] == (0, 0), values
        sql.execute("update sim_state set current_run_id=null where id=1")
        assert metrics(client, code, "current") == (0, 0, 0, 0, 0, 0)
        assert metrics(client, code, "all") == all_values


def test_map_unknown_layer_is_an_explicit_validation_error(seeded):
    with TestClient(create_app()) as client:
        for layer in ("garbage", "", "INCIDENTS", "churn risk"):
            response = client.get("/api/map/heat", params={"layer": layer, "run_id": "all"})
            assert response.status_code == 422, (layer, response.status_code)


def test_map_documented_and_runtime_layer_aliases_are_identical(seeded):
    with TestClient(create_app()) as client:
        for alias, canonical in (("incidents_open", "incidents"), ("churn_risk", "churn")):
            params = {"window_hours": 720, "run_id": "all"}
            actual = client.get("/api/map/heat", params={**params, "layer": alias})
            expected = client.get("/api/map/heat", params={**params, "layer": canonical})
            assert actual.status_code == expected.status_code == 200
            assert any(row["value"] > 0 for row in expected.json())
            assert actual.json() == expected.json(), (alias, canonical)


def test_numeric_branch_trace_ref_is_primary_id_without_changing_lookup_priority(seeded):
    with psycopg.connect(dsn(seeded), autocommit=True) as conn:
        branch = conn.execute("select id from branches where code='0042'").fetchone()
        assert branch is not None and branch[0] != 42
        decoy = conn.execute("select code from branches where id=42").fetchone()
        assert decoy is not None and decoy[0] != "0042"
    with TestClient(create_app()) as client:
        # Числовой ref по-прежнему означает PK: frontend обязан использовать id.
        correct = client.get(f"/api/trace/branch/{branch[0]}", params={"run_id": "all"})
        wrong = client.get("/api/trace/branch/0042", params={"run_id": "all"})
        assert correct.status_code == wrong.status_code == 200
        assert correct.json()["subject"]["ref"] == "VSP-0042"
        assert wrong.json()["subject"]["ref"] == "VSP-" + decoy[0].removeprefix("VSP-")
        assert wrong.json()["subject"]["ref"] != correct.json()["subject"]["ref"]
