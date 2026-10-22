"""Чистые функции экономики dCLTV (ТЗ 14.4): выбор ставки, формула, класс исхода."""

from __future__ import annotations

import datetime as dt

from app.economics.dcltv import Rate, compute, outcome_of, pick_rate

RATES = [
    {"code": "premium_service", "rate_rub": 91.53, "maps_to": {"segments": ["premium", "vip"], "addon": True}},
    {
        "code": "debit_card_premium",
        "rate_rub": 961.0,
        "maps_to": {"products": ["debit_card"], "segments": ["premium", "vip"]},
    },
    {"code": "debit_card", "rate_rub": 458.46, "maps_to": {"products": ["debit_card"]}},
    {"code": "processing", "rate_rub": 300.0, "maps_to": {"systems": ["processing"], "op_types": ["card_payment"]}},
    {"code": "processing_any", "rate_rub": 200.0, "maps_to": {"systems": ["processing"]}},
    {"code": "social_channel", "rate_rub": 100.0, "maps_to": {"channels": ["social"]}},
    {"code": "bank_average", "rate_rub": 4050.0, "maps_to": {"fallback": True}},
]


def test_pick_rate_priority() -> None:
    assert (
        pick_rate(RATES, product="debit_card", system=None, channel=None, segment="premium").code
        == "debit_card_premium"
    )
    assert pick_rate(RATES, product="debit_card", system=None, channel=None, segment="mass").code == "debit_card"
    assert (
        pick_rate(RATES, product=None, system="processing", channel=None, segment=None, op_type="card_payment").code
        == "processing"
    )
    assert pick_rate(RATES, product=None, system="processing", channel=None, segment=None).code == "processing_any"
    assert pick_rate(RATES, product=None, system=None, channel="social", segment=None).code == "social_channel"
    assert pick_rate(RATES, product=None, system=None, channel=None, segment=None).code == "bank_average"


def test_compute_matches_tz_example() -> None:
    """Пример ТЗ 14.4: 12 × 10 % × 50 % × (961 + 91,53) = 631,52 ₽."""
    res = compute(
        affected=12,
        detractor_share=0.1,
        no_return_share=0.5,
        rate=Rate("debit_card_premium", 961.0, "продукт"),
        premium_addon=91.53,
        retention_factor=0.8,
        outcome_class="closed_in_sla",
    )
    assert res["potential_loss_rub"] == 631.52
    assert res["prevented_loss_rub"] == 505.22 and res["realized_loss_rub"] == 0.0
    assert res["formula_ru"].startswith("12 × 10 % × 50 % × (961 + 91,53) = 631,52")


def test_compute_churned_realizes_loss_and_refund_reduces_effect() -> None:
    res = compute(
        affected=1,
        detractor_share=1.0,
        no_return_share=1.0,
        rate=Rate("x", 1000.0, ""),
        premium_addon=0,
        retention_factor=0.9,
        outcome_class="churned",
        refund_rub=450,
    )
    assert res["realized_loss_rub"] == 1000.0 and res["prevented_loss_rub"] == 0.0
    assert res["net_effect_rub"] == -450.0


def test_outcome_of() -> None:
    t0 = dt.datetime(2026, 1, 1, tzinfo=dt.UTC)
    base = {
        "status": "resolved",
        "sla_due_sim": t0 + dt.timedelta(hours=4),
        "resolved_sim": t0 + dt.timedelta(hours=1),
        "closed_sim": None,
        "sla_breached": False,
    }
    assert outcome_of(base, gift_given=False, regression=False, churned=False) == "closed_in_sla"
    assert outcome_of(base, gift_given=True, regression=False, churned=False) == "closed_in_sla_with_gift"
    assert (
        outcome_of(
            {**base, "resolved_sim": t0 + dt.timedelta(hours=9)}, gift_given=False, regression=False, churned=False
        )
        == "closed_late"
    )
    assert outcome_of(base, gift_given=False, regression=True, churned=False) == "closed_with_regression"
    assert outcome_of({**base, "status": "in_progress"}, gift_given=False, regression=False, churned=False) == "open"
    assert outcome_of({**base, "status": "rejected"}, gift_given=False, regression=False, churned=False) == "rejected"
    assert outcome_of(base, gift_given=False, regression=False, churned=True) == "churned"
