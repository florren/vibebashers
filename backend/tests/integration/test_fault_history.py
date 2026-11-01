"""T-018: реальные PostgreSQL causal links/log tool/events и отложенная финализация."""

from __future__ import annotations

import datetime as dt
import random
from collections import Counter
from pathlib import Path

import psycopg
import pytest

from app.agent.tools.base import ToolContext
from app.agent.tools.read import get_system_logs
from app.contracts.registry import validate

ROOT = Path(__file__).resolve().parents[3]


@pytest.fixture
def history(seeded, conn, monkeypatch):
    monkeypatch.syspath_prepend(str(ROOT))
    from scripts.seed import faults

    run_id, now = conn.execute(
        "select id,finished_sim from sim_runs where kind='baseline' order by id limit 1"
    ).fetchone()
    state = conn.execute("select value from settings where key=%s", (f"seed_fault_history:{run_id}",)).fetchone()[0]
    return faults, run_id, now, state


def snapshot(conn, run_id):
    return {
        table: conn.execute(f"select to_jsonb(t) from {table} t where run_id=%s order by id", (run_id,)).fetchall()
        for table in ("operations", "faults", "system_logs", "sim_events")
    }


def test_causal_windows_counts_logs_and_valid_events(history, conn):
    _, run_id, now, state = history
    rows = conn.execute(
        "select id,started_sim,resolved_sim,impact_count,affected_clients,region_codes from faults where run_id=%s",
        (run_id,),
    ).fetchall()
    assert 28 <= len(rows) <= 56
    assert 0.10 <= len(state["regression_candidate_ids"]) / len(rows) <= 0.15
    days = Counter((start - (now - dt.timedelta(days=14))).days for _, start, _, _, _, _ in rows)
    assert set(days) == set(range(14)) and all(2 <= n <= 4 for n in days.values())
    assert any(regions for *_, regions in rows) and any(not regions for *_, regions in rows)
    for fid, start, end, impact, clients, _ in rows:
        assert 10 <= (end - start).total_seconds() / 60 <= 240
        assert conn.execute(
            "select count(*),count(distinct client_id) from operations where fault_id=%s", (fid,)
        ).fetchone() == (impact, clients)
        assert (
            conn.execute(
                "select count(*) from system_logs where fault_id=%s and level='ERROR' and logged_sim between %s and %s",
                (fid, start, end),
            ).fetchone()[0]
            >= 3
        )
    assert sum(row[3] for row in rows) > 0
    assert (
        conn.execute(
            "select count(*) from operations o join faults f on f.id=o.fault_id join clients c on c.id=o.client_id "
            "join error_codes ec on ec.code=f.error_code where f.run_id=%s and (o.run_id<>f.run_id or o.status<>'failed' "
            "or o.error_code<>f.error_code or not f.system_code=any(o.system_path) or ec.system_code<>f.system_code "
            "or o.started_sim<f.started_sim or o.started_sim>=f.resolved_sim "
            "or (cardinality(f.region_codes)>0 and not c.region_code=any(f.region_codes)))",
            (run_id,),
        ).fetchone()[0]
        == 0
    )
    assert (
        conn.execute(
            "select count(*) from operations o join clients c on c.id=o.client_id join faults f on f.run_id=o.run_id "
            "and f.error_code=o.error_code and f.system_code=any(o.system_path) and o.started_sim>=f.started_sim "
            "and o.started_sim<f.resolved_sim and (cardinality(f.region_codes)=0 or c.region_code=any(f.region_codes)) "
            "where o.run_id=%s and o.status='failed' and o.fault_id is distinct from f.id",
            (run_id,),
        ).fetchone()[0]
        == 0
    )
    events = conn.execute(
        "select event_type,payload,sim_time from sim_events where run_id=%s and event_type like 'fault.%%'", (run_id,)
    ).fetchall()
    assert len(events) == 2 * len(rows)
    for kind, payload, when in events:
        assert validate(payload, "sim/fault") == []
        assert kind in ("fault.started", "fault.resolved")
        assert when <= now
    assert (
        conn.execute(
            "select count(*) from faults where run_id=%s and caused_by_incident_id is not null", (run_id,)
        ).fetchone()[0]
        == 0
    )
    assert (
        conn.execute(
            "select count(distinct system_code) from system_logs where run_id=%s and level='INFO' and fault_id is null",
            (run_id,),
        ).fetchone()[0]
        == 12
    )
    messages = [row[0] for row in conn.execute("select message from system_logs where run_id=%s", (run_id,)).fetchall()]
    assert all("@" not in message and "****" not in message and "client_id" not in message for message in messages)


