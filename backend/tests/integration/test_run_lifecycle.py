"""T-040: archive/delete на PostgreSQL без повреждения других запусков."""

from __future__ import annotations

import json

import psycopg
import pytest

from app.sim import baseline, run_lifecycle, runs

pytestmark = pytest.mark.integration


def _run(conn, status="completed", kind="free"):
    return conn.execute(
        "insert into sim_runs(kind,label,seed,status,started_sim,finished_sim,finished_at) "
        "values(%s,'lifecycle',42,%s,now(),now(),now()) returning id",
        (kind, status),
    ).fetchone()[0]


def _signal(conn, rid, *, parent=None):
    client = conn.execute("select id from clients order by id limit 1").fetchone()[0]
    return conn.execute(
        "insert into signals(run_id,client_id,channel_code,text,received_sim,parent_signal_id) "
        "values(%s,%s,'chat','Тест архива',now(),%s) returning id",
        (rid, client, parent),
    ).fetchone()[0]


async def _connect(url):
    return await psycopg.AsyncConnection.connect(url.replace("postgresql+psycopg://", "postgresql://"), autocommit=True)


async def test_archive_preserves_header_summary_export_and_other_runs(seeded, conn, tmp_path, monkeypatch):
    monkeypatch.setattr(baseline, "runs_export_dir", lambda: tmp_path)
    rid = _run(conn)
    other = _run(conn)
    sid = _signal(conn, rid)
    other_sid = _signal(conn, other)
    conn.execute(
        "insert into sim_events(run_id,event_type,payload,sim_time) values(%s,'archive.proof','{}',now())", (rid,)
    )
    async with await _connect(seeded) as ac:
        before = await runs.get_run(ac, rid)
        result = await run_lifecycle.archive(ac, rid)
        assert result["status"] == "archived"
        assert result["started_at"] == before["started_at"]
        assert result["summary"]["signals"] == 1
        assert result["counters"]["signals"] == 0
        assert (await run_lifecycle.archive(ac, rid))["summary"] == result["summary"]
    artifact = json.loads((tmp_path / f"{rid}.json").read_text())
    assert artifact["run"]["id"] == rid
    assert sum(hour["events"] for hour in artifact["aggregates"]["hours"]) == 1
    assert conn.execute("select id from signals where id=%s", (sid,)).fetchone() is None
    assert conn.execute("select id from signals where id=%s", (other_sid,)).fetchone() == (other_sid,)
    assert conn.execute("select count(*) from clients").fetchone()[0] == 200
    assert conn.execute("select count(*) from sim_runs where kind='baseline'").fetchone()[0] == 1


@pytest.mark.parametrize("action", ["archive", "delete"])
async def test_current_baseline_unfinished_missing_are_guarded(seeded, conn, tmp_path, monkeypatch, action):
    monkeypatch.setattr(baseline, "runs_export_dir", lambda: tmp_path)
    base = conn.execute("select id from sim_runs where kind='baseline'").fetchone()[0]
    current = _run(conn)
    conn.execute("update sim_state set current_run_id=%s where id=1", (current,))
    unfinished = _run(conn, "interrupted")
    async with await _connect(seeded) as ac:
        for rid in [base, current, unfinished]:
            with pytest.raises(run_lifecycle.RunConflict):
                await getattr(run_lifecycle, action)(ac, rid)
        with pytest.raises(LookupError):
            await getattr(run_lifecycle, action)(ac, 99999999)
    assert not list(tmp_path.iterdir())
    assert (
        conn.execute("select count(*) from sim_runs where id=any(%s)", ([base, current, unfinished],)).fetchone()[0]
        == 3
    )


@pytest.mark.parametrize("action", ["archive", "delete"])
async def test_cross_run_reference_refuses_purge_without_changes(seeded, conn, tmp_path, monkeypatch, action):
    monkeypatch.setattr(baseline, "runs_export_dir", lambda: tmp_path)
    rid = _run(conn)
    other = _run(conn)
    source = _signal(conn, rid)
    child = _signal(conn, other, parent=source)
    async with await _connect(seeded) as ac:
        with pytest.raises(run_lifecycle.RunConflict, match="signals → signals"):
            await getattr(run_lifecycle, action)(ac, rid)
    assert conn.execute("select parent_signal_id from signals where id=%s", (child,)).fetchone() == (source,)
    assert conn.execute("select status from sim_runs where id=%s", (rid,)).fetchone() == ("completed",)
    assert not list(tmp_path.iterdir())


async def test_delete_preserves_descendant_header_and_archive(seeded, conn, tmp_path, monkeypatch):
    monkeypatch.setattr(baseline, "runs_export_dir", lambda: tmp_path)
    rid = _run(conn)
    child = _run(conn)
    conn.execute("update sim_runs set parent_run_id=%s where id=%s", (rid, child))
    _signal(conn, rid)
    async with await _connect(seeded) as ac:
        await run_lifecycle.archive(ac, rid)
        await run_lifecycle.delete(ac, rid)
    assert conn.execute("select id from sim_runs where id=%s", (rid,)).fetchone() is None
    assert conn.execute("select parent_run_id from sim_runs where id=%s", (child,)).fetchone() == (None,)
    assert (tmp_path / f"{rid}.json").is_file()


