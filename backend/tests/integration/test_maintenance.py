"""T-040: реальные exported snapshots и отказ до reset при LLM drift."""

from __future__ import annotations

import asyncio
import json
import threading
from types import SimpleNamespace
from unittest.mock import AsyncMock

import psycopg
import pytest
from fastapi.testclient import TestClient

from app.config import get_settings
from app.main import create_app
from app.sim import baseline


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


def test_selected_custom_profile_drift_is_409_before_pause_or_reset(seeded, conn, snapshot_dir):
    asyncio.run(make_dump(seeded))
    pid = conn.execute(
        "insert into llm_profiles(code,provider,model,role) values('custom-after-dump','mock','mock-custom','main') returning id"
    ).fetchone()[0]
    before = conn.execute("select count(*) from clients").fetchone()[0]
    with TestClient(create_app()) as client:
        sim = SimpleNamespace(clock=SimpleNamespace(running=True), control=AsyncMock(), run_status="running")
        client.app.state.sim = sim
        response = client.post("/api/sim/runs", json={"kind": "free", "reset_mode": "baseline", "llm_profile_id": pid})
        assert response.status_code == 409 and "LLM" in response.text
        sim.control.assert_not_awaited()
        assert client.app.state.maintenance.phase == "ready"
    assert conn.execute("select count(*) from clients").fetchone()[0] == before
    assert conn.execute("select id from llm_profiles where id=%s", (pid,)).fetchone() == (pid,)


async def test_changed_encrypted_key_registry_refuses_without_exposing_material(seeded, conn, snapshot_dir):
    await make_dump(seeded)
    conn.execute(
        "insert into llm_api_keys(provider,label,encrypted_key,tokens_limit) values('gigachat','synthetic',pgp_sym_encrypt(%s,%s),100)",
        ("synthetic-test-value", "test-only-encryption-key"),
    )
    async with await connect(seeded) as ac:
        with pytest.raises(baseline.BaselineUnavailableError, match="изменились") as exc:
            await baseline.preflight_restore(ac, "lite")
    assert "synthetic-test-value" not in str(exc.value)
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
    pid, model = conn.execute("select id,model from llm_profiles order by id limit 1").fetchone()
    task = asyncio.create_task(make_dump(seeded))
    await asyncio.wait_for(started.wait(), 5)
    conn.execute("update llm_profiles set model=%s where id=%s", ("changed-after-export", pid))
    release.set()
    await task
    assert observed
    async with await connect(seeded) as ac:
        with pytest.raises(baseline.BaselineUnavailableError, match="изменились"):
            await baseline.preflight_restore(ac, "lite")
    # Явная подготовка test fixture: возвращаем исходный config, затем доказываем
    # реальным restore, что archive содержит экспортированный A, не более поздний B.
    conn.execute("update llm_profiles set model=%s where id=%s", (model, pid))
    async with await connect(seeded) as ac:
        await baseline.restore(ac, profile="lite")
    assert conn.execute("select model from llm_profiles where id=%s", (pid,)).fetchone() == (model,)


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
