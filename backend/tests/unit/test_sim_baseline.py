"""T-040: снимок baseline — info, dump, restore (мок subprocess), API без pg_dump."""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest
from fastapi.testclient import TestClient
from psycopg.types.json import Jsonb

from app.main import create_app
from app.sim import baseline as baseline_svc
from app.sim.engine import Simulator


@pytest.fixture(autouse=True)
def isolated_baseline_files(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Интеграционный seed и локальные снимки не влияют на unit-тесты API."""
    monkeypatch.setattr(baseline_svc, "baseline_dir", lambda: tmp_path)
    monkeypatch.setattr(baseline_svc, "runs_export_dir", lambda: tmp_path / "runs")


def _write_snapshot(tmp_path: Path, profile: str | None = None) -> str:
    prof = profile or baseline_svc.resolve_profile()
    dump_path = tmp_path / f"{prof}.dump"
    dump_path.write_bytes(b"fake-dump")
    (tmp_path / f"{prof}.meta.json").write_text(
        f'{{"profile":"{prof}","seed":42,"baseline_run_id":1,"created_at":"2026-01-01T00:00:00+00:00"}}',
        encoding="utf-8",
    )
    (tmp_path / f"{prof}.dump.sha256").write_text(f"abc123  {prof}.dump\n", encoding="utf-8")
    return prof


def _problem_text(res: Any) -> str:
    body = res.json()
    return str(body.get("detail") or body.get("title") or "")


def _attach_mock_sim(client: TestClient) -> MagicMock:
    sim = MagicMock()
    sim.clock.running = False
    sim.run_status = "completed"
    sim.conn = None
    sim.shutdown = AsyncMock()
    sim.reload_after_restore = AsyncMock()
    sim.control = AsyncMock(return_value={"current_run_id": 99, "current_run_status": "running"})
    client.app.state.sim = sim  # type: ignore[attr-defined]
    return sim


def _mock_dump_conn(profile: str) -> AsyncMock:
    mock_conn = AsyncMock()
    mock_conn.closed = False
    mock_conn.info = SimpleNamespace(dsn="dbname=isolated_mock", password="")
    mock_conn.commit = AsyncMock()

    async def _execute(sql: str, params: tuple[Any, ...] | None = None) -> AsyncMock:
        cur = AsyncMock()
        if "seed_done" in sql:
            cur.fetchone = AsyncMock(return_value=({"profile": profile, "seed": 42, "run_id": 1},))
        elif "sim_runs where kind" in sql:
            cur.fetchone = AsyncMock(return_value=(1,))
        else:
            cur.fetchone = AsyncMock(return_value=None)
            cur.fetchall = AsyncMock(return_value=[])
        return cur

    mock_conn.execute = _execute
    return mock_conn


def test_baseline_info_unavailable(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(baseline_svc, "baseline_dir", lambda: tmp_path)
    info = baseline_svc.info("lite")
    assert info["available"] is False
    assert info["profile"] == "lite"


def test_baseline_info_reads_artifacts(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(baseline_svc, "baseline_dir", lambda: tmp_path)
    prof = _write_snapshot(tmp_path)
    info = baseline_svc.info(prof)
    assert info["available"] is True
    assert info["seed"] == 42
    assert info["sha256"] == "abc123"
    assert info["baseline_run_id"] == 1


def test_dump_requires_pg_dump(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setattr(baseline_svc, "baseline_dir", lambda: tmp_path)
    monkeypatch.setattr(baseline_svc.shutil, "which", lambda _: None)
    conn = MagicMock()
    cur = MagicMock()
    conn.cursor.return_value.__enter__.return_value = cur
    cur.fetchone.side_effect = [
        ({"profile": "lite", "seed": 42, "run_id": 7},),
        (7,),
    ]
    with pytest.raises(baseline_svc.BaselineToolingError, match="pg_dump"):
        baseline_svc.dump_for_connection(conn, "lite", database_url="postgresql://u:p@localhost/db")


def test_dump_invokes_pg_dump(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setattr(baseline_svc, "baseline_dir", lambda: tmp_path)
    monkeypatch.setattr(baseline_svc.shutil, "which", lambda name: f"/usr/bin/{name}")

    def fake_run(cmd: list[str], **kwargs: Any) -> MagicMock:
        out = tmp_path / "lite.dump"
        out.write_bytes(b"dump-bytes")
        proc = MagicMock()
        proc.returncode = 0
        proc.stderr = ""
        return proc

    monkeypatch.setattr(baseline_svc.subprocess, "run", fake_run)
    conn = MagicMock()
    cur = MagicMock()
    conn.cursor.return_value.__enter__.return_value = cur
    cur.fetchone.side_effect = [
        ({"profile": "lite", "seed": 42, "run_id": 7},),
        (7,),
    ]
    result = baseline_svc.dump_for_connection(conn, "lite", database_url="postgresql://u:p@localhost/db")
    assert result["available"] is True
    assert (tmp_path / "lite.dump").exists()
    assert (tmp_path / "lite.meta.json").exists()


def test_baseline_status_api_unavailable() -> None:
    with TestClient(create_app()) as client:
        res = client.get("/api/sim/baseline")
    assert res.status_code == 200
    assert res.json()["available"] is False


def test_baseline_status_api_available(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(baseline_svc, "baseline_dir", lambda: tmp_path)
    _write_snapshot(tmp_path)
    with TestClient(create_app()) as client:
        res = client.get("/api/sim/baseline")
    assert res.status_code == 200
    body = res.json()
    assert body["available"] is True
    assert body["sha256"] == "abc123"
    assert body["size_bytes"] == len(b"fake-dump")
    assert body["baseline_run_id"] == 1


def test_post_baseline_dump_202(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(baseline_svc, "baseline_dir", lambda: tmp_path)
    monkeypatch.setattr(baseline_svc.shutil, "which", lambda name: f"/usr/bin/{name}")
    prof = baseline_svc.resolve_profile()

    def fake_run(cmd: list[str], **kwargs: Any) -> MagicMock:
        out = tmp_path / f"{prof}.dump"
        out.write_bytes(b"dump-bytes")
        proc = MagicMock()
        proc.returncode = 0
        proc.stderr = ""
        return proc

    monkeypatch.setattr(baseline_svc.subprocess, "run", fake_run)

    async def _allow(request: Any) -> MagicMock:
        return request.app.state.sim

    monkeypatch.setattr("app.api.sim._ensure_dump_allowed", _allow)

    with TestClient(create_app()) as client:
        sim = _attach_mock_sim(client)
        sim.connect = AsyncMock(return_value=_mock_dump_conn(prof))
        res = client.post("/api/sim/baseline")
    assert res.status_code == 202
    assert res.json()["available"] is True
    assert (tmp_path / f"{prof}.dump.sha256").is_file()


def test_post_baseline_dump_409_without_pg_dump(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(baseline_svc, "baseline_dir", lambda: tmp_path)
    monkeypatch.setattr(baseline_svc.shutil, "which", lambda _: None)
    prof = baseline_svc.resolve_profile()

    async def _allow(request: Any) -> MagicMock:
        return request.app.state.sim

    monkeypatch.setattr("app.api.sim._ensure_dump_allowed", _allow)
    with TestClient(create_app()) as client:
        sim = _attach_mock_sim(client)
        sim.connect = AsyncMock(return_value=_mock_dump_conn(prof))
        res = client.post("/api/sim/baseline")
    assert res.status_code == 409
    assert "pg_dump" in _problem_text(res)


def test_baseline_restore_conflicts_without_snapshot() -> None:
    with TestClient(create_app()) as client:
        res = client.post("/api/sim/baseline/restore")
    assert res.status_code == 409
    text = _problem_text(res)
    assert "снимок" in text
    assert "pg_dump" not in text.lower()


def test_baseline_restore_202_with_snapshot(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(baseline_svc, "baseline_dir", lambda: tmp_path)
    _write_snapshot(tmp_path)

    async def _fake_restore(request: Any) -> str:
        return "job-111"

    monkeypatch.setattr("app.api.sim._restore_baseline", _fake_restore)
    with TestClient(create_app()) as client:
        _attach_mock_sim(client)
        res = client.post("/api/sim/baseline/restore")
    assert res.status_code == 202
    assert res.json() == {"job_id": "job-111"}


def test_post_sim_runs_baseline_409_without_snapshot() -> None:
    with TestClient(create_app()) as client:
        _attach_mock_sim(client)
        res = client.post("/api/sim/runs", json={"kind": "free", "reset_mode": "baseline"})
    assert res.status_code == 409
    assert "снимок" in _problem_text(res)


def test_post_sim_runs_baseline_restore_and_start(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(baseline_svc, "baseline_dir", lambda: tmp_path)
    _write_snapshot(tmp_path)

    calls: list[str] = []

    async def _fake_restore(request: Any) -> str:
        calls.append("restore")
        return "job-222"

    monkeypatch.setattr("app.api.sim._restore_baseline", _fake_restore)
    with TestClient(create_app()) as client:
        sim = _attach_mock_sim(client)
        res = client.post("/api/sim/runs", json={"kind": "free", "reset_mode": "baseline", "label": "После baseline"})
    assert res.status_code == 200
    assert calls == ["restore"]
    sim.control.assert_awaited_once()
    kw = sim.control.await_args.kwargs
    assert kw["reset_mode"] == "baseline"
    assert kw["label"] == "После baseline"


def test_state_dict_baseline_available(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(baseline_svc, "baseline_dir", lambda: tmp_path)
    _write_snapshot(tmp_path)
    sim = Simulator(seed=7)
    assert sim.state_dict()["baseline_available"] is True


@pytest.mark.asyncio
async def test_restore_preserves_sim_runs_summary(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(baseline_svc, "baseline_dir", lambda: tmp_path)
    monkeypatch.setattr(baseline_svc, "runs_export_dir", lambda: tmp_path / "runs")
    _write_snapshot(tmp_path)

    summary = {"signals": 3, "incidents_open": 1}
    sim_row = (
        1,
        "baseline",
        "Baseline",
        None,
        42,
        None,
        "none",
        None,
        "completed",
        None,
        None,
        None,
        None,
        0,
        summary,
        None,
        None,
        None,
    )

    conn = AsyncMock()
    conn.info = SimpleNamespace(dsn="dbname=isolated_mock", password="")
    fetch_cur = AsyncMock()
    fetch_cur.fetchall = AsyncMock(return_value=[sim_row])
    notify_cur = AsyncMock()
    conn.execute = AsyncMock(side_effect=[fetch_cur, notify_cur])
    conn.commit = AsyncMock()
    conn.close = AsyncMock()

    def fake_pg_restore(dsn: str, dump_path: Path) -> None:
        assert dump_path.is_file()

    monkeypatch.setattr(baseline_svc, "_run_pg_restore", fake_pg_restore)

    inserted: list[tuple[Any, ...]] = []

    async def _track_execute(sql: str, params: tuple[Any, ...] | None = None) -> AsyncMock:
        if params and "insert into sim_runs" in sql.lower():
            inserted.append(params)
        cur = AsyncMock()
        cur.fetchall = AsyncMock(return_value=[])
        cur.fetchone = AsyncMock(return_value=None)
        return cur

    new_conn = AsyncMock()
    new_conn.execute = AsyncMock(side_effect=_track_execute)
    new_conn.commit = AsyncMock()

    class _ConnCtx:
        async def __aenter__(self) -> AsyncMock:
            return new_conn

        async def __aexit__(self, *args: Any) -> None:
            return None

    monkeypatch.setattr(
        baseline_svc.psycopg.AsyncConnection,
        "connect",
        AsyncMock(return_value=_ConnCtx()),
    )

    repair = MagicMock(return_value={"added": 0, "after": 480, "total": 480})
    monkeypatch.setattr(baseline_svc, "_run_csi_repair", repair)
    job_id = await baseline_svc.restore(conn)
    repair.assert_called_once()
    assert new_conn.commit.await_count == 2
    assert job_id
    assert inserted, "sim_runs должны быть восстановлены после pg_restore"
    assert isinstance(inserted[0][14], Jsonb)
    assert inserted[0][14].obj == summary
    statements = [call.args[0].lower() for call in new_conn.execute.await_args_list]
    assert not any("delete from sim_runs" in sql for sql in statements)
    insert = next(sql for sql in statements if "insert into sim_runs" in sql)
    assert "overriding system value" in insert and "on conflict (id) do update" in insert
    assert insert.count("%s") == len(inserted[0]) == 18
