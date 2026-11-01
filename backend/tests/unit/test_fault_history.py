"""T-018: диапазоны, детерминизм и отсутствие изменения операций планировщиком."""

from __future__ import annotations

import datetime as dt
import random
from collections import Counter
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[3]
NOW = dt.datetime(2026, 11, 9, 9, tzinfo=dt.UTC)


@pytest.fixture
def faults(monkeypatch):
    monkeypatch.syspath_prepend(str(ROOT))
    from scripts.seed import faults

    return faults


@pytest.mark.parametrize("seed", [1, 42, 789])
def test_deterministic_daily_windows_and_anchor_causality(faults, seed):
    errors = [("APP-LOGIN-FAIL", "mobile_app"), ("DEP-TIMEOUT-503", "sub_deposits")]
    anchors = [(NOW - dt.timedelta(days=d, hours=1), *errors[d % 2], "77") for d in range(14)]
    original = list(anchors)
    plan = faults.plan_faults(random.Random(seed), NOW, errors, anchors)
    assert plan == faults.plan_faults(random.Random(seed), NOW, errors, anchors)
    assert anchors == original
    days = Counter((row.started - (NOW - dt.timedelta(days=14))).days for row in plan)
    assert set(days) == set(range(14))
    assert all(2 <= count <= 4 for count in days.values())
    assert 0.10 <= round(len(plan) * 0.125) / len(plan) <= 0.15
    assert any(row.regions == ("77",) for row in plan)
    assert any(not row.regions for row in plan)
    for row in plan:
        assert NOW - dt.timedelta(days=14) <= row.started < row.resolved <= NOW
        assert 10 <= (row.resolved - row.started).total_seconds() / 60 <= 240
        assert (row.error_code, row.system) in errors


@pytest.mark.parametrize("invalid", ["timezone", "empty", "duplicate", "unknown_anchor"])
def test_invalid_planner_input_is_explicit(faults, invalid):
    errors = [("APP-LOGIN-FAIL", "mobile_app")]
    now, anchors = NOW, []
    if invalid == "timezone":
        now = NOW.replace(tzinfo=None)
    elif invalid == "empty":
        errors = []
    elif invalid == "duplicate":
        errors *= 2
    else:
        anchors = [(NOW - dt.timedelta(hours=1), "WRONG", "mobile_app", "77")]
    with pytest.raises(ValueError):
        faults.plan_faults(random.Random(42), now, errors, anchors)


def test_catalog_contract_gap_is_rejected_before_any_fault_generation(faults):
    # T-014 follow-up: каталог содержит long prefix, но текущий event contract его запрещает.
    from scripts.seed.common import load_yaml

    row = next(row for row in load_yaml("error_codes.yaml")["error_codes"] if row["code"] == "ANTIFRAUD-FALSE-BLOCK")
    with pytest.raises(ValueError, match="event contract"):
        faults.plan_faults(random.Random(42), NOW, [(row["code"], row["system"])], [])
    configured = load_yaml("op_paths.yaml")["failure_codes"]
    assert "AF-FALSE-BLOCK" in configured and "ANTIFRAUD-FALSE-BLOCK" not in configured
