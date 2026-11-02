"""T-161: offline-проверка proposal и воспроизводимые примеры, не runtime loader."""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import sys
from collections.abc import Mapping
from decimal import ROUND_HALF_UP, Decimal
from pathlib import Path
from typing import Any

import yaml

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "backend"))

from app.contracts.enums import ClientState, Segment  # noqa: E402
from app.contracts.events.behavior.psychotype_params import PsychotypeParams  # noqa: E402
from app.sim.behavior.model import BehaviorPolicy, CareEvidence, Snapshot, hazard  # noqa: E402


def unused_strategy(previous: float, evidence: CareEvidence, weights: Mapping[str, float]) -> float:
    raise RuntimeError("offline review не вызывает care_strategy runtime")


def care_score(weights: dict[str, float], components: dict[str, float], scale: int) -> float:
    if set(weights) != set(components) or sum(Decimal(str(x)) for x in weights.values()) != Decimal(1):
        raise ValueError("нужны все компоненты и исходные веса с суммой1")
    if any(not 0 <= x <= 1 for x in components.values()):
        raise ValueError("компоненты вне диапазона")
    value = sum((Decimal(str(weights[key])) * Decimal(str(components[key])) for key in weights), Decimal(0))
    return float(value.quantize(Decimal(1).scaleb(-scale), rounding=ROUND_HALF_UP))


def build_report(policy_path: Path) -> dict[str, Any]:
    policy = yaml.safe_load(policy_path.read_text(encoding="utf-8"))
    if policy["enabled"] is not False or policy["approved_by"] is not None or policy["status"] != "proposed_for_review":
        raise ValueError("этот инструмент принимает только неактивированный draft proposal")
    if set(policy["segment_multiplier"]) != {x.value for x in Segment}:
        raise ValueError("не хватает явных сегментов")
    if policy["hazard"]["clamp"] is not False or policy["hazard"]["trailing_batch_tick_draw"] is not False:
        raise ValueError("proposal не должен скрыто clamp/resample hazard")
    params = yaml.safe_load((ROOT / policy["sources"]["psychotypes"]).read_text())["psychotypes"]
    threshold = BehaviorPolicy(1.0, policy["retained_threshold"], unused_strategy).retained_threshold
    if policy["hazard"]["repeat_meaning"] != "boolean_at_least_one_actual_repeat_complaint":
        raise ValueError("этот draft harness проверяет только явно предложенный boolean repeat")
    scale = int(policy["care"]["numeric_score_storage"]["scale"])
    maxima = []
    for code, entry in params.items():
        parsed = PsychotypeParams.model_validate(entry["params"])
        for segment, multiplier in policy["segment_multiplier"].items():
            model_policy = BehaviorPolicy(multiplier, threshold, unused_strategy)
            raw = hazard(parsed, model_policy, Snapshot(ClientState.WAITING, 0.0, 1, True), repeat=True)
            if not math.isfinite(raw) or not 0 <= raw <= 1:
                raise ValueError("proposal выходит за контрактный raw_hazard domain; нет clamp")
            maxima.append({"psychotype": code, "segment": segment, "raw": raw})
    hours = policy["review_only_sensitivity"]["fixed_exposure_sim_hours"]
    ticks = int(hours * 60 / policy["hazard"]["cadence_sim_minutes"])
    sensitivity = []
    for code, entry in params.items():
        parsed = PsychotypeParams.model_validate(entry["params"])
        for score in policy["review_only_sensitivity"]["care_scores"]:
            raw = hazard(
                parsed,
                BehaviorPolicy(1, threshold, unused_strategy),
                Snapshot(ClientState.WAITING, score, 0, False),
                repeat=False,
            )
            sensitivity.append(
                {
                    "psychotype": code,
                    "care_score": score,
                    "raw_per_tick": raw,
                    "intent_probability_fixed_24h": 1 - (1 - raw) ** ticks,
                }
            )
    components = {"proactive": 0.0, "speed": 1.0, "sla": 1.0, "gift_fit": 0.0, "tone": 1.0, "explanation": 1.0}
    care_examples = []
    for code, entry in params.items():
        p = entry["params"]
        weights = p["care_weights"]
        complete = care_score(weights, components, scale)
        breached = care_score(weights, {**components, "sla": 0.0}, scale)
        bad_tone = care_score(weights, {**components, "tone": 0.0}, scale)
        gifted = care_score(weights, {**components, "gift_fit": p["gift_elasticity"]}, scale)
        proactive = care_score(weights, {**components, "proactive": 1.0}, scale)
        if breached >= complete or bad_tone >= complete:
            raise ValueError("negative evidence не снижает care")
        care_examples.append(
            {
                "psychotype": code,
                "on_time_reply_no_proactive_no_gift": complete,
                "after_sla_breach": breached,
                "after_tone_violation": bad_tone,
                "hypothetical_valid_bonus_gift": gifted,
                "with_prior_proactive": proactive,
                "retained_threshold_sweep": {
                    str(t): complete >= t for t in policy["review_only_sensitivity"]["threshold_sweep"]
                },
            }
        )
    segment_sweep = []
    parsed = PsychotypeParams.model_validate(params["loyal_pragmatic"]["params"])
    for multiplier in policy["review_only_sensitivity"]["segment_multiplier_sweep"]:
        raw = hazard(
            parsed,
            BehaviorPolicy(multiplier, threshold, unused_strategy),
            Snapshot(ClientState.WAITING, 0.5, 0, False),
            repeat=False,
        )
        segment_sweep.append(
            {"multiplier": multiplier, "raw": raw, "intent_probability_fixed_24h": 1 - (1 - raw) ** ticks}
        )
    return {
        "policy_id": policy["policy_id"],
        "status": policy["status"],
        "enabled": False,
        "approved_by": None,
        "policy_sha256": hashlib.sha256(policy_path.read_bytes()).hexdigest(),
        "catalog_sha256": {
            name: hashlib.sha256((ROOT / path).read_bytes()).hexdigest()
            for name, path in policy["sources"].items()
            if name in ("psychotypes", "segments", "gifts")
        },
        "catalog_psychotypes": len(params),
        "explicit_segments": len(policy["segment_multiplier"]),
        "worst_raw_hazard": max(maxima, key=lambda x: x["raw"]),
        "fixed_24h_ticks": ticks,
        "care_examples": care_examples,
        "hazard_sensitivity": sensitivity,
        "segment_sensitivity": segment_sweep,
        "silent_decline_unconditional_example": (1 - params["silent_churner"]["params"]["p_complain"])
        * params["silent_churner"]["params"]["silent_decline_prob"],
        "not_claimed": [
            "real-client calibration",
            "real churn forecast",
            "monetary impact",
            "runtime activation",
            "account closure",
        ],
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--policy", type=Path, default=ROOT / "data/behavior/demo_policy.review.yaml")
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    result = build_report(args.policy)
    payload = json.dumps(result, ensure_ascii=False, indent=2) + "\n"
    if args.output:
        args.output.write_text(payload)
    else:
        sys.stdout.write(payload)


if __name__ == "__main__":
    main()
