"""T-161: actual PG16, два OS процесса и SIGKILL одного producer после commit."""

from __future__ import annotations

import asyncio
import json
import os
import shutil
import subprocess
import sys
import time
import uuid
from pathlib import Path

import psycopg
import pytest
from psycopg import sql
from psycopg.conninfo import make_conninfo

from tests.helpers import dsn

from .test_behavior_runtime import failed, setup

ROOT = Path(__file__).resolve().parents[2]


def wait_ready(path, proc):
    limit = time.monotonic() + 30
    while time.monotonic() < limit:
        if path.exists():
            result = json.loads(path.read_text())
            if result.get("stage") == "ready":
                return result
        if proc.poll() is not None:
            raise AssertionError("behavior child завершился до prime barrier")
        time.sleep(0.05)
    raise AssertionError("behavior prime barrier timeout")


def stop(proc):
    if proc.poll() is None:
        proc.kill()
    proc.wait(timeout=10)


@pytest.mark.asyncio
async def test_sigkill_restart_matches_uninterrupted_signals_events_timers_and_rng(seeded, monkeypatch, tmp_path):
    dump = shutil.which("pg_dump")
    restore = shutil.which("pg_restore")
    if (
        not dump
        or not restore
        or any(" 16." not in subprocess.check_output([tool, "--version"], text=True) for tool in (dump, restore))
    ):
        pytest.skip("нужны native pg_dump/pg_restore16 для isolated reference clone")
    async with await psycopg.AsyncConnection.connect(dsn(seeded)) as conn:
        run, client, now, sim = await setup(conn, monkeypatch, seeded)
        await sim.conn.close()
        await failed(conn, run, client, now)
    primary = dsn(seeded)
    reference = "cx_behavior_ref_" + uuid.uuid4().hex[:12]
    admin = make_conninfo(primary, dbname="postgres")
    refdsn = make_conninfo(primary, dbname=reference)
    archive = tmp_path / "synthetic-reference.dump"
    subprocess.run(
        [dump, "--format=custom", "--no-owner", "--no-acl", "--file", str(archive), primary],
        check=True,
        capture_output=True,
    )
    with psycopg.connect(admin, autocommit=True) as db:
        db.execute(sql.SQL("create database {}").format(sql.Identifier(reference)))
    children = []
    handles = []
    try:
        subprocess.run(
            [restore, "--no-owner", "--no-acl", "--dbname", refdsn, str(archive)], check=True, capture_output=True
        )
        # Только явный whitelist: ни upper-, ни lowercase provider credentials не
        # наследуются; child запускает Simulator без LLM/network providers.
        base = {key: os.environ[key] for key in ("PATH", "LANG", "LC_ALL", "TZ") if key in os.environ}
        base.update(
            APP_ENV="test",
            ENV_FILE="/dev/null",
            LLM_PROVIDER="mock",
            LLM_RECORD="0",
            LOG_JSONL="false",
            PYTHONPATH=str(ROOT) + os.pathsep + str(ROOT.parent),
        )

        def spawn(url, name, phase, **extra):
            output = tmp_path / (name + ".json")
            handle = (tmp_path / (name + ".log")).open("w")
            handles.append(handle)
            env = (
                base
                | {
                    "DATABASE_URL": url,
                    "DATABASE_URL_TEST": url,
                    "BEHAVIOR_PHASE": phase,
                    "BEHAVIOR_OUTPUT": str(output),
                }
                | extra
            )
            proc = subprocess.Popen(
                [sys.executable, str(ROOT / "tests/fixtures/behavior_process.py")],
                env=env,
                stdout=handle,
                stderr=subprocess.STDOUT,
            )
            children.append(proc)
            return proc, output

        control, a = spawn(primary, "control", "prime")
        crash, b = spawn(refdsn, "crash", "prime")
        ready_a = await asyncio.to_thread(wait_ready, a, control)
        ready_b = await asyncio.to_thread(wait_ready, b, crash)
        assert ready_a == ready_b
        crash.kill()
        await asyncio.to_thread(crash.wait, timeout=10)
        assert crash.returncode < 0
        a.with_suffix(".continue").touch()
        await asyncio.to_thread(control.wait, timeout=30)
        assert control.returncode == 0
        recovered, c = spawn(refdsn, "recovered", "recover", BEHAVIOR_TARGET=ready_b["target"])
        await asyncio.to_thread(recovered.wait, timeout=30)
        assert recovered.returncode == 0
        expected = json.loads(a.read_text())
        actual = json.loads(c.read_text())
        assert expected["stage"] == actual["stage"] == "complete"
        assert expected["digest"] == actual["digest"]
        assert (
            expected["declared_wall_clock"]["validated_review_fields"]
            == actual["declared_wall_clock"]["validated_review_fields"]
        )
        assert (
            expected["declared_wall_clock"]["events_raw_sha256"] != actual["declared_wall_clock"]["events_raw_sha256"]
        )
        assert actual["digest"]["signals"]["count"] == 2
        (tmp_path / "proof.json").write_text(
            json.dumps(
                {
                    "prime_equal": True,
                    "recovered_equal": True,
                    "sigkill_returncode": crash.returncode,
                    "comparison": actual,
                    "control_raw_events_sha256": expected["declared_wall_clock"]["events_raw_sha256"],
                },
                indent=2,
            )
        )
    finally:
        for proc in children:
            await asyncio.to_thread(stop, proc)
        for handle in handles:
            handle.close()
        with psycopg.connect(admin, autocommit=True) as db:
            db.execute(sql.SQL("drop database {}").format(sql.Identifier(reference)))
