"""Общий разбор действующих порогов карты, включая legacy seed format."""

from __future__ import annotations

from typing import Any


def map_thresholds(raw: dict[str, Any]) -> dict[str, Any]:
    result = {"yellow": 0.25, "red": 0.5, "copilot_weight": 0.5, "window_sim_hours": 24, "critical_red": 3, **raw}
    if "yellow_max" in raw and "red" not in raw:
        result["yellow"], result["red"] = float(raw.get("green_max", 0.25)), float(raw.get("yellow_max", 0.5))
    return result
