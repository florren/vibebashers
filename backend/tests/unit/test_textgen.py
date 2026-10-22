"""B21: генератор текстов сигналов и справочные YAML — детерминизм, стили, Лун, консистентность кодов."""

from __future__ import annotations

import random
import sys
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT))

from scripts.seed.clients import luhn_invalid_last4  # noqa: E402
from scripts.seed.textgen import TextGen  # noqa: E402

DATA = ROOT / "data"


def test_textgen_deterministic_and_styled() -> None:
    a, b = TextGen(1), TextGen(1)
    for st, p in a.all_combinations():
        ga, gb = a.generate(st, p), b.generate(st, p)
        assert ga.text == gb.text and ga.gold == gb.gold
    g = TextGen(3).generate("tech_fault", "debit_card", style="sarcasm")
    assert g.gold["hidden_negativity"] is True and "sarcasm" in g.gold["flags"] and g.gold["sentiment"] == "negative"
    assert ".." not in g.text
    assert TextGen(3).generate("gratitude", "deposit", style="sarcasm").style == "plain"


def test_all_type_product_combos_have_templates() -> None:
    tg = TextGen(0)
    types = {t["code"] for t in yaml.safe_load((DATA / "error_codes.yaml").read_text(encoding="utf-8"))["signal_types"]}
    products = {p["code"] for p in yaml.safe_load((DATA / "products.yaml").read_text(encoding="utf-8"))["products"]}
    assert {(t, p) for t in types for p in products} == set(tg.all_combinations())


def test_luhn_invalid() -> None:
    rnd = random.Random(5)
    for _ in range(50):
        last4 = luhn_invalid_last4(rnd)
        assert len(last4) == 4 and last4.isdigit()


def test_reference_yaml_consistency() -> None:
    teams = yaml.safe_load((DATA / "teams.yaml").read_text(encoding="utf-8"))["teams"]
    systems = {s["code"] for s in yaml.safe_load((DATA / "systems.yaml").read_text(encoding="utf-8"))["systems"]}
    team_codes = {t["code"] for t in teams}
    for t in teams:
        assert set(t["systems"]) <= systems, t["code"]
    ec = yaml.safe_load((DATA / "error_codes.yaml").read_text(encoding="utf-8"))
    for e in ec["error_codes"]:
        assert (
            e["system"] in systems
            and e["complexity"] in ("easy", "medium", "hard")
            and e["criticality"] in ("high", "medium", "low")
        )
    sla = yaml.safe_load((DATA / "sla.yaml").read_text(encoding="utf-8"))
    assert {(r["complexity"], r["criticality"]): r["fix_days"] for r in sla["sla_matrix"]}[("hard", "low")] == 10
    for r in sla["routing_rules"]:
        assert set(r["team_codes"]) <= team_codes
    rules = yaml.safe_load((DATA / "rules.yaml").read_text(encoding="utf-8"))["business_rules"]
    assert any(r["code"] == "RULE-QR-FEE-001" and r["error_code"] == "PROC-QR-FEE-CHARGED" for r in rules)
    segs = yaml.safe_load((DATA / "segments.yaml").read_text(encoding="utf-8"))["segments"]
    assert abs(sum(s["population_share"] for s in segs) - 1.0) < 1e-9
