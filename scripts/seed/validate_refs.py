#!/usr/bin/env python3
"""Проверка ссылочной целостности data/* (T-236 product_lines и смежные справочники)."""

from __future__ import annotations

import csv
import json
import re
import sys
from pathlib import Path

import structlog
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


def validate_error_routing() -> list[str]:
    """T-014: каждый код ведёт к владельцу системы, а fallback остаётся у CX."""
    errors: list[str] = []
    catalogs = _load_yaml("error_codes.yaml")
    codes = catalogs.get("error_codes", [])
    teams = _load_yaml("teams.yaml")["teams"]
    system_codes = {row["code"] for row in _load_yaml("systems.yaml")["systems"]}
    team_codes = {row["code"] for row in teams}
    products = _product_codes()
    common = json.loads((ROOT / "contracts/events/common.schema.json").read_text(encoding="utf-8"))["$defs"]
    rules = _load_yaml("sla.yaml")["routing_rules"]
    if len(codes) < 25:
        errors.append(f"error_codes: ожидалось ≥ 25 кодов, получено {len(codes)}")
    names = [row["code"] for row in codes]
    if len(names) != len(set(names)):
        errors.append("error_codes: повторяющиеся коды")
    if len(rules) < 15:
        errors.append("routing_rules: ожидалось ≥ 15 правил")
    for row in codes:
        code, system = row["code"], row.get("system")
        if re.fullmatch(common["error_code"]["pattern"], code) is None:
            errors.append(f"{code}: код не соответствует contracts/events/common.schema.json error_code")
        if system not in system_codes:
            errors.append(f"{code}: неизвестная система {system}")
        if row.get("product") is not None and row["product"] not in products:
            errors.append(f"{code}: неизвестный продукт {row['product']}")
        for field in ("complexity", "criticality"):
            if row.get(field) not in common[field]["enum"]:
                errors.append(f"{code}: неизвестное значение {field}")
        owners = {team["code"] for team in teams if system in team["systems"]}
        explicit = [rule for rule in rules if rule.get("match") == {"error_code": code}]
        if not explicit or not any(owners.intersection(rule["team_codes"]) for rule in explicit):
            errors.append(f"{code}: нет явного маршрута владельцу системы {system}")
    for rule in rules:
        if not rule.get("team_codes") or not set(rule["team_codes"]) <= team_codes:
            errors.append(f"routing_rules {rule.get('priority')}: неизвестная или пустая команда")
        code = rule.get("match", {}).get("error_code")
        if code is not None and code not in names:
            errors.append(f"routing_rules: неизвестный код ошибки {code}")
    fallback = [row for row in rules if row.get("match") == {}]
    if len(fallback) != 1 or fallback[0].get("team_codes") != ["team_cx"]:
        errors.append("routing_rules: единственный маршрут по умолчанию должен вести в team_cx")
    elif fallback[0]["priority"] < max(rule["priority"] for rule in rules):
        errors.append("routing_rules: маршрут по умолчанию перекрывает более поздние правила")
    types = catalogs.get("signal_types", [])
    if {row["code"] for row in types} != set(common["signal_type"]["enum"]):
        errors.append("signal_types: набор не совпадает с контрактом")
    for row in types:
        if row.get("base_criticality") not in common["criticality"]["enum"]:
            errors.append(f"{row['code']}: некорректная base_criticality")
        for field in ("requires_hitl", "creates_incident"):
            if type(row.get(field)) is not bool:
                errors.append(f"{row['code']}: {field} должен быть bool")
    return errors


def main() -> int:
    errors = validate_product_lines() + validate_error_routing()
    log = structlog.get_logger("validate_refs")
    if errors:
        log.error("reference_validation_failed", errors=errors)
        return 1
    log.info("validate_refs_ok")
    return 0


if __name__ == "__main__":
    sys.exit(main())
