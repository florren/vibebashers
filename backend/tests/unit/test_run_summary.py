"""T-042: числовое сравнение без идентификаторов и bool."""

from decimal import Decimal

from app.sim.run_summary import numeric_diff


def test_nested_numeric_diff_and_legacy_counters():
    left = {
        "run_id": 1,
        "summary_version": 1,
        "signals": 4,
        "gifts": False,
        "dashboard": {"hitl_share": 2.5, "economics": {"prevented_loss_rub": Decimal("1.25")}},
        "only_left": 2,
    }
    right = {
        "run_id": 9,
        "summary_version": 2,
        "signals": 8,
        "gifts": 2,
        "dashboard": {"hitl_share": 3.5, "economics": {"prevented_loss_rub": 2.5}},
        "only_right": 8,
    }
    assert numeric_diff(left, right) == {
        "signals": 4.0,
        "dashboard.hitl_share": 1.0,
        "dashboard.economics.prevented_loss_rub": 1.25,
    }
    assert numeric_diff({"a": 1}, {"a": False}) == {}
