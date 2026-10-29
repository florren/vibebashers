"""T-265: независимый validation, допуск источника и честная неизвестность."""

from __future__ import annotations

import copy
import datetime as dt
import json
from decimal import Decimal
from pathlib import Path

import pytest

from app.economics import calibration as cal
from app.economics.evidence import policy_for, qualify
from app.economics.impact import bounds

DATA = Path(__file__).resolve().parents[3] / "data/economics"


def dataset():
    rows = [json.loads(line) for line in (DATA / "demo-controls.jsonl").read_text().splitlines()]
    metadata = json.loads((DATA / "demo-metadata.json").read_text())
    return rows, metadata


def test_reproducible_calibration_and_independent_validation() -> None:
    rows, metadata = dataset()
    artifact = cal.fit(rows, metadata)
    assert artifact == json.loads((DATA / "demo-calibration.json").read_text())
    assert artifact["train_n"] == 1000 and artifact["metrics"]["validation_n"] == 1000
    assert artifact["metrics"]["calibrated_brier"] < artifact["metrics"]["raw_brier"]
    assert artifact["metrics"]["ece"] < 0.12
    changed = copy.deepcopy(rows)
    for row in changed:
        if row["split"] == "validation":
            row["churned_sim"] = None
    with pytest.raises(ValueError, match="validation"):
        cal.fit(changed, metadata)


@pytest.mark.parametrize(
    "change",
    [
        {"treated": True},
        {"scope": "observed"},
        {"model": "other"},
        {"horizon_days": 30},
        {"observed_until_sim": "2026-10-02T00:00:00Z"},
        {"churned_sim": "2026-10-09T00:00:00Z"},
        {"score": float("nan")},
        {"score": True},
        {"split": "test"},
    ],
)
def test_bad_controls_are_rejected(change: dict) -> None:
    rows, metadata = dataset()
    rows[0].update(change)
    with pytest.raises(ValueError):
        cal.fit(rows, metadata)


def test_client_leakage_and_small_sample_rejected() -> None:
    rows, metadata = dataset()
    with pytest.raises(ValueError, match="Недостаточно"):
        cal.fit(rows[:10], metadata)
    rows[-1]["client_ref"] = rows[0]["client_ref"]
    with pytest.raises(ValueError, match="Утечка|утечка"):
        cal.fit(rows, metadata)


def test_unknown_and_version_mismatch_never_become_zero() -> None:
    registry = cal.load_registry()
    profile = cal.load_profile("demo", registry)
    args = dict(
        model="mock:mock-rules-v1",
        prompt_version="v1.1",
        pipeline=cal.PIPELINE,
        predicted_sim=dt.datetime(2026, 11, 9, tzinfo=dt.UTC),
    )
    assert cal.assess(0, profile=profile, **args)["probability"] == 0.06
    assert cal.assess(100, profile=profile, **args)["status"] == "calibrated"
    for change in (
        {"profile": None},
        {"model": "gigachat:live"},
        {"prompt_version": "v2"},
        {"pipeline": None},
        {"predicted_sim": None},
        {"predicted_sim": dt.datetime(2026, 1, 1, tzinfo=dt.UTC)},
    ):
        result = cal.assess(75, **{**args, "profile": profile, **change})
        assert result["status"] == "unknown" and result["probability"] is None
    for score in (None, True, -1, 101, "75", float("inf")):
        result = cal.assess(score, profile=profile, **args)
        assert result["status"] == "unknown" and result["probability"] is None
    assert cal.load_profile("observed", registry) is None
    rows, metadata = dataset()
    metadata.update(scope="observed", data_kind="synthetic_controls")
    with pytest.raises(ValueError):
        cal.fit(rows, metadata)