async def test_archive_rolls_back_db_and_own_file_if_purge_fails(seeded, conn, tmp_path, monkeypatch):
    monkeypatch.setattr(baseline, "runs_export_dir", lambda: tmp_path)
    rid = _run(conn)
    sid = _signal(conn, rid)
    original = run_lifecycle._purge

    async def fail_after_purge(ac, run_id, roots):
        await original(ac, run_id, roots)
        raise RuntimeError("injected failure")

    monkeypatch.setattr(run_lifecycle, "_purge", fail_after_purge)
    async with await _connect(seeded) as ac:
        with pytest.raises(RuntimeError, match="injected failure"):
            await run_lifecycle.archive(ac, rid)
    assert conn.execute("select id from signals where id=%s", (sid,)).fetchone() == (sid,)
    assert conn.execute("select status from sim_runs where id=%s", (rid,)).fetchone() == ("completed",)
    assert not list(tmp_path.iterdir())


async def test_new_run_none_is_atomic_and_counters_snapshots_settings(seeded, conn):
    from psycopg.rows import dict_row

    conn.execute(
        "insert into settings(key,value) values('policies.archive_test','7'),('llm.keys','\"private-sentinel\"') on conflict(key) do update set value=excluded.value"
    )
    pid = conn.execute("select id from llm_profiles where code='mock'").fetchone()[0]
    base = conn.execute("select id from sim_runs where kind='baseline'").fetchone()[0]
    now = conn.execute("select sim_time from sim_state where id=1").fetchone()[0]
    async with await _connect(seeded) as ac:
        ac.row_factory = dict_row
        first = await runs.create_run(ac, kind="free", label="first", seed=17, sim_time=now, llm_profile_id=pid)
        before = conn.execute("select count(*) from sim_runs").fetchone()[0]
        with pytest.raises(ValueError, match="незавершённый"):
            await runs.create_run(ac, kind="free", label="refused", seed=18, sim_time=now, reset_mode="none")
        assert conn.execute("select count(*) from sim_runs").fetchone()[0] == before
        assert conn.execute("select current_run_id from sim_state where id=1").fetchone() == (first,)
        with pytest.raises(ValueError, match="профиль"):
            await runs.create_run(ac, kind="free", label="invalid", seed=19, sim_time=now, llm_profile_id=999999)
        bench_id = conn.execute(
            "select id from llm_profiles where role='bench_only' and is_active order by id limit 1"
        ).fetchone()[0]
        with pytest.raises(ValueError, match="bench_only"):
            await runs.create_run(
                ac, kind="free", label="bench refused", seed=19, sim_time=now, llm_profile_id=bench_id
            )
        assert conn.execute("select status from sim_runs where id=%s", (first,)).fetchone() == ("running",)
        second = await runs.create_run(ac, kind="free", label="second", seed=18, sim_time=now, reset_mode="counters")
    status, summary = conn.execute("select status,summary from sim_runs where id=%s", (first,)).fetchone()
    assert status == "stopped" and summary["summary_version"] == 1
    row = conn.execute(
        "select seed,llm_profile_id,parent_run_id,settings_snapshot from sim_runs where id=%s", (first,)
    ).fetchone()
    assert row[:3] == (17, pid, base)
    assert row[3]["settings"]["policies.archive_test"] == 7
    assert "private-sentinel" not in json.dumps(row[3])
    assert conn.execute("select signals from v_run_counters where run_id=%s", (second,)).fetchone() == (0,)


async def test_archived_export_api_reads_preserved_aggregates(seeded, conn, tmp_path, monkeypatch):
    from fastapi.testclient import TestClient

    from app.main import create_app

    monkeypatch.setenv("DATABASE_URL", seeded)
    monkeypatch.setattr(baseline, "runs_export_dir", lambda: tmp_path)
    rid = _run(conn)
    _signal(conn, rid)
    async with await _connect(seeded) as ac:
        await run_lifecycle.archive(ac, rid)
    with TestClient(create_app()) as client:
        response = client.get(f"/api/sim/runs/{rid}/export")
        assert response.status_code == 200
        assert sum(row["signals"] for row in response.json()["aggregates"]["hours"]) == 1
        assert client.get(f"/api/sim/runs/{rid}/export?format=csv").status_code == 409
        assert client.post(f"/api/sim/runs/{rid}/archive").status_code == 200
        assert client.delete(f"/api/sim/runs/{rid}").status_code == 204
        assert client.get(f"/api/sim/runs/{rid}").status_code == 404


