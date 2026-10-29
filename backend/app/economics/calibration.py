"""T-265: частотная калибровка фиксированных корзин, раздельные train/validation и provenance."""

from __future__ import annotations

import datetime as dt
import hashlib
import json
import math
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[3]
DATA = ROOT / "data" / "economics"
PIPELINE = "agent-score-v1"


def digest(value: Any) -> str:
    return hashlib.sha256(
        json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()


def timestamp(value: str) -> dt.datetime:
    parsed = dt.datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.utcoffset() is None:
        raise ValueError("Нужен часовой пояс")
    return parsed


def bucket(score: float) -> int:
    if isinstance(score, bool) or not math.isfinite(score) or not 0 <= score <= 100:
        raise ValueError("Скор должен быть конечным числом от 0 до 100")
    return min(4, int(score // 20))


def fit(rows: list[dict[str, Any]], metadata: dict[str, Any]) -> dict[str, Any]:
    """Один клиент в одном split; только дозревшие контрольные исходы до cutoff."""
    if metadata["scope"] not in ("demo", "observed") or metadata["horizon_days"] != 7:
        raise ValueError("Поддержан горизонт 7 сим-дней и scope demo/observed")
    if metadata["scope"] == "observed" and not metadata.get("business_approval_ref"):
        raise ValueError("Для рабочего контура требуется согласование целевой переменной")
    expected_kind = "synthetic_controls" if metadata["scope"] == "demo" else "observed_controls"
    if metadata.get("data_kind") != expected_kind or (
        metadata["scope"] == "observed" and str(metadata["model"]).startswith("mock:")
    ):
        raise ValueError("Демонстрационные данные и mock не допускаются в рабочий контур")
    cutoff = timestamp(metadata["cutoff_sim"])
    clients: set[str] = set()
    counts = [[0, 0] for _ in range(5)]
    validation: list[tuple[int, int]] = []
    for row in rows:
        if row["client_ref"] in clients:
            raise ValueError("Повтор клиента или утечка между train и validation")
        clients.add(row["client_ref"])
        if (
            row["scope"] != metadata["scope"]
            or row["model"] != metadata["model"]
            or row["prompt_version"] != metadata["prompt_version"]
            or row["score_pipeline"] != PIPELINE
        ):
            raise ValueError("Несовместимый источник прогноза")
        if row["treated"] or row["horizon_days"] != 7:
            raise ValueError("Нужны контрольные наблюдения без вмешательства с тем же горизонтом")
        predicted = timestamp(row["predicted_sim"])
        observed = timestamp(row["observed_until_sim"])
        if observed < predicted + dt.timedelta(days=7) or observed > cutoff:
            raise ValueError("Незрелый исход или наблюдение после cutoff")
        churn_at = timestamp(row["churned_sim"]) if row.get("churned_sim") else None
        if churn_at is not None and (churn_at < predicted or churn_at > observed):
            raise ValueError("Уход до момента прогноза")
        y = int(churn_at is not None and churn_at <= predicted + dt.timedelta(days=7))
        score = row["score"]
        b = bucket(score)
        if row["split"] == "train":
            counts[b][0] += 1
            counts[b][1] += y
        elif row["split"] == "validation":
            validation.append((score, y))
        else:
            raise ValueError("split: train или validation")
    if any(n < 30 for n, _ in counts) or len(validation) < 100:
        raise ValueError("Недостаточно наблюдений: 30 train на корзину и 100 validation")
    probabilities = [k / n for n, k in counts]
    if any(a > b for a, b in zip(probabilities, probabilities[1:], strict=False)):
        raise ValueError("Калибровочная кривая не монотонна")
    val_bins = [[0, 0] for _ in range(5)]
    raw_brier = calibrated_brier = 0.0
    for score, y in validation:
        b = bucket(score)
        val_bins[b][0] += 1
        val_bins[b][1] += y
        raw_brier += (score / 100 - y) ** 2
        calibrated_brier += (probabilities[b] - y) ** 2
    if any(n < 20 for n, _ in val_bins):
        raise ValueError("Недостаточно validation на корзину")
    n = len(validation)
    ece = sum(abs(probabilities[b] - k / count) * count / n for b, (count, k) in enumerate(val_bins))
    metrics = {"raw_brier": raw_brier / n, "calibrated_brier": calibrated_brier / n, "ece": ece, "validation_n": n}
    if ece > 0.12 or calibrated_brier > raw_brier + 0.005:
        raise ValueError("Калибровка не прошла пороги validation")
    result = {
        **metadata,
        "schema_version": 1,
        "score_pipeline": PIPELINE,
        "dataset_sha256": digest(rows),
        "train_n": sum(x[0] for x in counts),
        "metrics": metrics,
        "bins": [
            {"lower": b * 20, "upper": (b + 1) * 20, "n": count, "churned": k, "probability": probabilities[b]}
            for b, (count, k) in enumerate(counts)
        ],
    }
    result["artifact_sha256"] = digest(result)
    return result


def load_registry() -> dict[str, Any]:
    """Только проверенные в Git файлы. Отсутствующий рабочий набор остаётся неизвестным."""
    registry: dict[str, Any] = json.loads((DATA / "registry.json").read_text())
    return registry


def load_profile(scope: str, registry: dict[str, Any]) -> dict[str, Any] | None:
    name = registry["calibrations"].get(scope)
    if name is None:
        return None
    path = (DATA / name).resolve()
    if not path.is_relative_to(DATA.resolve()):
        raise ValueError("Путь калибровки вне data/economics")
    artifact: dict[str, Any] = json.loads(path.read_text())
    expected = artifact.pop("artifact_sha256")
    if digest(artifact) != expected or artifact["scope"] != scope:
        raise ValueError("Повреждённый артефакт калибровки")
    expected_kind = "synthetic_controls" if scope == "demo" else "observed_controls"
    if artifact.get("data_kind") != expected_kind or (
        scope == "observed" and str(artifact["model"]).startswith("mock:")
    ):
        raise ValueError("Демо-артефакт не допускается в рабочий контур")
    metrics = artifact["metrics"]
    bins = artifact["bins"]
    if (
        len(bins) != 5
        or artifact["horizon_days"] != 7
        or metrics["validation_n"] < 100
        or not 0 <= metrics["ece"] <= 0.12
        or metrics["calibrated_brier"] > metrics["raw_brier"] + 0.005
    ):
        raise ValueError("Артефакт не прошёл критерии допуска")
    if any(
        b["n"] < 30
        or not math.isfinite(b["probability"])
        or not 0 <= b["probability"] <= 1
        or b["lower"] != i * 20
        or b["upper"] != (i + 1) * 20
        for i, b in enumerate(bins)
    ):
        raise ValueError("Некорректные корзины калибровки")
    artifact["artifact_sha256"] = expected
    if scope == "observed" and not artifact.get("business_approval_ref"):
        return None
    return artifact


def assess(
    score: Any,
    *,
    model: str | None,
    prompt_version: str | None,
    pipeline: str | None,
    predicted_sim: dt.datetime | None,
    profile: dict[str, Any] | None,
) -> dict[str, Any]:
    valid_score = (
        isinstance(score, (int, float)) and not isinstance(score, bool) and math.isfinite(score) and 0 <= score <= 100
    )
    out: dict[str, Any] = {
        "status": "unknown",
        "probability": None,
        "reason": "no_approved_calibration",
        "raw_score": score if valid_score else None,
        "model": model,
        "prompt_version": prompt_version,
        "score_pipeline": pipeline,
        "predicted_sim": predicted_sim,
        "horizon_days": 7,
        "calibration_id": None,
        "dataset_sha256": None,
        "artifact_sha256": None,
    }
    if profile is None:
        return out
    out.update(
        calibration_id=profile["id"],
        dataset_sha256=profile["dataset_sha256"],
        artifact_sha256=profile["artifact_sha256"],
    )
    if (
        model != profile["model"]
        or prompt_version != profile["prompt_version"]
        or pipeline != profile["score_pipeline"]
    ):
        return {**out, "reason": "source_mismatch"}
    if predicted_sim is None or predicted_sim < timestamp(profile["cutoff_sim"]):
        return {**out, "reason": "temporal_leakage"}
    if score is None:
        return {**out, "reason": "missing_score"}
    try:
        b = bucket(score)
    except (ValueError, TypeError):
        return {**out, "reason": "invalid_score"}
    return {
        **out,
        "status": "calibrated",
        "reason": "synthetic_controls" if profile["scope"] == "demo" else "approved_controls",
        "probability": profile["bins"][b]["probability"],
    }
