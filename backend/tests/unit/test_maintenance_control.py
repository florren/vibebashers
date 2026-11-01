"""T-040: устойчивый opaque marker без TTL, автоматического сброса и partial JSON."""

from __future__ import annotations

import json
from unittest.mock import Mock

import pytest

from app.sim.maintenance_control import ControlError, MaintenanceControl


def test_atomic_state_is_fsynced_and_only_opaque_fields_are_persisted(tmp_path, monkeypatch):
    import app.sim.maintenance_control as module

    c = MaintenanceControl(tmp_path)
    assert c.read() is None
    fsync = Mock(wraps=module.os.fsync)
    monkeypatch.setattr(module.os, "fsync", fsync)
    c.initialize_missing()
    assert c.read() == {"version": 1, "phase": "idle", "job_id": None}
    c.write("restoring", "opaque-job")
    assert set(json.loads(c.path.read_text())) == {"version", "phase", "job_id"}
    assert fsync.call_count == 4
    assert not list(tmp_path.glob("*.tmp"))
    with pytest.raises(ControlError, match="явный restore"):
        c.require_idle()
    c.initialize_missing()
    assert c.read()["phase"] == "restoring"
    c.write("idle")
    c.require_idle()


@pytest.mark.parametrize(
    "raw",
    [
        b"{",
        b"{}",
        b"null",
        b"[]",
        b'{"version":true,"phase":"idle","job_id":null}',
        b'{"version":1,"phase":[],"job_id":null}',
        b'{"version":1,"phase":"idle","job_id":"bad"}',
        b"x" * 4097,
    ],
)
def test_corrupt_marker_is_never_automatically_reopened(tmp_path, raw):
    c = MaintenanceControl(tmp_path)
    c.path.write_bytes(raw)
    with pytest.raises(ControlError):
        c.initialize_missing()
    assert c.path.read_bytes() == raw
    with pytest.raises(ControlError):
        c.require_idle()


def test_missing_marker_is_closed_and_existing_failed_has_no_expiry(tmp_path):
    c = MaintenanceControl(tmp_path)
    with pytest.raises(ControlError):
        c.require_idle()
    c.write("failed", "past-job")
    restarted = MaintenanceControl(tmp_path)
    restarted.initialize_missing()
    assert restarted.read() == {"version": 1, "phase": "failed", "job_id": "past-job"}
    with pytest.raises(ControlError):
        restarted.require_idle()


def test_failed_atomic_replace_preserves_previous_marker(tmp_path, monkeypatch):
    from pathlib import Path

    c = MaintenanceControl(tmp_path)
    c.write("failed", "job")
    previous = c.path.read_bytes()
    monkeypatch.setattr(Path, "replace", Mock(side_effect=OSError("synthetic IO failure")))
    with pytest.raises(ControlError, match="надёжно"):
        c.write("idle")
    assert c.path.read_bytes() == previous
    assert not list(tmp_path.glob("*.tmp"))


async def test_bootstrap_owns_exclusive_and_never_clears_failed_or_corrupt(tmp_path):
    from types import SimpleNamespace
    from unittest.mock import AsyncMock

    from app.main import _initialize_maintenance
    from app.sim.maintenance import MaintenanceCoordinator

    control = MaintenanceControl(tmp_path)
    boundary = SimpleNamespace(acquire=AsyncMock(), release=AsyncMock())
    c = MaintenanceCoordinator(boundary=boundary, control=control)
    app = SimpleNamespace(state=SimpleNamespace(maintenance=c))
    assert not await _initialize_maintenance(app)
    boundary.acquire.assert_awaited_once()
    boundary.release.assert_awaited_once()
    control.write("failed", "opaque")
    before = control.path.read_bytes()
    assert await _initialize_maintenance(app)
    assert c.phase == "failed" and not c._ready.is_set()
    assert control.path.read_bytes() == before
    control.path.write_bytes(b"{invalid")
    assert await _initialize_maintenance(app)
    assert control.path.read_bytes() == b"{invalid"
    assert boundary.acquire.await_count == 1


def test_invalid_transition_and_unreadable_marker_fail_closed(tmp_path, monkeypatch):
    from pathlib import Path

    c = MaintenanceControl(tmp_path)
    with pytest.raises(ControlError):
        c.write("unknown")
    with pytest.raises(ControlError):
        c.write("idle", "job")
    monkeypatch.setattr(Path, "open", Mock(side_effect=PermissionError("synthetic")))
    with pytest.raises(ControlError, match="недоступен"):
        c.read()


def test_compose_uses_one_durable_volume_with_readonly_public_origin():
    from pathlib import Path

    import yaml

    root = Path(__file__).resolve().parents[3]
    config = yaml.safe_load((root / "docker-compose.yml").read_text())
    backend = config["services"]["backend"]
    personal = config["services"]["personal"]
    assert (
        backend["environment"]["MAINTENANCE_CONTROL_DIR"]
        == personal["environment"]["MAINTENANCE_CONTROL_DIR"]
        == "/run/cx-maintenance"
    )
    assert "maintenance_control:/run/cx-maintenance" in backend["volumes"]
    assert "maintenance_control:/run/cx-maintenance:ro" in personal["volumes"]
    assert "maintenance_control" in config["volumes"]
