"""T-236: справочник product_lines.yaml соответствует ТЗ 24.2."""

from __future__ import annotations

from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[3]

TZ_ROWS = [
    ("deposits", "deposit", "team_deposits", False, ["deposit"], 9),
    ("mortgage", "mortgage", "team_lending", False, ["credit"], 3),
    ("loans", "consumer_loan", "team_lending", False, ["credit"], 5),
    ("credit_cards", "credit_card", "team_lending", False, ["credit_card"], 1),
    ("debit_cards", "debit_card", "team_debit", False, ["debit_card"], 4),
    ("transfers_payments", "transfers", "team_processing", False, ["debit_card"], 2),
    ("mobile_app", "mobile_app", "team_front", False, [], 6),
    ("investments", "brokerage", "team_cx", True, [], 2),
    ("insurance", "insurance", "team_cx", True, ["credit"], 8),
    ("bonuses_subscription", "subscription", "team_promo", False, [], 3),
    ("branches_service", "branches", "team_branch_network", False, [], 3),
    ("support", "support_chat", "team_contact_center", False, [], 2),
    ("business_banking", "bank_average", "team_processing", True, [], 3),
    ("atm_self_service", "atm", "team_processing", True, ["debit_card"], 1),
    ("fraud_security", "bank_average", "team_antifraud", False, [], 2),
]


def test_product_lines_matches_tz_table() -> None:
    doc = yaml.safe_load((ROOT / "data/product_lines.yaml").read_text(encoding="utf-8"))
    by_code = {r["code"]: r for r in doc["product_lines"]}
    assert len(by_code) == 15
    for code, rate, team, proxy, products, share in TZ_ROWS:
        row = by_code[code]
        assert row["rate_code"] == rate
        assert row["owner_team_code"] == team
        assert row["owner_is_proxy"] is proxy
        assert row["product_codes"] == products
        assert row["demo_review_share"] == share
        assert row["rate_is_fallback"] == (code in {"business_banking", "fraud_security"})