async def test_real_get_system_logs_returns_errors_for_every_fault_and_isolates_run(history, conn, seeded):
    _, run_id, _, _ = history
    faults = conn.execute(
        "select system_code,started_sim,resolved_sim from faults where run_id=%s order by id", (run_id,)
    ).fetchall()
    foreign_id = conn.execute(
        "insert into sim_runs(kind,label,seed,started_sim) values('free','foreign',42,now()) returning id"
    ).fetchone()[0]
    system, start, _ = faults[0]
    conn.execute(
        "insert into system_logs(run_id,system_code,level,component,message,logged_sim) values(%s,%s,'ERROR','test','FOREIGN_RUN_SENTINEL',%s)",
        (foreign_id, system, start),
    )
    async with await psycopg.AsyncConnection.connect(
        seeded.replace("postgresql+psycopg://", "postgresql://")
    ) as async_conn:
        for system, start, end in faults:
            ctx = ToolContext(async_conn, run_id=run_id, agent_run_id=0, sim_time=start + (end - start) / 2)
            result = await get_system_logs(ctx, [system], hours=2, limit=1000)
            in_window = [row for row in result["logs"] if row["level"] == "ERROR" and start <= row["logged_sim"] <= end]
            assert len(in_window) >= 3
            assert all(row["message"] != "FOREIGN_RUN_SENTINEL" for row in result["logs"])
            assert ctx.calls[-1]["ok"] is True


def test_seed_repeat_is_noop_and_keeps_original_operations(history, conn):
    faults, run_id, now, state = history
    before = snapshot(conn, run_id)
    with conn.cursor() as cur:
        assert faults.seed_faults(cur, random.Random(99), run_id, now) == state
    assert snapshot(conn, run_id) == before


def binding(conn, run_id, fid, *, delay=120, action="release", same_system=False):
    system, start = conn.execute("select system_code,started_sim from faults where id=%s", (fid,)).fetchone()
    origin = system if same_system else ("processing" if system != "processing" else "mobile_app")
    incident = conn.execute(
        "insert into incidents(run_id,title,incident_type,system_code,team_code,complexity,criticality,priority,created_by,created_sim,sla_due_sim,take_due_sim) "
        "values(%s,'T018 release binding','tech_fault',%s,'team_processing','easy','medium',2,'scenario',%s,%s,%s) returning id",
        (run_id, origin, start - dt.timedelta(hours=5), start, start),
    ).fetchone()[0]
    release = conn.execute(
        "insert into team_actions(run_id,incident_id,team_code,action,action_sim) values(%s,%s,'team_processing',%s,%s) returning id",
        (run_id, incident, action, start - dt.timedelta(minutes=delay)),
    ).fetchone()[0]
    return {"fault_id": fid, "caused_by_incident_id": incident, "release_action_id": release}


def test_actual_regression_bindings_are_valid_and_idempotent(history, conn):
    faults, run_id, _, state = history
    bindings = [binding(conn, run_id, fid) for fid in state["regression_candidate_ids"]]
    with conn.cursor() as cur:
        faults.finalize_regressions(cur, run_id, bindings)
        before = snapshot(conn, run_id)
        faults.finalize_regressions(cur, run_id, bindings)
    assert snapshot(conn, run_id) == before
    rows = conn.execute(
        "select payload from sim_events where run_id=%s and event_type='fault.regression'", (run_id,)
    ).fetchall()
    assert len(rows) == len(bindings)
    family = conn.execute(
        "select payload->>'fault_id',count(distinct correlation_id) from sim_events where run_id=%s and event_type like 'fault.%%' group by payload->>'fault_id'",
        (run_id,),
    ).fetchall()
    assert len(family) == len(state["fault_ids"]) and all(count == 1 for _, count in family)
    for (payload,) in rows:
        assert validate(payload, "sim/fault_regression") == []
        assert payload["delay_min"] == 120
    stored = conn.execute("select value from settings where key=%s", (f"seed_fault_history:{run_id}",)).fetchone()[0]
    assert stored["regressions_finalized"] == sorted(state["regression_candidate_ids"])


