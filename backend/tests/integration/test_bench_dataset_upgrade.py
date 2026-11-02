"""Явный dataset upgrade сохраняет старые cases/results и откатывается целиком при ошибке."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[3]


@pytest.fixture
def legacy(seeded, conn, monkeypatch):
    monkeypatch.syspath_prepend(str(ROOT))
    from scripts.seed import bench_upgrade

    profile = conn.execute("select id from llm_profiles where provider='mock' order by id limit 1").fetchone()[0]
    old = {}
    for family in bench_upgrade.FAMILIES:
        did = conn.execute("select id from bench_datasets where code=%s", (family,)).fetchone()[0]
        conn.execute("update bench_datasets set description=%s where id=%s", (f"legacy data/bench/{family}.jsonl", did))
        cid = conn.execute("select id from bench_cases where dataset_id=%s order by id limit 1", (did,)).fetchone()[0]
        # Старый формат не имеет полного gold/source-id; это только подготовка своей scratch DB.
        conn.execute("update bench_cases set gold=gold-'needs_hitl',tags=array['plain'] where id=%s", (cid,))
        rid = conn.execute(
            "insert into bench_runs(dataset_id,llm_profile_id,prompt_version,status) values(%s,%s,'legacy','done') returning id",
            (did, profile),
        ).fetchone()[0]
        result = conn.execute(
            "insert into bench_results(run_id,case_id,predicted,correct,json_valid_first_try,latency_ms) values(%s,%s,'{}','{}',true,1) returning id",
            (rid, cid),
        ).fetchone()[0]
        old[family] = {
            "id": did,
            "run_id": rid,
            "result_id": result,
            "cases": conn.execute("select * from bench_cases where dataset_id=%s order by id", (did,)).fetchall(),
        }
    return bench_upgrade, old


def snapshot(conn):
    return conn.execute("select id,code,description from bench_datasets order by id").fetchall()


def test_read_only_plan_and_explicit_apply_preserve_history_and_ids(legacy, conn):
    upgrade, old = legacy
    before = snapshot(conn)
    with conn.transaction():
        conn.execute("set transaction isolation level repeatable read read only")
        with conn.cursor() as cur:
            plan = upgrade.build_plan(cur)
        assert conn.execute("show transaction_read_only").fetchone() == ("on",)
    assert snapshot(conn) == before
    assert not plan["blocked"] and all(entry["action"] == "archive_and_create" for entry in plan["datasets"])
    with conn.cursor() as cur:
        applied = upgrade.apply_plan(cur, plan["plan_sha256"])
    assert applied["applied"]
    for entry in plan["datasets"]:
        previous = old[entry["family"]]
        archived = conn.execute(
            "select id,description from bench_datasets where code=%s", (entry["archive_code"],)
        ).fetchone()
        assert archived[0] == previous["id"]
        assert json.loads(archived[1])["family"] == entry["family"]
        assert (
            conn.execute("select * from bench_cases where dataset_id=%s order by id", (previous["id"],)).fetchall()
            == previous["cases"]
        )
        assert conn.execute("select run_id from bench_results where id=%s", (previous["result_id"],)).fetchone() == (
            previous["run_id"],
        )
        current_id = conn.execute("select id from bench_datasets where code=%s", (entry["family"],)).fetchone()[0]
        assert current_id != previous["id"]
        assert conn.execute("select count(*) from bench_cases where dataset_id=%s", (current_id,)).fetchone()[0] == (
            200 if entry["family"] == "golden_v1" else 40
        )
    after = snapshot(conn)
    with conn.cursor() as cur:
        repeated = upgrade.apply_plan(cur, plan["plan_sha256"])
    assert repeated["already_current"] and not repeated["applied"]
    assert snapshot(conn) == after


@pytest.mark.parametrize("reason", ["active", "collision", "stale"])
def test_upgrade_refuses_active_collision_or_stale_plan_without_changes(legacy, conn, reason):
    upgrade, old = legacy
    with conn.cursor() as cur:
        plan = upgrade.build_plan(cur)
    if reason == "active":
        conn.execute("update bench_runs set status='running' where id=%s", (old["golden_v1"]["run_id"],))
    elif reason == "collision":
        conn.execute(
            "insert into bench_datasets(code,title_ru) values(%s,'collision')", (plan["datasets"][0]["archive_code"],)
        )
    else:
        conn.execute(
            "update bench_datasets set description='changed after plan' where id=%s", (old["golden_v1"]["id"],)
        )
    before = snapshot(conn)
    with conn.cursor() as cur, pytest.raises(ValueError):
        upgrade.apply_plan(cur, plan["plan_sha256"])
    assert snapshot(conn) == before
    for previous in old.values():
        assert (
            conn.execute("select * from bench_cases where dataset_id=%s order by id", (previous["id"],)).fetchall()
            == previous["cases"]
        )


def test_second_dataset_failure_rolls_back_first_upgrade(legacy, conn, monkeypatch):
    upgrade, old = legacy
    with conn.cursor() as cur:
        plan = upgrade.build_plan(cur)
    original = upgrade.seed_dataset

    def fail_second(cur, code, rows):
        if code == "lite_v1":
            raise ValueError("injected failure")
        original(cur, code, rows)

    monkeypatch.setattr(upgrade, "seed_dataset", fail_second)
    before = snapshot(conn)
    with conn.cursor() as cur, pytest.raises(ValueError, match="injected"):
        upgrade.apply_plan(cur, plan["plan_sha256"])
    assert snapshot(conn) == before
    for previous in old.values():
        assert (
            conn.execute("select * from bench_cases where dataset_id=%s order by id", (previous["id"],)).fetchall()
            == previous["cases"]
        )


def test_operator_cli_plan_then_apply_and_retry(legacy, seeded, conn):
    import os
    import subprocess
    import sys

    upgrade, old = legacy
    environment = {**os.environ, "APP_ENV": "test", "LLM_PROVIDER": "mock", "DATABASE_URL": seeded}
    command = [sys.executable, str(ROOT / "scripts/seed/bench.py")]
    before = snapshot(conn)
    preview = subprocess.run(
        [*command, "--plan"], env=environment, capture_output=True, text=True, timeout=30, check=False
    )
    assert preview.returncode == 0, preview.stderr
    plan = json.loads(preview.stdout)
    assert snapshot(conn) == before
    applied = subprocess.run(
        [*command, "--apply", "--plan-sha", plan["plan_sha256"]],
        env=environment,
        capture_output=True,
        text=True,
        timeout=30,
        check=False,
    )
    assert applied.returncode == 0, applied.stderr
    assert json.loads(applied.stdout)["applied"]
    after = snapshot(conn)
    repeated = subprocess.run(
        [*command, "--apply", "--plan-sha", plan["plan_sha256"]],
        env=environment,
        capture_output=True,
        text=True,
        timeout=30,
        check=False,
    )
    assert repeated.returncode == 0, repeated.stderr
    assert json.loads(repeated.stdout)["already_current"]
    assert snapshot(conn) == after
    for previous in old.values():
        assert (
            conn.execute("select * from bench_cases where dataset_id=%s order by id", (previous["id"],)).fetchall()
            == previous["cases"]
        )
