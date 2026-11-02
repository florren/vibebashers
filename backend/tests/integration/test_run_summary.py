"""T-042: stop/экспорт/сравнение на настоящей изолированной PostgreSQL."""

from __future__ import annotations

import asyncio
import csv
import datetime as dt
import io
import json

import psycopg
import pytest
from fastapi.testclient import TestClient

from app.analytics.dashboard import dashboard
from app.main import app
from app.sim import runs
from app.sim.run_summary import build_summary, csv_events, export_json

pytestmark = pytest.mark.integration


def dsn(url):
    return url.replace("postgresql+psycopg://", "postgresql://")


def baseline(conn):
    return conn.execute("select id from sim_runs where kind='baseline' order by id limit 1").fetchone()[0]


def test_stop_summary_matches_metrics_and_profiles(seeded, conn):
    rid = baseline(conn)
    profile_id = conn.execute("select id from llm_profiles where code='mock'").fetchone()[0]
    conn.execute("update llm_profiles set price_in_per_1m=2,price_out_per_1m=4 where id=%s", (profile_id,))
    signal_id = conn.execute("select id from signals where run_id=%s order by id limit 1", (rid,)).fetchone()[0]
    for kind, tokens in [("agent", 100), ("compare", 10000)]:
        conn.execute(
            "insert into agent_runs(kind,sim_run_id,llm_profile_id,prompt_version,prompt_tokens,completion_tokens,total_tokens,signal_id) values(%s,%s,%s,'test',60,40,%s,%s)",
            (kind, rid, profile_id, tokens, signal_id),
        )

    async def check():
        async with await psycopg.AsyncConnection.connect(dsn(seeded), autocommit=True) as ac:
            now = (await (await ac.execute("select sim_time from sim_state where id=1")).fetchone())[0]
            await runs.set_run_status(ac, rid, "stopped", now)
            stored = (await (await ac.execute("select summary from sim_runs where id=%s", (rid,))).fetchone())[0]
            assert stored["summary_version"] == 1
            assert stored["dashboard"] == json.loads(json.dumps(await dashboard(ac, rid=rid), default=str))
            assert stored["signals"] == 800
            assert stored["dashboard"]["agent_runs"] == 1
            assert stored["dashboard"]["tokens_total"] == 100
            assert stored["tokens"] == 10100
            assert len(stored["llm_profiles"]) == 2
            assert float(stored["llm_profiles"][0]["tariff_cost_estimate"]) == pytest.approx(0.00028)
            assert stored["duration_sim_seconds"] == 14 * 86400
            assert stored["duration_real_seconds"] >= 0
            assert {"outcomes", "assumptions_vs_fact", "churned"} <= stored["fact"].keys()
            original_finished = (
                await (await ac.execute("select finished_at from sim_runs where id=%s", (rid,))).fetchone()
            )[0]
            await runs.set_run_status(ac, rid, "stopped", now)
            assert (await (await ac.execute("select finished_at from sim_runs where id=%s", (rid,))).fetchone())[
                0
            ] == original_finished
            await runs.set_run_status(ac, rid, "running")
            assert (
                await (
                    await ac.execute("select summary,finished_at,finished_sim from sim_runs where id=%s", (rid,))
                ).fetchone()
            ) == (None, None, None)

    asyncio.run(check())