@pytest.mark.parametrize(
    "reason", ["early", "late", "not_release", "same_system", "wrong_run", "duplicate", "not_candidate"]
)
def test_invalid_regression_binding_rolls_back_everything(history, conn, reason):
    faults, run_id, _, state = history
    first = binding(conn, run_id, state["regression_candidate_ids"][0])
    second = binding(
        conn,
        run_id,
        state["regression_candidate_ids"][1],
        delay=30 if reason == "early" else 241 if reason == "late" else 120,
        action="take" if reason == "not_release" else "release",
        same_system=reason == "same_system",
    )
    if reason == "wrong_run":
        foreign = conn.execute(
            "insert into sim_runs(kind,label,seed,started_sim) values('free','foreign release',42,now()) returning id"
        ).fetchone()[0]
        conn.execute("update team_actions set run_id=%s where id=%s", (foreign, second["release_action_id"]))
    elif reason == "duplicate":
        second = first
    elif reason == "not_candidate":
        second["fault_id"] = next(fid for fid in state["fault_ids"] if fid not in state["regression_candidate_ids"])
    before = snapshot(conn, run_id)
    with conn.cursor() as cur, pytest.raises(ValueError):
        faults.finalize_regressions(cur, run_id, [first, second])
    assert snapshot(conn, run_id) == before
    assert (
        conn.execute("select value from settings where key=%s", (f"seed_fault_history:{run_id}",)).fetchone()[0]
        == state
    )


def test_partial_fault_seed_failure_is_atomic(history, conn, monkeypatch):
    faults, _, now, _ = history
    rid = conn.execute(
        "insert into sim_runs(kind,label,seed,started_sim) values('baseline','atomic faults',42,%s) returning id",
        (now,),
    ).fetchone()[0]
    operation = conn.execute(
        "insert into operations(run_id,client_id,product_code,op_type,system_path,status,error_code,started_sim) "
        "select %s,client_id,product_code,op_type,system_path,status,error_code,%s from operations where status='failed' limit 1 returning id",
        (rid, now - dt.timedelta(days=14) + dt.timedelta(hours=1)),
    ).fetchone()[0]
    count = 0
    original = faults._event

    def fail_second(*args):
        nonlocal count
        count += 1
        if count == 2:
            raise ValueError("injected schema failure")
        return original(*args)

    monkeypatch.setattr(faults, "_event", fail_second)
    with conn.cursor() as cur, pytest.raises(ValueError, match="injected"):
        faults.seed_faults(cur, random.Random(42), rid, now)
    for table in ("faults", "system_logs", "sim_events"):
        assert conn.execute(f"select count(*) from {table} where run_id=%s", (rid,)).fetchone()[0] == 0
    assert conn.execute("select value from settings where key=%s", (f"seed_fault_history:{rid}",)).fetchone() is None
    assert conn.execute("select fault_id from operations where id=%s", (operation,)).fetchone() == (None,)


def test_fault_seed_only_links_operations_and_rejects_broken_marker(history, conn):
    faults, _, now, _ = history
    from scripts.seed.operations import seed_operations

    rid = conn.execute(
        "insert into sim_runs(kind,label,seed,started_sim) values('baseline','T018 immutable operations',42,%s) returning id",
        (now,),
    ).fetchone()[0]
    with conn.cursor() as cur:
        seed_operations(cur, random.Random(42), rid, now, per_client=5)
        before = conn.execute(
            "select to_jsonb(o)-'fault_id' from operations o where run_id=%s order by id", (rid,)
        ).fetchall()
        state = faults.seed_faults(cur, random.Random(42), rid, now)
        assert (
            conn.execute(
                "select to_jsonb(o)-'fault_id' from operations o where run_id=%s order by id", (rid,)
            ).fetchall()
            == before
        )
        # Marker не даёт ложного success при повреждённой/неполной истории.
        conn.execute(
            "update settings set value=jsonb_set(value,'{fault_ids}','[]') where key=%s", (f"seed_fault_history:{rid}",)
        )
        with pytest.raises(ValueError, match="marker"):
            faults.seed_faults(cur, random.Random(42), rid, now)
        assert conn.execute("select count(*) from faults where run_id=%s", (rid,)).fetchone()[0] == len(
            state["fault_ids"]
        )


