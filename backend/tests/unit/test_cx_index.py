"""ТЗ14.1: ручной расчёт, полнота компонентов и отсутствие перенормировки."""

import math

import pytest

from app.analytics.cx_index import (
    COMPONENTS,
    DEFAULT_WEIGHTS,
    Observation,
    hourly_delta,
    validated_weights,
    weighted_index,
)


def observations(values):
    return {key: Observation(value, int(value is not None), 1) for key, value in zip(COMPONENTS, values, strict=True)}


def test_manual_formula_and_hourly_change():
    current = weighted_index(components=observations((80, 20, 50, 40)), weights=DEFAULT_WEIGHTS)
    # 100 - (0.4*80 + 0.25*20 + 0.2*50 + 0.15*40) = 47.
    assert current == 47
    assert hourly_delta(current=current, previous=55) == -8


@pytest.mark.parametrize("value,expected", [(0, 100), (100, 0)])
def test_exact_boundaries(value, expected):
    assert weighted_index(components=observations((value,) * 4), weights=DEFAULT_WEIGHTS) == expected


def test_configured_weights_are_used_as_given_and_result_is_clamped():
    configured = dict(zip(COMPONENTS, (0.1, 0.1, 0.4, 0.4), strict=True))
    assert weighted_index(components=observations((80, 20, 50, 40)), weights=configured) == 54
    assert weighted_index(components=observations((100,) * 4), weights={key: 1 for key in COMPONENTS}) == 0
    assert dict(DEFAULT_WEIGHTS) == dict(zip(COMPONENTS, (0.4, 0.25, 0.2, 0.15), strict=True))


@pytest.mark.parametrize("missing", COMPONENTS)
def test_unknown_never_renormalizes_other_components(missing):
    components = observations((0,) * 4)
    components[missing] = Observation(None, 0, 1)
    assert weighted_index(components=components, weights=DEFAULT_WEIGHTS) is None
    weights = {key: 0 if key == missing else 1 for key in COMPONENTS}
    assert weighted_index(components=components, weights=weights) is None


def test_partial_and_empty_are_distinct_from_known_zero():
    components = observations((0,) * 4)
    components["negativity"] = Observation(0, 1, 2)
    assert weighted_index(components=components, weights=DEFAULT_WEIGHTS) is None
    components["negativity"] = Observation(None, 0, 0)
    assert weighted_index(components=components, weights=DEFAULT_WEIGHTS) is None
    components["negativity"] = Observation(0, 0, 0)
    assert weighted_index(components=components, weights=DEFAULT_WEIGHTS) == 100


@pytest.mark.parametrize("value", [True, math.nan, math.inf, -math.inf, -1, 101])
def test_invalid_component_is_rejected(value):
    with pytest.raises(ValueError):
        Observation(value, 1, 1)


@pytest.mark.parametrize("known,total", [(True, 1), (-1, 1), (2, 1), (0, -1), (1.0, 1)])
def test_invalid_coverage_is_rejected(known, total):
    with pytest.raises(ValueError):
        Observation(None, known, total)


@pytest.mark.parametrize("weight", [-1, True, math.nan, math.inf])
def test_invalid_weight_is_rejected(weight):
    with pytest.raises(ValueError):
        weighted_index(components=observations((0,) * 4), weights={**DEFAULT_WEIGHTS, "sla": weight})


def test_explicit_all_keys_and_positive_weights_required():
    with pytest.raises(ValueError):
        weighted_index(components=observations((0,) * 4), weights={key: 0 for key in COMPONENTS})
    with pytest.raises(ValueError):
        weighted_index(components=observations((0,) * 4), weights={"negativity": 1})
    with pytest.raises(ValueError):
        weighted_index(components={}, weights=DEFAULT_WEIGHTS)


def test_unknown_previous_is_not_current_classification_backdated():
    assert hourly_delta(current=80, previous=None) is None
    assert hourly_delta(current=None, previous=80) is None
    with pytest.raises(ValueError):
        hourly_delta(current=101, previous=80)


