"""T-040 / ADR-0026: exported snapshots и сохранение текущей LLM-конфигурации при reset."""

from __future__ import annotations

import asyncio
import json
import threading
from unittest.mock import AsyncMock

import psycopg
import pytest
from fastapi.testclient import TestClient

from app.config import get_settings
from app.main import create_app
from app.sim import baseline, baseline_llm
from app.sim.engine import Simulator


@pytest.fixture
def snapshot_dir(tmp_path, monkeypatch):
    monkeypatch.setattr(baseline, "baseline_dir", lambda: tmp_path)
    monkeypatch.setattr(baseline, "runs_export_dir", lambda: tmp_path / "runs")
    monkeypatch.setenv("PROFILE", "lite")
    get_settings.cache_clear()
    yield tmp_path
    get_settings.cache_clear()


async def connect(url):
    return await psycopg.AsyncConnection.connect(url.replace("postgresql+psycopg://", "postgresql://"))


async def make_dump(url):
    async with await connect(url) as conn:
        return await baseline.dump(conn, "lite")


async def test_unchanged_llm_config_passes_preflight_without_material_in_metadata(seeded, snapshot_dir):
    await make_dump(seeded)
    async with await connect(seeded) as conn:
        await baseline.preflight_restore(conn, "lite")
    meta = json.loads((snapshot_dir / "lite.meta.json").read_text())
    assert len(meta["llm_config_fingerprint"]) == 64 and len(meta["dump_sha256"]) == 64
    assert set(meta) == {
        "profile",
        "seed",
        "baseline_run_id",
        "created_at",
        "llm_config_fingerprint",
        "db_contract_fingerprint",
        "dump_sha256",
    }


def test_selected_custom_profile_survives_baseline_reset_and_starts_new_run(seeded, conn, snapshot_dir):
    asyncio.run(make_dump(seeded))
    pid = conn.execute(
        "insert into llm_profiles(code,provider,model,role) values('custom-after-dump','mock','mock-custom','main') returning id"
    ).fetchone()[0]
    initial_time = conn.execute("select sim_time from sim_state where id=1").fetchone()[0]
    before = baseline_llm.read_sync(conn.cursor())
    conn.execute("update clients set is_active=false")
    conn.execute("update sim_state set sim_time=sim_time+interval '1 day' where id=1")
    with TestClient(create_app()) as client:

        async def attach_simulator():
            sim = Simulator(dsn=seeded)
            await sim.load_state()
            client.app.state.sim = sim

        client.portal.call(attach_simulator)
        response = client.post("/api/sim/runs", json={"kind": "free", "reset_mode": "baseline", "llm_profile_id": pid})
        assert response.status_code == 202, response.text
        run = response.json()
        assert run["llm_profile_id"] == pid and run["status"] == "running"
        assert client.get("/api/sim/state").json()["running"] is True
        assert client.app.state.maintenance.phase == "ready"
        assert client.post("/api/sim/control", json={"action": "stop"}).status_code == 200
    assert conn.execute("select count(*) from clients where is_active").fetchone()[0] == 200
    assert conn.execute("select sim_time from sim_state where id=1").fetchone() == (initial_time,)
    assert baseline_llm.read_sync(conn.cursor()) == before
    assert conn.execute("select id from llm_profiles where id=%s", (pid,)).fetchone() == (pid,)


async def test_changed_encrypted_key_registry_survives_without_exposing_material(seeded, conn, snapshot_dir):
    await make_dump(seeded)
    conn.execute(
        "insert into llm_api_keys(provider,label,encrypted_key,tokens_limit) values('gigachat','synthetic',pgp_sym_encrypt(%s,%s),100)",
        ("synthetic-test-value", "test-only-encryption-key"),
    )
    before = baseline_llm.read_sync(conn.cursor())
    encrypted = conn.execute("select encrypted_key from llm_api_keys where label='synthetic'").fetchone()[0]
    async with await connect(seeded) as ac:
        await baseline.preflight_restore(ac, "lite")
        await baseline.restore(ac, profile="lite")
    assert baseline_llm.read_sync(conn.cursor()) == before
    assert conn.execute("select encrypted_key from llm_api_keys where label='synthetic'").fetchone() == (encrypted,)
    text = (snapshot_dir / "lite.meta.json").read_text()
    assert "synthetic-test-value" not in text and "encrypted_key" not in text


async def test_legacy_metadata_refuses_before_exports_or_restore(seeded, snapshot_dir, monkeypatch):
    await make_dump(seeded)
    path = snapshot_dir / "lite.meta.json"
    meta = json.loads(path.read_text())
    meta.pop("llm_config_fingerprint")
    path.write_text(json.dumps(meta))
    prepare = AsyncMock()
    monkeypatch.setattr("app.sim.run_lifecycle.prepare_for_restore", prepare)
    async with await connect(seeded) as ac:
        with pytest.raises(baseline.BaselineUnavailableError, match="Пересоздайте"):
            await baseline.restore(ac, profile="lite")
        assert not ac.closed
    prepare.assert_not_awaited()


