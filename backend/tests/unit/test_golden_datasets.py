"""T-021: строгая JSONL validation и отсутствие спорных меток в accuracy."""

from __future__ import annotations

import copy
import json

import pytest

from app.bench import datasets, runner
from app.bench.metrics import aggregate
from app.llm.base import LLMProfile
from app.llm.failover import ProviderChain
from app.llm.mock import MockProvider


def test_canonical_pair_is_full_balanced_and_exact_subset():
    assert datasets.check_canonical() == {"golden_v1": 200, "lite_v1": 40}
    assert runner.dataset_path("lite_v1").parent == datasets.GOLDEN_DIR
    cases = runner.load_dataset("golden_v1")
    assert len(cases) == 200 and all(set(case.gold) == set(datasets.GOLD_FIELDS) for case in cases)
    assert all(case.gold["system"] != "core" for case in cases)


@pytest.mark.parametrize(
    "mutation", ["missing", "system", "bool", "flags", "tags", "channel", "segment", "rationale", "id"]
)
def test_invalid_full_gold_is_rejected(tmp_path, mutation):
    row = copy.deepcopy(datasets.load_rows("golden_v1")[0])
    if mutation == "missing":
        del row["gold"]["complexity"]
    elif mutation == "system":
        row["gold"]["system"] = "core"
    elif mutation == "bool":
        row["gold"]["needs_hitl"] = 1
    elif mutation == "flags":
        row["gold"]["flags"] = [{}]
    elif mutation == "tags":
        row["tags"] = ["plain", "plain"]
    elif mutation == "channel":
        row["channel"] = "invalid"
    elif mutation == "segment":
        row["segment"] = "invalid"
    elif mutation == "rationale":
        row["annotation"] = {}
    else:
        row["id"] = ""
    path = tmp_path / "invalid.jsonl"
    path.write_text(json.dumps(row))
    with pytest.raises(ValueError):
        datasets.read_rows(path, complete_gold=True)


@pytest.mark.parametrize("text", ["{", '{"a":1,"a":2}', '{"x":NaN}', "", "[]"])
def test_bad_json_is_explicit_error_without_echoing_payload(tmp_path, text):
    path = tmp_path / "bad.jsonl"
    path.write_text(text)
    with pytest.raises(ValueError):
        datasets.read_rows(path, complete_gold=True)


def test_duplicate_ids_and_non_subset_fail(tmp_path):
    rows = datasets.load_rows("golden_v1")
    path = tmp_path / "duplicate.jsonl"
    path.write_text("\n".join(json.dumps(rows[0]) for _ in range(2)))
    with pytest.raises(ValueError, match="id"):
        datasets.read_rows(path, complete_gold=True)
    lite = copy.deepcopy(datasets.load_rows("lite_v1"))
    lite[0]["gold"]["needs_hitl"] = not lite[0]["gold"]["needs_hitl"]
    with pytest.raises(ValueError, match="подмножеством"):
        datasets.validate_pair(rows, lite)


@pytest.mark.parametrize("code", ["../secret", "/tmp/secret", ".", ".."])
def test_dataset_path_cannot_escape_corpus(code):
    with pytest.raises(ValueError):
        datasets.dataset_path(code)


def test_other_legacy_bench_still_accepts_partial_gold(tmp_path):
    path = tmp_path / "legacy.jsonl"
    path.write_text(json.dumps({"text": "Пример", "channel": "chat", "gold": {"signal_type": "info_request"}}))
    assert datasets.read_rows(path)[0]["gold"] == {"signal_type": "info_request"}


def test_ambiguous_is_excluded_from_accuracy_and_critical_recall_only():
    ordinary = {
        "case_id": 1,
        "gold": {"signal_type": "tech_fault", "criticality": "high"},
        "predicted": {"criticality": "high"},
        "correct": {"signal_type": True},
        "latency_ms": 10,
        "tool_ok": True,
        "json_valid_first_try": True,
    }
    ambiguous = {
        **ordinary,
        "case_id": 2,
        "tags": ["ambiguous"],
        "predicted": {"criticality": "low"},
        "correct": {"signal_type": False},
        "latency_ms": 20,
    }
    metrics = aggregate([ordinary, ambiguous])
    assert metrics["accuracy_type"] == metrics["recall_critical"] == 1
    assert metrics["requests_total"] == 2 and metrics["p95_ms"] > 10
    only = aggregate([ambiguous])
    assert "accuracy_type" not in only and "recall_critical" not in only
    assert only["json_valid_rate"] == 1


async def test_file_runner_preserves_ambiguous_tags_in_result_and_export():
    case = runner.load_dataset("lite_v1")[0]
    case.tags = [*case.tags, "ambiguous"]
    profile = LLMProfile(code="mock", provider="mock", model="mock-rules-v1", temperature=0)
    record = await runner.run(
        "lite_v1", profile, cases=[case], chain=ProviderChain([MockProvider()], append_mock=False)
    )
    assert record.status == "done"
    assert record.results[0]["correct"] == {}
    assert "accuracy_type" not in record.metrics
    exported = json.loads(runner.export_run(record.id, "json"))
    assert "ambiguous" in exported["results"][0]["tags"]
    assert "tags" in runner.export_run(record.id, "csv").splitlines()[0]