async def test_baseline_restore_preserves_prior_run_export_summary(seeded, conn, tmp_path, monkeypatch):
    monkeypatch.setattr(baseline, "baseline_dir", lambda: tmp_path)
    monkeypatch.setattr(baseline, "runs_export_dir", lambda: tmp_path / "runs")
    async with await _connect(seeded) as ac:
        await baseline.dump(ac, profile="lite")
    rid = _run(conn, "running")
    _signal(conn, rid)
    conn.execute(
        "insert into sim_events(run_id,event_type,payload,sim_time) values(%s,'restore.proof','{}',now())", (rid,)
    )
    conn.execute("update sim_state set current_run_id=%s where id=1", (rid,))
    async with await _connect(seeded) as ac:
        await baseline.restore(ac, profile="lite")
    status, summary, export_path = conn.execute(
        "select status,summary,export_path from sim_runs where id=%s", (rid,)
    ).fetchone()
    assert status == "archived"
    assert summary["signals"] == 1
    assert export_path == str(tmp_path / "runs" / f"{rid}.json")
    artifact = json.loads((tmp_path / "runs" / f"{rid}.json").read_text())
    assert artifact["summary"] == summary
    assert sum(row["events"] for row in artifact["aggregates"]["hours"]) == 1
    assert conn.execute("select count(*) from signals where run_id=%s", (rid,)).fetchone() == (0,)
    assert conn.execute(
        "select current_run_id=(select id from sim_runs where kind='baseline' order by id limit 1) from sim_state where id=1"
    ).fetchone() == (True,)


@pytest.mark.parametrize("action", ["archive", "delete"])
@pytest.mark.parametrize("external", [False, True])
async def test_behavior_composite_fk_closure_and_foreign_guard(seeded, conn, tmp_path, monkeypatch, action, external):
    from app.sim.behavior.owner import BehaviorOwner
    from app.sim.behavior.store import BehaviorStore
    from tests.helpers import new_run

    from .test_behavior_owner import POLICY, prepare

    monkeypatch.setattr(baseline, "runs_export_dir", lambda: tmp_path)
    async with await _connect(seeded) as ac:
        rid, client, now, _, operations = await prepare(ac)
        other_client = (
            await (await ac.execute("select id from clients where id<>%s order by id limit 1", (client,))).fetchone()
        )[0]
        fault = (await (await ac.execute("select fault_id from operations where id=%s", (operations[0],))).fetchone())[
            0
        ]
        second = (
            await (
                await ac.execute(
                    "insert into operations(run_id,client_id,product_code,op_type,system_path,status,error_code,fault_id,started_sim) values(%s,%s,'deposit','deposit_open',ARRAY['sub_deposits'],'failed','DEP-TIMEOUT-503',%s,%s) returning id",
                    (rid, other_client, fault, now),
                )
            ).fetchone()
        )[0]
        async with ac.transaction():
            store = BehaviorStore(ac)
            await store.enqueue_operation(run_id=rid, operation_id=operations[0])
            await store.enqueue_operation(run_id=rid, operation_id=second)
            await BehaviorOwner(ac, POLICY).advance(run_id=rid, to_sim=now)
        other = await new_run(ac, "composite foreign owner", kind="free")
        assert (
            await (await ac.execute("select count(*) from behavior_runtime where run_id=%s", (rid,))).fetchone()
        ) == (2,)
        if external:
            await ac.execute(
                "create table lifecycle_composite_probe(run_id bigint references sim_runs(id) on delete cascade,target_run bigint,target_client bigint,foreign key(target_run,target_client) references behavior_runtime(run_id,client_id) on delete cascade)"
            )
            await ac.execute("insert into lifecycle_composite_probe values(%s,%s,%s)", (other, rid, client))
            with pytest.raises(run_lifecycle.RunConflict, match="вне его области"):
                await getattr(run_lifecycle, action)(ac, rid)
            assert (
                await (await ac.execute("select count(*) from behavior_runtime where run_id=%s", (rid,))).fetchone()
            ) == (2,)
            assert (await (await ac.execute("select count(*) from lifecycle_composite_probe")).fetchone()) == (1,)
            assert not (tmp_path / f"{rid}.json").exists()
            # Только собственная synthetic foreign ссылка явно удаляется для
            # retry; guard не отключается и CASCADE не разрешается через чужой run.
            await ac.execute("delete from lifecycle_composite_probe")
        await getattr(run_lifecycle, action)(ac, rid)
        for table in (
            "behavior_runtime",
            "behavior_work",
            "behavior_causes",
            "behavior_evidence",
            "behavior_receipts",
            "client_states",
        ):
            from psycopg import sql

            assert (
                await (
                    await ac.execute(
                        sql.SQL("select count(*) from {} where run_id=%s").format(sql.Identifier(table)), (rid,)
                    )
                ).fetchone()
            ) == (0,)
        assert (await (await ac.execute("select id from sim_runs where id=%s", (other,))).fetchone()) == (other,)
        assert (await (await ac.execute("select count(*) from clients")).fetchone()) == (200,)