async def test_digest_and_pg_dump_share_snapshot_during_concurrent_config_change(
    seeded, conn, snapshot_dir, monkeypatch
):
    started = asyncio.Event()
    release = threading.Event()
    loop = asyncio.get_running_loop()
    original = baseline._run_pg_dump
    observed = []

    def blocked(dsn, path, snapshot=None):
        assert snapshot is not None
        loop.call_soon_threadsafe(started.set)
        assert release.wait(10)
        original(dsn, path, snapshot)
        observed.append(True)

    monkeypatch.setattr(baseline, "_run_pg_dump", blocked)
    before = baseline_llm.read_sync(conn.cursor())
    pid = conn.execute("select id from llm_profiles order by id limit 1").fetchone()[0]
    task = asyncio.create_task(make_dump(seeded))
    await asyncio.wait_for(started.wait(), 5)
    conn.execute("update llm_profiles set model=%s where id=%s", ("changed-after-export", pid))
    release.set()
    await task
    assert observed
    meta = json.loads((snapshot_dir / "lite.meta.json").read_text())
    assert meta["llm_config_fingerprint"] == before
    current = baseline_llm.read_sync(conn.cursor())
    assert current != before
    async with await connect(seeded) as ac:
        await baseline.preflight_restore(ac, "lite")
    # Archive и fingerprint относятся к A; bank restore обязан сохранить более поздний рабочий B.
    async with await connect(seeded) as ac:
        await baseline.restore(ac, profile="lite")
    assert conn.execute("select model from llm_profiles where id=%s", (pid,)).fetchone() == ("changed-after-export",)
    assert baseline_llm.read_sync(conn.cursor()) == current


async def test_dump_cancel_waits_process_keeps_snapshot_open_and_preserves_previous_archive(
    seeded, snapshot_dir, monkeypatch
):
    await make_dump(seeded)
    before = {path.name: path.read_bytes() for path in snapshot_dir.iterdir() if path.is_file()}
    started = asyncio.Event()
    release = threading.Event()
    loop = asyncio.get_running_loop()
    original = baseline._run_pg_dump
    completed = []

    def blocked(dsn, path, snapshot=None):
        loop.call_soon_threadsafe(started.set)
        assert release.wait(10)
        original(dsn, path, snapshot)
        completed.append(True)

    monkeypatch.setattr(baseline, "_run_pg_dump", blocked)
    task = asyncio.create_task(make_dump(seeded))
    await asyncio.wait_for(started.wait(), 5)
    task.cancel()
    await asyncio.sleep(0)
    assert not task.done()
    release.set()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert completed
    after = {path.name: path.read_bytes() for path in snapshot_dir.iterdir() if path.is_file()}
    assert after == before


async def test_new_nonpublic_checkpoint_schema_refuses_old_archive_before_effects(
    seeded, conn, snapshot_dir, monkeypatch
):
    await make_dump(seeded)
    prepare = AsyncMock()
    monkeypatch.setattr("app.sim.run_lifecycle.prepare_for_restore", prepare)
    conn.execute("create schema maintenance_checkpoint_probe")
    try:
        conn.execute("create table maintenance_checkpoint_probe.checkpoints(id bigint primary key)")
        async with await connect(seeded) as ac:
            with pytest.raises(baseline.BaselineUnavailableError, match="DB contract"):
                await baseline.restore(ac, profile="lite")
        prepare.assert_not_awaited()
        assert conn.execute("select to_regclass('maintenance_checkpoint_probe.checkpoints')").fetchone()[0]
    finally:
        conn.execute("drop schema maintenance_checkpoint_probe cascade")


async def test_real_agent_db_writer_drains_before_restore_and_cannot_write_reused_ids(
    seeded, conn, snapshot_dir, monkeypatch
):
    from app.agent import runner
    from app.sim.maintenance import MaintenanceCoordinator

    c = MaintenanceCoordinator()
    await make_dump(seeded)
    cid = conn.execute("select id from clients where is_active order by id limit 1").fetchone()[0]
    entered = asyncio.Event()
    release = asyncio.Event()
    stages = []

    async def delayed(conn, **kwargs):
        entered.set()
        await release.wait()
        await conn.execute("update clients set is_active=false where id=%s", (cid,))
        stages.append("agent-effect")
        return {"outcome": "completed"}

    monkeypatch.setattr(runner, "process_signal", delayed)
    agent = runner.AgentService(None, None, dsn=seeded)
    with c.bind():
        actor = agent.submit(1)
    await entered.wait()

    async def action(job):
        stages.append("restore")
        assert actor.done()
        async with await connect(seeded) as ac:
            await baseline.restore(ac, profile="lite", job_id=job)
        return job

    resetting = asyncio.create_task(c.restore(action, park=agent.stop))
    await asyncio.sleep(0)
    assert c.phase == "draining" and stages == []
    release.set()
    await resetting
    assert stages == ["agent-effect", "restore"]
    assert actor.done() and not agent._inflight and not agent._by_signal
    assert conn.execute("select is_active from clients where id=%s", (cid,)).fetchone() == (True,)
    async with await connect(seeded) as ac:
        await baseline.preflight_restore(ac, profile="lite")