def test_large_finite_weights_saturate_without_overflow():
    assert weighted_index(components=observations((100,) * 4), weights={key: 1e308 for key in COMPONENTS}) == 0


@pytest.mark.parametrize(
    "value",
    [
        None,
        [],
        {},
        {"negativity": 1},
        {**DEFAULT_WEIGHTS, "unknown": 1},
        {**DEFAULT_WEIGHTS, "sla": "0.2"},
        {**DEFAULT_WEIGHTS, "sla": 10**1000},
    ],
)
def test_settings_weights_boundary_rejects_malformed_without_fallback(value):
    with pytest.raises(ValueError):
        validated_weights(value)


def test_settings_weights_do_not_normalize_explicit_coefficients():
    configured = {key: 1 for key in COMPONENTS}
    assert validated_weights(configured) == configured
    assert configured == {key: 1 for key in COMPONENTS}


@pytest.mark.parametrize(
    "case,expected",
    [
        ("fresh", False),
        ("warning", True),
        ("overdue", True),
        ("missing_stage", None),
        ("mismatch", None),
        ("future_stage", None),
        ("release", None),
        ("reopen", None),
        ("stale_warning", None),
        ("same_clock", None),
    ],
)
def test_registered_sla_current_lifecycle_is_not_an_exhaustive_forecast(case, expected):
    import datetime as dt

    from app.analytics.cx_index_reader import registered_sla_risk

    now = dt.datetime(2026, 11, 9, 9, tzinfo=dt.UTC)
    row = {
        "status": "in_progress",
        "stage_status": "in_progress",
        "stage_sim": now - dt.timedelta(hours=2),
        "sla_due_sim": now + dt.timedelta(hours=1),
    }
    if case in ("warning", "stale_warning", "same_clock"):
        row.update(warning_event_id=1, warning_sim=now - dt.timedelta(minutes=30), warning_due_sim=row["sla_due_sim"])
    if case == "overdue":
        row["sla_due_sim"] = now - dt.timedelta(seconds=1)
    if case == "missing_stage":
        row["stage_sim"] = None
    if case == "mismatch":
        row["stage_status"] = "new"
    if case == "future_stage":
        row["stage_sim"] = now + dt.timedelta(seconds=1)
    if case == "release":
        row["release_sim"] = now - dt.timedelta(minutes=10)
    if case == "reopen":
        row["reopened_sim"] = now - dt.timedelta(minutes=10)
    if case == "stale_warning":
        row["stage_sim"] = now - dt.timedelta(minutes=10)
    if case == "same_clock":
        row["stage_sim"] = row["warning_sim"]
    assert registered_sla_risk(row, now) is expected


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "stored,source",
    [
        (None, "tz_default"),
        ({"value": {}}, "tz_default"),
        ({"value": {"weights": dict(DEFAULT_WEIGHTS)}}, "configured"),
        ({"value": {"weights": None}}, "invalid"),
        ({"value": {"weights": "private-invalid-sentinel"}}, "invalid"),
        ({"value": True}, "invalid"),
    ],
)
async def test_settings_defaults_only_when_absent_and_never_echo_bad_values(monkeypatch, stored, source):
    from app.analytics import cx_index_reader

    async def fetch(*args, **kwargs):
        return stored

    monkeypatch.setattr(cx_index_reader, "fetch_one", fetch)
    result = await cx_index_reader.weights_config(None)
    assert result["source"] == source
    assert (result["weights"] is None) == (source == "invalid")
    assert "private-invalid-sentinel" not in str(result)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "config", [None, [], {"weights": None}, {"weights": {"sla": 0.2}}, {"weights": {**DEFAULT_WEIGHTS, "sla": True}}]
)
async def test_bad_settings_patch_rejected_before_database(monkeypatch, config):
    from app.api import settings
    from app.errors import Problem

    def bomb(*args, **kwargs):
        raise AssertionError("invalid config must be rejected before DB")

    monkeypatch.setattr(settings, "db", bomb)
    with pytest.raises(Problem) as error:
        await settings.patch_settings({"cx_index": config})
    assert error.value.status == 422
