"""T-275: протокол автоматического ремонта и ошибки без ложного успеха."""

from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

from app.main import create_app
from app.sim import baseline
from tests.unit.test_sim_baseline import _attach_mock_sim, _write_snapshot


def test_repair_subprocess_uses_environment_and_json(monkeypatch):
    result = {"added": 40, "after": 480, "total": 480}
    run = Mock(return_value=SimpleNamespace(returncode=0, stdout=json.dumps(result), stderr=""))
    monkeypatch.setattr(baseline.subprocess, "run", run)
    url = "postgresql://localhost/isolated_test"
    assert baseline._run_csi_repair(url, Path("/scripts/seed/repair_csi.py")) == result
    assert url not in run.call_args.args[0]
    assert run.call_args.kwargs["env"]["DATABASE_URL"] == url
    assert run.call_args.args[0][-2:] == ["--apply", "--json"]


@pytest.mark.parametrize(
    "code,body",
    [
        (2, {"error": "есть пробелы вне CSI"}),
        (1, {}),
        (0, []),
        (0, {"added": 0}),
        (0, {"added": 0, "after": 440, "total": 480}),
        (0, {"added": 0, "after": "480", "total": "480"}),
    ],
)
def test_repair_failure_is_explicit(monkeypatch, code, body):
    monkeypatch.setattr(
        baseline.subprocess,
        "run",
        Mock(return_value=SimpleNamespace(returncode=code, stdout=json.dumps(body), stderr="")),
    )
    with pytest.raises(baseline.BaselineToolingError, match="восстановление baseline не завершено"):
        baseline._run_csi_repair("postgresql://localhost/test", Path("repair.py"))


def test_invalid_cli_output_is_not_success(monkeypatch):
    monkeypatch.setattr(
        baseline.subprocess, "run", Mock(return_value=SimpleNamespace(returncode=1, stdout="", stderr="script failed"))
    )
    with pytest.raises(baseline.BaselineToolingError, match="не вернул результат"):
        baseline._run_csi_repair("postgresql://localhost/test", Path("repair.py"))


async def test_missing_repair_script_fails_before_restore(tmp_path, monkeypatch):
    monkeypatch.setattr(baseline, "REPO_ROOT", tmp_path)
    monkeypatch.setattr(baseline, "baseline_dir", lambda: tmp_path)
    _write_snapshot(tmp_path)
    pg = Mock()
    monkeypatch.setattr(baseline, "_run_pg_restore", pg)
    conn = AsyncMock()
    with pytest.raises(baseline.BaselineToolingError, match="не найден scripts/seed/repair_csi"):
        await baseline.restore(conn)
    pg.assert_not_called()
    conn.close.assert_not_awaited()


def test_csi_failure_does_not_start_a_run(tmp_path, monkeypatch):
    monkeypatch.setattr(baseline, "baseline_dir", lambda: tmp_path)
    _write_snapshot(tmp_path)
    failed = AsyncMock(side_effect=baseline.BaselineToolingError("Автоматический CSI-ремонт не завершён"))
    monkeypatch.setattr(baseline, "restore", failed)
    with TestClient(create_app()) as client:
        sim = _attach_mock_sim(client)
        sim.connect = AsyncMock(return_value=AsyncMock())
        sim.clock.running = False
        sim.run_status = "completed"
        response = client.post("/api/sim/runs", json={"kind": "free", "reset_mode": "baseline"})
    assert response.status_code == 409 and "CSI" in response.text
    sim.control.assert_not_awaited()


def test_connection_dsn_preserves_authentication_and_database():
    from psycopg.conninfo import conninfo_to_dict

    password = uuid4().hex
    conn = SimpleNamespace(
        info=SimpleNamespace(dsn="host=127.0.0.1 port=55434 dbname=isolated_test user=cx", password=password)
    )
    params = conninfo_to_dict(baseline._connection_dsn(conn))
    assert params["dbname"] == "isolated_test" and params["port"] == "55434"
    assert params["password"] == password
