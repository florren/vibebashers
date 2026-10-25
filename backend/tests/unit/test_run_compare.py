"""T-041: разница счётчиков двух запусков."""

from app.api.sim import _numeric_diff


def test_numeric_diff_subtracts_counters() -> None:
    assert _numeric_diff({"signals": 2, "label": "a"}, {"signals": 5, "label": "b"}) == {"signals": 3.0}
