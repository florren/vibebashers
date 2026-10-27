#!/usr/bin/env python3
"""Проверка ссылочной целостности data/* (T-236 product_lines и смежные справочники)."""
from __future__ import annotations

import csv
import re
import sys
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[2]
DATA = ROOT / "data"

FORBIDDEN_BANK = re.compile(
    r"(сбер|сбербанк|тинькофф|tinkoff|альфа[- ]?банк|втб|газпромбанк)",
    re.IGNORECASE,
)

EXPECTED_FALLBACK = {"business_banking", "fraud_security"}
EXPECTED_SHARES = [9, 3, 5, 1, 4, 2, 6, 2, 8, 3, 3, 2, 3, 1, 2]


def _load_yaml(name: str) -> dict:
    return yaml.safe_load((DATA / name).read_text(encoding="utf-8")) or {}


def _rate_codes() -> set[str]:
    with (DATA / "dcltv_rates.csv").open(encoding="utf-8") as f:
        return {row["code"] for row in csv.DictReader(f)}


def _team_codes() -> set[str]:
    return {t["code"] for t in _load_yaml("teams.yaml")["teams"]}


def _product_codes() -> set[str]:
    return {p["code"] for p in _load_yaml("products.yaml")["products"]}


def validate_product_lines() -> list[str]:
    errors: list[str] = []
    doc = _load_yaml("product_lines.yaml")
    lines = doc.get("product_lines") or []
    if len(lines) != 15:
        errors.append(f"product_lines: ожидалось 15 строк, получено {len(lines)}")
    rates, teams, products = _rate_codes(), _team_codes(), _product_codes()
    orders: list[int] = []
    share_sum = 0
    for row in lines:
        code = row.get("code", "")
        for field in ("name_ru", "name_en"):
            text = str(row.get(field, ""))
            if FORBIDDEN_BANK.search(text):
                errors.append(f"{code}.{field}: запрещённый бренд банка")
        rate = row.get("rate_code")
        if rate not in rates:
            errors.append(f"{code}: неизвестный rate_code {rate}")
        team = row.get("owner_team_code")
        if team not in teams:
            errors.append(f"{code}: неизвестный owner_team_code {team}")
        for pc in row.get("product_codes") or []:
            if pc not in products:
                errors.append(f"{code}: неизвестный product {pc}")
        orders.append(int(row.get("sort_order", -1)))
        share_sum += int(row.get("demo_review_share", 0))
        if code in EXPECTED_FALLBACK and not row.get("rate_is_fallback"):
            errors.append(f"{code}: rate_is_fallback должен быть true")
        if code not in EXPECTED_FALLBACK and row.get("rate_is_fallback"):
            errors.append(f"{code}: rate_is_fallback должен быть false")
    if sorted(orders) != list(range(1, 16)):
        errors.append(f"product_lines: sort_order должен быть 1…15 уникально, got {sorted(orders)}")
    if share_sum != 54:
        errors.append(f"product_lines: сумма demo_review_share = {share_sum}, ожидалось 54")
    codes = [row["code"] for row in lines]
    if codes != sorted(codes, key=lambda c: next(r["sort_order"] for r in lines if r["code"] == c)):
        pass  # order in file follows TZ table, not sort_order sort
    return errors


def main() -> int:
    errors = validate_product_lines()
    if errors:
        print("\n".join(errors))
        return 1
    print("validate_refs: ok")
    return 0


if __name__ == "__main__":
    sys.exit(main())