async def test_context_reads_baseline_and_current_but_not_foreign_run_kinds(history, conn, seeded):
    _, baseline_id, _, _ = history
    baseline_fault, system, code, start, end = conn.execute(
        "select id,system_code,error_code,started_sim,resolved_sim from faults where run_id=%s order by id limit 1",
        (baseline_id,),
    ).fetchone()
    current_id = conn.execute(
        "insert into sim_runs(kind,label,seed,started_sim) values('free','current context',42,%s) returning id",
        (start,),
    ).fetchone()[0]
    own_fault = conn.execute(
        "insert into faults(run_id,system_code,error_code,started_sim,resolved_sim) values(%s,%s,%s,%s,%s) returning id",
        (current_id, system, code, start, end),
    ).fetchone()[0]
    conn.execute(
        "insert into system_logs(run_id,system_code,level,component,message,logged_sim) values(%s,%s,'ERROR','test','CURRENT_ALLOWED',%s)",
        (current_id, system, start),
    )
    foreign_faults = []
    for kind in ("free", "scenario", "live"):
        foreign = conn.execute(
            "insert into sim_runs(kind,label,seed,started_sim) values(%s,'foreign context',42,%s) returning id",
            (kind, start),
        ).fetchone()[0]
        fid = conn.execute(
            "insert into faults(run_id,system_code,error_code,started_sim,resolved_sim) values(%s,%s,%s,%s,%s) returning id",
            (foreign, system, code, start, end),
        ).fetchone()[0]
        foreign_faults.append(fid)
        conn.execute(
            "insert into system_logs(run_id,system_code,level,component,message,logged_sim) values(%s,%s,'ERROR','test',%s,%s)",
            (foreign, system, f"FOREIGN_{kind.upper()}", start),
        )
    async with await psycopg.AsyncConnection.connect(
        seeded.replace("postgresql+psycopg://", "postgresql://")
    ) as async_conn:
        ctx = ToolContext(async_conn, run_id=current_id, agent_run_id=0, sim_time=start + (end - start) / 2)
        result = await get_system_logs(ctx, [system], limit=1000)
    ids = {row["fault_id"] for row in result["active_faults"]}
    assert {baseline_fault, own_fault} <= ids
    assert not ids.intersection(foreign_faults)
    messages = {row["message"] for row in result["logs"]}
    assert "CURRENT_ALLOWED" in messages
    assert (
        sum(row["level"] == "ERROR" and row["message"].startswith("health_probe failed") for row in result["logs"]) >= 3
    )
    assert not any(message.startswith("FOREIGN_") for message in messages)


def test_fault_family_correlation_repeats_after_clearing_same_seed_and_ids(history, conn):
    faults, original_run, now, _ = history
    original = snapshot(conn, original_run)
    rid = conn.execute(
        "insert into sim_runs(kind,label,seed,started_sim) values('baseline','correlation repeat',42,%s) returning id",
        (now,),
    ).fetchone()[0]
    with conn.cursor() as cur:
        first = faults.seed_faults(cur, random.Random(42), rid, now)
        before = conn.execute(
            "select event_type,payload,sim_time,correlation_id from sim_events where run_id=%s order by event_type,payload->>'fault_id'",
            (rid,),
        ).fetchall()
        assert len({row[3] for row in before}) == len(first["fault_ids"])
        # Только собственная isolated fixture: возвращаем те же generated fault IDs после очистки.
        for table in ("system_logs", "sim_events", "faults"):
            conn.execute(f"delete from {table} where run_id=%s", (rid,))
        conn.execute("delete from settings where key=%s", (f"seed_fault_history:{rid}",))
        conn.execute("select setval(pg_get_serial_sequence('faults','id'),%s,false)", (min(first["fault_ids"]),))
        second = faults.seed_faults(cur, random.Random(42), rid, now)
        assert second == first
        assert (
            conn.execute(
                "select event_type,payload,sim_time,correlation_id from sim_events where run_id=%s order by event_type,payload->>'fault_id'",
                (rid,),
            ).fetchall()
            == before
        )
    assert snapshot(conn, original_run) == original
