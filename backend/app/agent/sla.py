"""Детерминированные поля решения (ТЗ 8.1–8.2, T-061/T-058): приоритет P1–P4, критичность с модификаторами, SLA по матрице и рабочему календарю."""

from __future__ import annotations

import datetime as dt
from typing import Any

from app.agent import gifts as giftmod
from app.sim.clock import add_working_days, add_working_hours

CRIT_ORDER = ["low", "medium", "high"]
SEGMENT_MULTIPLIER = {
    "mass": 1.0,
    "salary": 1.0,
    "social": 1.1,
    "youth": 1.0,
    "premium": 1.3,
    "vip": 1.6,
    "ultra_vip": 2.0,
}
TYPE_COMPLEXITY = {
    "tech_fault": "medium",
    "client_error": "easy",
    "tariff_terms": "easy",
    "service_quality": "easy",
    "fraud_suspicion": "medium",
    "legal_regulatory": "hard",
    "info_request": "easy",
    "suggestion": "easy",
    "gratitude": "easy",
}
DEFAULT_MATRIX: dict[tuple[str, str], dict[str, Any]] = {
    ("easy", "high"): {"fix_days": 1, "report_days": [], "take_hours": 2},
    ("easy", "medium"): {"fix_days": 2, "report_days": [], "take_hours": 4},
    ("easy", "low"): {"fix_days": 3, "report_days": [], "take_hours": 8},
    ("medium", "high"): {"fix_days": 3, "report_days": [], "take_hours": 2},
    ("medium", "medium"): {"fix_days": 4, "report_days": [], "take_hours": 4},
    ("medium", "low"): {"fix_days": 5, "report_days": [], "take_hours": 8},
    ("hard", "high"): {"fix_days": 5, "report_days": [], "take_hours": 2},
    ("hard", "medium"): {"fix_days": 5, "report_days": [3], "take_hours": 4},
    ("hard", "low"): {"fix_days": 10, "report_days": [3, 6, 9], "take_hours": 8},
}


def bump(crit: str, steps: int = 1) -> str:
    i = CRIT_ORDER.index(crit) if crit in CRIT_ORDER else 1
    return CRIT_ORDER[min(len(CRIT_ORDER) - 1, i + steps)]


def effective_criticality(
    base: str, flags: list[str], segment: str | None, signal_type: str, mass_impact: int = 0
) -> str:
    """ТЗ 8.1: повышается при repeat, mass_impact, churn_intent, vip/ultra_vip, legal_regulatory, fraud_suspicion."""
    crit = base if base in CRIT_ORDER else "medium"
    if "repeat" in flags:
        crit = bump(crit)
    if "mass_impact" in flags or mass_impact >= 3:
        crit = bump(crit)
    if "churn_intent" in flags:
        crit = bump(crit)
    if segment in ("vip", "ultra_vip"):
        crit = bump(crit)
    if signal_type in ("legal_regulatory", "fraud_suspicion"):
        crit = "high"
    return crit


def priority(crit: str, churn_risk: int, segment: str | None, flags: list[str]) -> int:
    """P1–P4 = f(критичность, риск ухода, множитель сегмента, повторность); P1 — самый срочный."""
    score = {"high": 3.0, "medium": 2.0, "low": 1.0}.get(crit, 2.0)
    score += churn_risk / 50.0  # 0..2
    score *= SEGMENT_MULTIPLIER.get(segment or "mass", 1.0)
    if "repeat" in flags:
        score += 0.5
    if "churn_intent" in flags:
        score += 0.5
    if score >= 4.5:
        return 1
    if score >= 3.2:
        return 2
    if score >= 2.0:
        return 3
    return 4


def sla_for(
    complexity: str, crit: str, created_sim: dt.datetime, matrix: dict[tuple[str, str], dict[str, Any]] | None = None
) -> dict[str, Any]:
    """Поле decision.sla + сроки для incidents: due_sim по рабочим дням, take_due_sim по рабочим часам, report_due_sims."""
    m = (matrix or DEFAULT_MATRIX).get((complexity, crit)) or DEFAULT_MATRIX[("medium", "medium")]
    if complexity == "instant":
        due = created_sim + dt.timedelta(seconds=15)
        return {
            "fix_days": 1,
            "report_days": [],
            "take_hours": 0,
            "due_sim": due.isoformat(),
            "take_due_sim": due.isoformat(),
            "report_due_sims": [],
        }
    due = add_working_days(created_sim, int(m["fix_days"]))
    take = add_working_hours(created_sim, float(m["take_hours"]))
    reports = [add_working_days(created_sim, int(d)).isoformat() for d in (m.get("report_days") or [])]
    return {
        "fix_days": int(m["fix_days"]),
        "report_days": list(m.get("report_days") or []),
        "take_hours": int(m["take_hours"]),
        "due_sim": due.isoformat(),
        "take_due_sim": take.isoformat(),
        "report_due_sims": reports,
    }


def complexity_for(signal_type: str, error_code_complexity: str | None, flags: list[str]) -> str:
    c = error_code_complexity or TYPE_COMPLEXITY.get(signal_type, "medium")
    if "mass_impact" in flags and c == "easy":
        c = "medium"
    return c if c in ("instant", "easy", "medium", "hard") else "medium"


def pick_gift(crit: str, segment: str | None, flags: list[str]) -> dict[str, Any] | None:
    """ТЗ 8.5: делегат в gifts.choose без психотипа (совместимость T-061)."""
    chosen = giftmod.choose(segment, crit, flags, psychotype=None)
    if not chosen:
        return None
    return {k: chosen[k] for k in ("gift_code", "points", "privilege_code") if k in chosen}