def test_readonly_json_csv_and_run_isolation(seeded, conn):
    rid = baseline(conn)
    historical_count = conn.execute("select count(*) from sim_events where run_id=%s", (rid,)).fetchone()[0]
    assert historical_count > 0

    async def check_seed_history():
        async with await psycopg.AsyncConnection.connect(dsn(seeded)) as ac:
            await ac.execute("set transaction isolation level repeatable read read only")
            exported = await export_json(ac, rid)
            assert sum(row["events"] for row in exported["aggregates"]["hours"]) == historical_count

    asyncio.run(check_seed_history())
    # Контролируемые 1001 строки ниже проверяют CSV/pagination; события истории
    # T-018 уже проверены выше и не должны менять размер этой тестовой фикстуры.
    conn.execute("delete from sim_events where run_id=%s", (rid,))
    other = conn.execute(
        "insert into sim_runs(kind,label,seed,status,started_sim) values('free','other',5,'completed',now()) returning id"
    ).fetchone()[0]
    for event_run, event in [(rid, "=formula"), (other, "other.private")]:
        conn.execute(
            'insert into sim_events(run_id,event_type,payload,sim_time) select %s,%s,\'{"text":"one\\ntwo"}\'::jsonb,now() from generate_series(1,1001)',
            (event_run, event),
        )
    before = conn.execute("select count(*) from db_activity_log").fetchone()[0]

    async def check():
        async with await psycopg.AsyncConnection.connect(dsn(seeded)) as ac:
            await ac.execute("set transaction isolation level repeatable read read only")
            exported = await export_json(ac, rid)
            assert exported["run"]["id"] == rid
            assert {"hours", "products", "teams"} == exported["aggregates"].keys()
            hours = exported["aggregates"]["hours"]
            assert sum(row["events"] for row in hours) == 1001
            assert sum(row["signals"] for row in hours) == 800
            assert sum(row["incidents"] for row in hours) == 150
            assert (
                sum(row["operations"] for row in hours)
                == (await (await ac.execute("select count(*) from operations where run_id=%s", (rid,))).fetchone())[0]
            )
            assert (
                sum(row["failed_operations"] for row in hours)
                == (
                    await (
                        await ac.execute("select count(*) from operations where run_id=%s and status='failed'", (rid,))
                    ).fetchone()
                )[0]
            )
            assert exported["summary"]["dashboard"]["signals_total"] == 800
            chunks = [chunk async for chunk in csv_events(ac, rid)]
            assert len(chunks) == 4
            rows = list(csv.DictReader(io.StringIO("".join(chunks))))
            assert len(rows) == 1001
            assert {int(row["run_id"]) for row in rows} == {rid}
            assert {row["event_type"] for row in rows} == {"'=formula"}
            assert json.loads(rows[0]["payload"])["text"] == "one\ntwo"
            with pytest.raises(LookupError):
                await build_summary(ac, 9999999)

    asyncio.run(check())
    assert conn.execute("select count(*) from db_activity_log").fetchone()[0] == before
    with TestClient(app) as client:
        assert client.get(f"/api/sim/runs/{rid}/export?format=json").status_code == 200
        response = client.get(f"/api/sim/runs/{rid}/export?format=csv")
        assert response.status_code == 200
        assert len(list(csv.DictReader(io.StringIO(response.text)))) == 1001
        assert client.get("/api/sim/runs/99999999/export").status_code == 404
        assert client.get(f"/api/sim/runs/{rid}/export?format=xml").status_code == 422
        comparison = client.get(f"/api/sim/runs/compare?a={rid}&b={other}")
        assert comparison.status_code == 200
        assert comparison.json()["diff"]["dashboard.signals_total"] == -800
        assert conn.execute("select count(*) from db_activity_log").fetchone()[0] == before


def test_start_next_run_finalizes_previous(seeded, conn):
    async def check():
        async with await psycopg.AsyncConnection.connect(dsn(seeded), autocommit=True) as ac:
            now = dt.datetime(2026, 11, 9, 9, tzinfo=dt.UTC)
            first = await runs.create_run(ac, kind="free", label="first", seed=1, sim_time=now)
            second = await runs.create_run(
                ac, kind="free", label="second", seed=2, sim_time=now + dt.timedelta(hours=1)
            )
            previous = await (await ac.execute("select status,summary from sim_runs where id=%s", (first,))).fetchone()
            assert previous[0] == "stopped"
            assert previous[1]["duration_sim_seconds"] == 3600
            assert previous[1]["summary_version"] == 1
            assert (await runs.get_run(ac, second))["status"] == "running"

    asyncio.run(check())


def test_failed_snapshot_rolls_back_stop(seeded, conn, monkeypatch):
    rid = baseline(conn)
    original = conn.execute("select status,summary,finished_at from sim_runs where id=%s", (rid,)).fetchone()

    async def fail(*args, **kwargs):
        raise ValueError("snapshot unavailable")

    monkeypatch.setattr(runs, "build_summary", fail)

    async def check():
        async with await psycopg.AsyncConnection.connect(dsn(seeded), autocommit=True) as ac:
            with pytest.raises(ValueError, match="snapshot unavailable"):
                await runs.set_run_status(ac, rid, "stopped", dt.datetime.now(dt.UTC))

    asyncio.run(check())
    assert conn.execute("select status,summary,finished_at from sim_runs where id=%s", (rid,)).fetchone() == original


def test_next_run_from_api_dictionary_connection(seeded):
    from psycopg.rows import dict_row

    async def check():
        async with await psycopg.AsyncConnection.connect(dsn(seeded), autocommit=True, row_factory=dict_row) as ac:
            now = dt.datetime(2026, 11, 9, 9, tzinfo=dt.UTC)
            first = await runs.create_run(ac, kind="free", label="first dict", seed=1, sim_time=now)
            await runs.create_run(ac, kind="free", label="second dict", seed=2, sim_time=now + dt.timedelta(hours=1))
            row = await (await ac.execute("select status,summary from sim_runs where id=%s", (first,))).fetchone()
            assert row["status"] == "stopped"
            assert row["summary"]["summary_version"] == 1
            assert row["summary"]["duration_sim_seconds"] == 3600

    asyncio.run(check())


def test_explicit_recalculation_and_status_guards(seeded, conn, monkeypatch):
    from pathlib import Path

    monkeypatch.syspath_prepend(str(Path(__file__).resolve().parents[3]))
    from scripts.run_summary import recalculate

    rid = baseline(conn)
    assert asyncio.run(recalculate(rid)) == 0
    stored = conn.execute("select summary from sim_runs where id=%s", (rid,)).fetchone()[0]
    assert stored["summary_version"] == 1 and stored["dashboard"]["signals_total"] == 800
    assert asyncio.run(recalculate(9999999)) == 2
    conn.execute("update sim_runs set status='running' where id=%s", (rid,))
    assert asyncio.run(recalculate(rid)) == 2
