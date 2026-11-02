"""ТЗ14.1: ручной расчёт, полнота компонентов и отсутствие перенормировки."""

import math

import pytest

from app.analytics.cx_index import COMPONENTS, DEFAULT_WEIGHTS, Observation, hourly_delta, weighted_index


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
