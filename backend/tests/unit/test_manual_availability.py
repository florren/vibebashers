"""Остановка сохраняется, ошибка общего исполнителя не отключает ручное ускорение."""

import pytest

from app.demo.execution import manual_active


@pytest.mark.parametrize(
    "status,enabled,expected",
    [
        ("paused", True, True),
        ("running", True, True),
        ("error", False, True),
        ("stopped", False, False),
        ("finished", False, False),
        ("paused", False, False),
    ],
)
def test_manual_availability(status, enabled, expected):
    config = {"mode": "simulation", "auto_advance": True, "status": status, "enabled": enabled}
    assert manual_active(config) == expected
    assert not manual_active({**config, "auto_advance": False})
    assert not manual_active({**config, "mode": "demo"})
