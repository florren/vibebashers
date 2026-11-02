"""T-161: воспроизводимость неактивного proposal, не одобрение его значений."""

from __future__ import annotations

import importlib.util
import json
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[3]
POLICY = ROOT / "data/behavior/demo_policy.review.yaml"
spec = importlib.util.spec_from_file_location("demo_review", ROOT / "scripts/reviews/behavior_demo_review.py")
assert spec is not None and spec.loader is not None
review = importlib.util.module_from_spec(spec)
spec.loader.exec_module(review)


def test_review_is_disabled_and_catalog_hashes_reproducible() -> None:
    report = review.build_report(POLICY)
    expected = json.loads((ROOT / "docs/reviews/T-161-demo-policy-sensitivity.json").read_text())
    assert report == expected
    assert report["enabled"] is False and report["approved_by"] is None
    assert report["explicit_segments"] == 7 and report["catalog_psychotypes"] == 8
    assert 0 <= report["worst_raw_hazard"]["raw"] <= 1


def test_negative_fact_lowers_care_without_rewriting_psychotypes() -> None:
    for row in review.build_report(POLICY)["care_examples"]:
        assert row["after_sla_breach"] < row["on_time_reply_no_proactive_no_gift"]
        assert row["after_tone_violation"] < row["on_time_reply_no_proactive_no_gift"]
        assert row["with_prior_proactive"] > row["on_time_reply_no_proactive_no_gift"]


def test_cumulative_intent_is_exposed_not_called_real_churn() -> None:
    report = review.build_report(POLICY)
    assert report["fixed_24h_ticks"] == 96
    rows = [x for x in report["hazard_sensitivity"] if x["psychotype"] == "loyal_pragmatic"]
    assert rows[0]["raw_per_tick"] > rows[1]["raw_per_tick"] > rows[2]["raw_per_tick"]
    assert rows[0]["intent_probability_fixed_24h"] > 0.8
    assert "real churn forecast" in report["not_claimed"]


@pytest.mark.parametrize("change", ["enabled", "approval", "missing_segment", "invalid_domain", "boolean_threshold"])
def test_invalid_or_activated_review_refused(tmp_path: Path, change: str) -> None:
    policy = yaml.safe_load(POLICY.read_text())
    if change == "enabled":
        policy["enabled"] = True
    elif change == "approval":
        policy["approved_by"] = "example-only"
    elif change == "missing_segment":
        policy["segment_multiplier"].pop("mass")
    elif change == "boolean_threshold":
        policy["retained_threshold"] = True
    else:
        policy["segment_multiplier"]["mass"] = 100
    p = tmp_path / "draft.yaml"
    p.write_text(yaml.safe_dump(policy))
    with pytest.raises(ValueError):
        review.build_report(p)