def test_artifact_tampering_and_path_escape_fail(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(cal, "DATA", tmp_path)
    profile = json.loads((DATA / "demo-calibration.json").read_text())
    profile["bins"][0]["probability"] = 1
    (tmp_path / "bad.json").write_text(json.dumps(profile))
    with pytest.raises(ValueError, match="Повреждённый"):
        cal.load_profile("demo", {"calibrations": {"demo": "bad.json"}})
    with pytest.raises(ValueError, match="вне"):
        cal.load_profile("demo", {"calibrations": {"demo": "../outside.json"}})


def test_observed_requires_observed_controls_and_separate_admission(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    rows, metadata = dataset()
    metadata.update(
        scope="observed",
        data_kind="observed_controls",
        model="gigachat:TEST-fixture",
        business_approval_ref="TEST-business-approval",
    )
    for row in rows:
        row.update(scope="observed", model=metadata["model"])
    # Синтетическая fixture проверяет ветку допуска; в реестр приложения она не попадает.
    artifact = cal.fit(rows, metadata)
    (tmp_path / "observed.json").write_text(json.dumps(artifact))
    monkeypatch.setattr(cal, "DATA", tmp_path)
    profile = cal.load_profile("observed", {"calibrations": {"observed": "observed.json"}})
    assert (
        cal.assess(
            55,
            model=metadata["model"],
            prompt_version="v1.1",
            pipeline=cal.PIPELINE,
            predicted_sim=dt.datetime(2026, 11, 9, tzinfo=dt.UTC),
            profile=profile,
        )["status"]
        == "calibrated"
    )
    assert (
        cal.assess(
            55,
            model="mock:mock-rules-v1",
            prompt_version="v1.1",
            pipeline=cal.PIPELINE,
            predicted_sim=dt.datetime(2026, 11, 9, tzinfo=dt.UTC),
            profile=profile,
        )["probability"]
        is None
    )


def test_fine_requires_real_approvals_in_observed_scope() -> None:
    registry = cal.load_registry()
    assert policy_for("observed", registry) is None
    policy = copy.deepcopy(registry["fine_policies"]["demo"])
    policy["scope"] = "observed"
    registry["fine_policies"]["observed"] = policy
    assert policy_for("observed", registry) is None
    policy.update(basis_ref="TEST-legal-basis", business_approval_ref="TEST-business", legal_approval_ref="TEST-legal")
    assert policy_for("observed", registry) == policy


def test_only_timely_confirmed_policy_matched_deal_has_fine() -> None:
    policy = policy_for("demo", cal.load_registry())
    row = {
        "policy": policy,
        "policy_sha256": cal.digest(policy),
        "decision": "go",
        "outcome": "prevented",
        "session_started_sim": dt.datetime(2026, 11, 9, 7, tzinfo=dt.UTC),
        "intervention_sim": dt.datetime(2026, 11, 9, 8, tzinfo=dt.UTC),
        "deal_closed_sim": dt.datetime(2026, 11, 9, 9, tzinfo=dt.UTC),
    }
    assert qualify(row, policy) == (Decimal(50000), "qualified_demo")
    for change in (
        {"decision": "false_positive"},
        {"outcome": "unknown"},
        {"outcome": "completed"},
        {"policy_sha256": "other"},
        {"deal_closed_sim": row["intervention_sim"]},
        {"intervention_sim": dt.datetime(2025, 1, 1, tzinfo=dt.UTC)},
    ):
        assert qualify({**row, **change}, policy)[0] == 0
    assert qualify(row, None)[1] == "no_approved_policy"


def test_calendar_filter_uses_utc_even_when_database_returns_moscow() -> None:
    start, end = bounds("day", dt.datetime(2026, 11, 9, 1, tzinfo=dt.timezone(dt.timedelta(hours=3))), None, None)
    assert start == dt.datetime(2026, 11, 8, tzinfo=dt.UTC)
    assert end == dt.datetime(2026, 11, 9, tzinfo=dt.UTC)


def test_brier_tolerance_is_mean_loss_not_dataset_sum() -> None:
    source, metadata = dataset()
    for offset, admitted in ((5, True), (10, False)):
        rows = []
        for b in range(5):
            score = b * 20 + 10
            for split in ("train", "validation"):
                churned = score - offset if split == "train" else score
                for index in range(100):
                    rows.append(
                        {
                            **source[0],
                            "client_ref": f"{b}-{split}-{index}",
                            "score": score,
                            "split": split,
                            "churned_sim": "2026-10-02T00:00:00Z" if index < churned else None,
                        }
                    )
        if admitted:
            metrics = cal.fit(rows, metadata)["metrics"]
            assert 0 < metrics["calibrated_brier"] - metrics["raw_brier"] < 0.005
        else:
            with pytest.raises(ValueError, match="validation"):
                cal.fit(rows, metadata)
