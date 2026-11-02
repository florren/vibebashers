"""T-017: распределения, детерминизм и границы синтетической истории."""

from __future__ import annotations

import copy
import datetime as dt
import math
import random
from collections import Counter
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[3]


@pytest.fixture
def history(monkeypatch):
    monkeypatch.syspath_prepend(str(ROOT))
    from scripts.seed.common import load_yaml
    from scripts.seed.operations import load_config

    config = load_config()
    errors = [(row["code"], row["system"], row.get("product")) for row in load_yaml("error_codes.yaml")["error_codes"]]
    now = dt.datetime(2026, 11, 9, 9, tzinfo=dt.timezone(dt.timedelta(hours=3)))
    return config, errors, now


def generate(history, count=10000):
    from scripts.seed.operations import operation_rows

    config, errors, now = history
    return list(
        operation_rows(
            [(1, "mass", list(config["products"]))], random.Random(42), 8, now, config, errors, per_client=count
        )
    )


def test_history_deterministic_and_contract_boundaries(history):
    rows = generate(history, 1000)
    assert rows == generate(history, 1000)
    config, errors, now = history
    systems = set(sum(config["system_paths"].values(), []))
    for row in rows:
        assert row[0:2] == (8, 1)
        assert set(row[4]) <= systems
        assert now - dt.timedelta(days=14) <= row[11] <= row[12] <= now
        assert row[5] is None or 0 <= row[5] < 10**12
        if row[10] == "PROC-QR-FEE-CHARGED":
            assert row[6] == "qr_sbp" and row[8] > 0 and row[9] == "success"
        if row[9] == "failed":
            code, system, product = next(error for error in errors if error[0] == row[10])
            assert system in row[4]
            assert product in (None, row[2])


def test_hour_weekday_chi_squared_and_failure_rate(history):
    from scripts.seed.operations import history_slots

    config, _, now = history
    rows = generate(history, 60000)
    slots, cumulative = history_slots(now, config)
    weights = [b - a for a, b in zip([0] + cumulative[:-1], cumulative, strict=True)]
    for selector in (lambda timestamp: timestamp.hour, lambda timestamp: timestamp.weekday()):
        expected = Counter()
        observed = Counter(selector(row[11]) for row in rows)
        for timestamp, weight in zip(slots, weights, strict=True):
            expected[selector(timestamp)] += weight / sum(weights) * len(rows)
        chi = sum((observed[key] - value) ** 2 / value for key, value in expected.items())
        # Fixed seed, upper bound exceeds χ²(23) .999 and χ²(6) .999.
        assert chi < 60
    failed = sum(row[9] == "failed" for row in rows)
    assert abs(failed / len(rows) - 0.01) < 0.002
    qr = [row for row in rows if row[6] == "qr_sbp" and row[9] == "success"]
    assert 0.03 < sum(row[8] > 0 for row in qr) / len(qr) < 0.05


def test_amounts_are_continuous_lognormal(history):
    rows = generate(history, 20000)
    config, _, _ = history
    for product, values in config["products"].items():
        amounts = [row[5] for row in rows if row[2] == product and row[5] is not None]
        logs = [math.log(amount) for amount in amounts]
        mean = sum(logs) / len(logs)
        sigma = math.sqrt(sum((value - mean) ** 2 for value in logs) / len(logs))
        assert abs(mean - math.log(values["amount_median_rub"])) < 0.08
        assert abs(sigma - values["amount_sigma"]) < 0.08
        assert len(set(amounts)) > len(amounts) * 0.95


def test_segment_intensity_and_demo_volume(history):
    from scripts.seed.operations import operation_rows

    config, errors, now = history
    clients = [(i, "mass" if i < 50 else "vip", ["debit_card"]) for i in range(100)]
    counts = Counter(
        row[1] for row in operation_rows(clients, random.Random(42), 1, now, config, errors, profile="demo")
    )
    assert 11900 <= sum(counts.values()) <= 12100
    assert sum(counts[i] for i in range(50, 100)) > 1.6 * sum(counts[i] for i in range(50))
    assert 500000 <= sum(counts.values()) * 50 <= 700000


@pytest.mark.parametrize(
    "key,value",
    [
        ("hour_weights", [1]),
        ("weekday_weights", [0] * 7),
        ("failure_probability", 2),
        ("qr_share", -1),
        ("history_days", 13),
        ("segment_weights", {"mass": 0}),
        ("operations_per_client", {"demo": 0}),
    ],
)
def test_invalid_config_rejected(history, monkeypatch, key, value):
    from scripts.seed import operations

    config = copy.deepcopy(history[0])
    config[key] = value
    original = operations.load_yaml
    monkeypatch.setattr(operations, "load_yaml", lambda name: config if name == "op_paths.yaml" else original(name))
    with pytest.raises(ValueError):
        operations.load_config()


def test_invalid_path_rejected(history, monkeypatch):
    from scripts.seed import operations

    config = copy.deepcopy(history[0])
    config["system_paths"]["login"] = ["unknown"]
    original = operations.load_yaml
    monkeypatch.setattr(operations, "load_yaml", lambda name: config if name == "op_paths.yaml" else original(name))
    with pytest.raises(ValueError, match="invalid operation path"):
        operations.load_config()


def test_naive_time_and_missing_error_rejected(history):
    from scripts.seed.operations import history_slots, operation_rows

    config, _, now = history
    with pytest.raises(ValueError, match="timezone-aware"):
        history_slots(now.replace(tzinfo=None), config)
    config = copy.deepcopy(config)
    config["failure_probability"] = 1
    with pytest.raises(ValueError, match="no compatible error"):
        list(operation_rows([(1, "mass", ["debit_card"])], random.Random(42), 1, now, config, [], per_client=2))
    with pytest.raises(ValueError, match="no active products"):
        list(operation_rows([(1, "mass", [])], random.Random(42), 1, now, config, [], per_client=2))
    with pytest.raises(ValueError, match="positive"):
        list(operation_rows([], random.Random(42), 1, now, config, [], per_client=0))


def test_partial_hour_slots(history):
    from scripts.seed.operations import history_slots

    config, _, now = history
    now = now.replace(minute=37, second=8)
    slots, cumulative = history_slots(now, config)
    assert len(slots) == 337
    assert slots[0] == now - dt.timedelta(days=14)
    assert all(a < b for a, b in zip(cumulative, cumulative[1:], strict=False))


def test_recorded_history_context_is_not_rekeyed_or_reused_after_changes(history):
    import json

    from app.contracts.registry import deref
    from app.llm.base import LLMProfile, ProviderError
    from app.replay.provider import ReplayProvider
    from app.replay.store import CassetteStore

    fixture = json.loads((ROOT / "backend/tests/fixtures/replay_bank_v1.json").read_text())
    record = next(
        json.loads(line)
        for line in (ROOT / "data/cassettes/gigachat.jsonl").read_text().splitlines()
        if json.loads(line)["request_hash"] == fixture["source_request_hash"]
    )
    store = CassetteStore(ROOT / "data/cassettes")
    provider = ReplayProvider(store)
    profile = LLMProfile(code="recorded", provider=record["provider"], model=record["model"])
    schema = deref("agent/instant_decision")
    assert provider._find(record["messages"], schema, profile)["request_hash"] == fixture["source_request_hash"]
    changed = copy.deepcopy(record["messages"])
    changed[0]["content"] = changed[0]["content"].replace('"operation_ids":[2179]', '"operation_ids":[600001]')
    assert changed != record["messages"]
    with pytest.raises(ProviderError) as exc:
        provider._find(changed, schema, profile)
    assert exc.value.kind == "miss"
