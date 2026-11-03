"""T-161: approved loader и strict care snapshot."""

from __future__ import annotations

import copy
import datetime as dt
from pathlib import Path

import pytest
import yaml

from app.sim.behavior.care import CareComponents, CareState
from app.sim.behavior.codec import dump_care, load_care
from app.sim.behavior.facts import template_fields_present
from app.sim.behavior.policy import DemoPolicy

ROOT = Path(__file__).resolve().parents[3]
PATH = ROOT / "data/behavior/demo_policy.review.yaml"


def test_approved_policy_is_active_immutable_and_domain_preflight(tmp_path) -> None:
    policy = DemoPolicy.load(PATH, validation_only=False)
    disabled = tmp_path / "disabled.yaml"
    disabled.write_text(yaml.safe_dump(policy.spec | {"enabled": False}))
    with pytest.raises(ValueError, match="выключен"):
        DemoPolicy.load(disabled, validation_only=False)
    assert DemoPolicy.load(disabled, validation_only=True).spec["enabled"] is False
    raw = policy.spec
    raw["segment_multiplier"]["mass"] = 999
    assert policy.multiplier("mass") == 1
    params = {
        key: value["params"]
        for key, value in yaml.safe_load((ROOT / "data/psychotypes.yaml").read_text())["psychotypes"].items()
    }
    segments = {row["code"] for row in yaml.safe_load((ROOT / "data/segments.yaml").read_text())["segments"]}
    policy.preflight(params, segments)
    params["anxious"]["base_churn_hazard"] = 1
    with pytest.raises(ValueError, match="raw hazard"):
        policy.preflight(params, segments)
    with pytest.raises(ValueError, match="все текущие"):
        policy.preflight(params, segments - {"mass"})
    with pytest.raises(ValueError, match="отсутствует"):
        policy.multiplier("unlisted")


@pytest.mark.parametrize(
    "change",
    [
        {"status": "draft"},
        {"approved_by": "other"},
        {"enabled": "false"},
        {"version": True},
        {"segment_multiplier": {"mass": True}},
        {"retained_threshold": True},
    ],
)
def test_bad_policy_refused_without_defaults(tmp_path, change) -> None:
    source = yaml.safe_load(PATH.read_text())
    path = tmp_path / "policy.yaml"
    path.write_text(yaml.safe_dump(source | change))
    with pytest.raises(ValueError):
        DemoPolicy.load(path, validation_only=True)


def test_care_snapshot_round_trip_preserves_all_sticky_facts() -> None:
    source = CareState(CareComponents(speed=0.7, gift_fit=0.2), dt.datetime(2026, 11, 2, tzinfo=dt.UTC), True, True)
    snapshot = dump_care(source)
    assert load_care(snapshot) == source
    snapshot["components"]["tone"] = 1
    with pytest.raises(ValueError, match="sticky"):
        load_care(snapshot)


@pytest.mark.parametrize(
    "change",
    [
        {"version": True},
        {"version": 2},
        {"first_reply_at": "2026-11-02T10:00:00"},
        {"tone_violated": 1},
        {"components": {"speed": 0}},
        {"other": "ignored?"},
    ],
)
def test_bad_snapshot_is_not_silently_defaulted(change) -> None:
    original = dump_care(CareState(CareComponents()))
    with pytest.raises(ValueError):
        load_care(copy.deepcopy(original) | change)
    for field in original:
        broken = copy.deepcopy(original)
        del broken[field]
        with pytest.raises(ValueError):
            load_care(broken)


def test_explanation_requires_filled_catalog_template() -> None:
    template = "{{ name }}, мы получили {{ summary }}."
    assert template_fields_present(template, "Клиент, мы получили жалобу.", ["name", "summary"])
    assert not template_fields_present(template, ", мы получили жалобу.", ["name", "summary"])
    assert not template_fields_present(template, "{{ name }}, мы получили жалобу.", ["name", "summary"])
    assert not template_fields_present(template, "Произвольное обещание решить проблему", ["name", "summary"])
    assert not template_fields_present(template, "Клиент, мы получили жалобу.", ["name"])


@pytest.mark.parametrize(
    "at,expected",
    [
        (dt.datetime(1969, 12, 31, 23, 59, 59, 900000, tzinfo=dt.UTC), dt.datetime(1970, 1, 1, tzinfo=dt.UTC)),
        (dt.datetime(2026, 11, 2, 0, 15, tzinfo=dt.UTC), dt.datetime(2026, 11, 2, 0, 30, tzinfo=dt.UTC)),
    ],
)
def test_logical_tick_is_strictly_next_epoch_boundary(at, expected) -> None:
    from app.sim.behavior.owner import BehaviorOwner

    assert BehaviorOwner.next_tick(at) == expected
    with pytest.raises(ValueError):
        BehaviorOwner.next_tick(at.replace(tzinfo=None))
