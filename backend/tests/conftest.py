from __future__ import annotations

import os

import pytest

os.environ.setdefault("APP_ENV", "test")
os.environ.setdefault("LLM_PROVIDER", "mock")


@pytest.fixture(autouse=True)
def isolated_maintenance_control(tmp_path, monkeypatch):
    """Готовый store каждого теста; bootstrap/crash тесты меняют только свой marker."""
    from app.config import get_settings
    from app.sim.maintenance_control import MaintenanceControl

    monkeypatch.setenv("MAINTENANCE_CONTROL_DIR", str(tmp_path / "maintenance-control"))
    get_settings.cache_clear()
    MaintenanceControl().write("idle")
    yield
    get_settings.cache_clear()
