"""T-014: маршруты всех ошибок, контракт типов и точная матрица SLA ТЗ §8.2."""

from __future__ import annotations

import importlib.util
from copy import deepcopy
from pathlib import Path
from types import SimpleNamespace

import pytest
import yaml

from app.agent.nodes import route_team

ROOT = Path(__file__).resolve().parents[3]
spec = importlib.util.spec_from_file_location("validate_refs", ROOT / "scripts/seed/validate_refs.py")
refs = importlib.util.module_from_spec(spec)
spec.loader.exec_module(refs)


def load(name):
    return yaml.safe_load((ROOT / "data" / name).read_text())


def test_catalogs_are_complete_and_consistent():
    assert refs.validate_error_routing() == []


@pytest.mark.parametrize("error", load("error_codes.yaml")["error_codes"], ids=lambda row: row["code"])
def test_each_error_routes_to_an_owner(error):
    teams = load("teams.yaml")["teams"]
    rules = sorted(load("sla.yaml")["routing_rules"], key=lambda row: row["priority"])
    deps = SimpleNamespace(
        teams=[row["code"] for row in teams],
        routing_rules=[(i, row["match"], row["team_codes"]) for i, row in enumerate(rules)],
    )
    classification = {
        "signal_type": "tech_fault",
        "error_code": error["code"],
        "system": error["system"],
        "product": error["product"],
    }
    primary, secondary, rule_id = route_team(classification, {"signal": {"channel": "chat"}}, deps)
    owners = {row["code"] for row in teams if error["system"] in row["systems"]}
    assert primary in owners or owners.intersection(secondary)
    assert rule_id is not None


def test_sla_matrix_matches_tz_working_days_and_reports():
    expected = {
        ("easy", "high"): (1, [], 2),
        ("easy", "medium"): (2, [], 4),
        ("easy", "low"): (3, [], 8),
        ("medium", "high"): (3, [], 2),
        ("medium", "medium"): (4, [], 4),
        ("medium", "low"): (5, [], 8),
        ("hard", "high"): (5, [], 2),
        ("hard", "medium"): (5, [3], 4),
        ("hard", "low"): (10, [3, 6, 9], 8),
    }
    rows = load("sla.yaml")["sla_matrix"]
    assert len(rows) == 9
    assert {
        (row["complexity"], row["criticality"]): (row["fix_days"], row["report_days"], row["take_hours"])
        for row in rows
    } == expected


@pytest.mark.parametrize(
    "mutation,match",
    [
        ("missing_route", "нет явного маршрута"),
        ("wrong_owner", "нет явного маршрута"),
        ("duplicate", "повторяющиеся"),
        ("unknown_system", "неизвестная система"),
        ("fallback", "маршрут по умолчанию"),
        ("signal_type", "набор не совпадает"),
        ("invalid_contract_code", "код не соответствует"),
    ],
)
def test_validator_rejects_broken_catalog(monkeypatch, mutation, match):
    docs = {
        name: deepcopy(load(name))
        for name in ("error_codes.yaml", "sla.yaml", "teams.yaml", "systems.yaml", "products.yaml")
    }
    errors = docs["error_codes.yaml"]["error_codes"]
    rules = docs["sla.yaml"]["routing_rules"]
    if mutation == "missing_route":
        rules[:] = [row for row in rules if row["match"] != {"error_code": errors[0]["code"]}]
    elif mutation == "wrong_owner":
        next(row for row in rules if row["match"] == {"error_code": errors[0]["code"]})["team_codes"] = [
            "team_compliance"
        ]
    elif mutation == "duplicate":
        errors.append(deepcopy(errors[0]))
    elif mutation == "unknown_system":
        errors[0]["system"] = "missing"
    elif mutation == "fallback":
        next(row for row in rules if row["match"] == {})["priority"] = 0
    elif mutation == "invalid_contract_code":
        old_code = errors[0]["code"]
        errors[0]["code"] = "ANTIFRAUDX-FALSE-BLOCK"
        for rule in rules:
            if rule["match"] == {"error_code": old_code}:
                rule["match"]["error_code"] = errors[0]["code"]
    else:
        docs["error_codes.yaml"]["signal_types"].pop()
    monkeypatch.setattr(refs, "_load_yaml", lambda name: docs[name])
    assert any(match in message for message in refs.validate_error_routing())


@pytest.mark.parametrize("error", load("error_codes.yaml")["error_codes"], ids=lambda row: row["code"])
def test_each_catalog_error_is_valid_in_real_fault_event(error):
    from app.contracts.registry import validate

    assert (
        validate(
            {
                "event_type": "fault.started",
                "fault_id": 1,
                "system": error["system"],
                "error_code": error["code"],
                "started_sim": "2026-11-09T09:00:00+03:00",
            },
            "sim/fault",
        )
        == []
    )


@pytest.mark.parametrize(
    "code", ["ANTIFRAUDX-FALSE-BLOCK", "antifraud-FALSE-BLOCK", "A-FALSE", "AF-X", "AF-ABCDEFGHIJKLM", "AF-AA-BB-CC-DD"]
)
def test_error_code_extension_keeps_other_constraints(code):
    from app.contracts.registry import validate

    errors = validate(
        {
            "event_type": "fault.started",
            "fault_id": 1,
            "system": "antifraud",
            "error_code": code,
            "started_sim": "2026-11-09T09:00:00+03:00",
        },
        "sim/fault",
    )
    assert len(errors) == 1 and errors[0].startswith("error_code:")