def test_independent_review_is_exact_current_case_level():
    reviewed = datasets.validate_review()
    assert reviewed["cases"] == 200
    assert reviewed["raw_case_agreement_pct"] == 98.5


def test_reference_policy_context_and_current_routing_match_all_gold():
    import re
    from types import SimpleNamespace

    import yaml

    from app.agent.nodes import route_team
    from app.agent.policies import PolicyContext, needs_human

    rules = yaml.safe_load((datasets.ROOT / "data/sla.yaml").read_text())["routing_rules"]
    teams = yaml.safe_load((datasets.ROOT / "data/teams.yaml").read_text())["teams"]
    deps = SimpleNamespace(
        teams=[team["code"] for team in teams],
        routing_rules=[
            (i, rule["match"], rule["team_codes"])
            for i, rule in enumerate(sorted(rules, key=lambda rule: rule["priority"]))
        ],
    )
    for row in datasets.load_rows("golden_v1"):
        classification = {**row["gold"], "confidence": row["annotation"]["policy_context"]["confidence"]}
        if row["annotation"].get("error_code"):
            classification["error_code"] = row["annotation"]["error_code"]
            assert classification["error_code"] in row["text"]
        if classification["signal_type"] == "fraud_suspicion":
            classification["entities"] = {"amount_rub": int(re.search(r"\d{5,6}", row["text"])[0])}
        primary, _, _ = route_team(classification, {"signal": {"channel": row["channel"]}}, deps)
        assert primary == row["gold"]["team"], row["id"]
        assert (
            bool(needs_human(classification, PolicyContext(segment=row["segment"], repeat_count=1)))
            == row["gold"]["needs_hitl"]
        ), row["id"]


@pytest.mark.parametrize("mutation", ["inflate", "missing", "unresolved", "provenance", "threshold"])
def test_review_gate_rejects_incomplete_or_inflated_report(tmp_path, monkeypatch, mutation):
    report = json.loads((datasets.ROOT / "docs/reviews/T-021-independent-review.json").read_text())
    if mutation == "inflate":
        report["case_agreement_pct"] = 100
    elif mutation == "missing":
        report["decisions"].pop()
    elif mutation == "unresolved":
        report["follow_up"]["all_known_findings_resolved"] = False
    elif mutation == "provenance":
        report["provenance_follow_up"]["approved"] = False
    else:
        report["required_agreement_pct"] = 90
    path = tmp_path / "review.json"
    path.write_text(json.dumps(report))
    monkeypatch.setattr(datasets, "REVIEW_FILE", path)
    with pytest.raises(ValueError):
        datasets.validate_review()


@pytest.mark.parametrize("option", ["--plan", "--apply"])
def test_operator_cli_never_uses_implicit_database_defaults(option):
    import os
    import subprocess
    import sys

    completed = subprocess.run(
        [sys.executable, str(datasets.ROOT / "scripts/seed/bench.py"), option],
        env={"PATH": os.defpath, "APP_ENV": "test", "LLM_PROVIDER": "mock"},
        capture_output=True,
        text=True,
        timeout=30,
        check=False,
    )
    assert completed.returncode != 0
    assert ("DATABASE_URL" if option == "--plan" else "--plan-sha") in completed.stderr


def test_ambiguous_lite_cannot_be_used_as_gate():
    golden = copy.deepcopy(datasets.load_rows("golden_v1"))
    lite = copy.deepcopy(datasets.load_rows("lite_v1"))
    lite[0]["tags"].append("ambiguous")
    next(row for row in golden if row["id"] == lite[0]["id"])["tags"].append("ambiguous")
    with pytest.raises(ValueError, match="ambiguous"):
        datasets.validate_pair(golden, lite)


def test_review_gate_works_with_deployed_data_without_docs(tmp_path, monkeypatch):
    import shutil

    golden = tmp_path / "data/golden"
    bench = tmp_path / "data/bench"
    common = tmp_path / "contracts/events"
    for directory in (golden, bench, common):
        directory.mkdir(parents=True)
    for name in ("golden_v1.jsonl", "lite_v1.jsonl", "manifest_v1.json", "review_v1.json"):
        shutil.copy2(datasets.GOLDEN_DIR / name, golden / name)
    for name in ("golden_v1.jsonl", "lite_v1.jsonl"):
        shutil.copy2(datasets.BENCH_DIR / name, bench / name)
    shutil.copy2(datasets.ROOT / "contracts/events/common.schema.json", common / "common.schema.json")
    monkeypatch.setattr(datasets, "ROOT", tmp_path)
    monkeypatch.setattr(datasets, "GOLDEN_DIR", golden)
    monkeypatch.setattr(datasets, "BENCH_DIR", bench)
    monkeypatch.setattr(datasets, "REVIEW_FILE", golden / "review_v1.json")
    assert not (tmp_path / "docs").exists()
    assert datasets.check_canonical() == {"golden_v1": 200, "lite_v1": 40}
    assert datasets.validate_review()["raw_case_agreement_pct"] == 98.5
