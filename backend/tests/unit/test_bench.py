"""T-129: бенчмарк-раннер и метрики без PostgreSQL и сети."""

from __future__ import annotations

import asyncio
import json
import time

import pytest

import app.bench
from app.bench.metrics import aggregate
from app.bench.runner import (
    FailOnceProvider,
    build_classify_prompt,
    export_run,
    forecast,
    load_dataset,
    run,
)
from app.llm.base import LLMProfile
from app.llm.failover import ProviderChain


def test_import_package() -> None:
    assert hasattr(app.bench, "run")
    assert hasattr(app.bench, "forecast")


def test_lite_v1_dataset() -> None:
    cases = load_dataset("lite_v1")
    assert 30 <= len(cases) <= 40
    for c in cases:
        assert c.text and c.channel
        assert "signal_type" in c.gold and "product" in c.gold
        assert set(c.gold.keys()) <= {"signal_type", "product", "system"}


def test_aggregate_deterministic_and_stability_rules() -> None:
    base = {
        "case_id": 1,
        "gold": {"signal_type": "tech_fault", "product": "deposit", "system": "mobile_app"},
        "predicted": {
            "signal_type": "tech_fault",
            "product": "deposit",
            "system": "mobile_app",
            "criticality": "medium",
            "problem_summary": {"suggested_team": "team_cx"},
        },
        "correct": {"signal_type": True, "product": True, "system": True},
        "latency_ms": 10,
        "json_valid_first_try": True,
        "retries": 0,
        "prompt_tokens": 100,
        "completion_tokens": 50,
        "fallback_mock": False,
        "cost_rub": 0.0,
    }
    m1 = aggregate([base], repeats=1)
    m2 = aggregate([base], repeats=1)
    assert m1 == m2
    assert m1["stability"] is None
    assert "recall_critical" not in m1

    high_gold = {**base, "gold": {**base["gold"], "criticality": "high"}}
    m_high = aggregate([high_gold], repeats=1)
    assert "recall_critical" in m_high

    stable = [
        {**base, "case_id": 2, "repeat_no": 1},
        {**base, "case_id": 2, "repeat_no": 2, "predicted": {**base["predicted"]}},
    ]
    m_stable = aggregate(stable, repeats=2)
    assert m_stable["stability"] == 1.0

    unstable = [
        {**base, "case_id": 3, "repeat_no": 1},
        {
            **base,
            "case_id": 3,
            "repeat_no": 2,
            "predicted": {**base["predicted"], "signal_type": "client_error"},
        },
    ]
    m_unstable = aggregate(unstable, repeats=2)
    assert m_unstable["stability"] == 0.0


@pytest.mark.asyncio
async def test_mock_run_reproducible_and_fast() -> None:
    profile = LLMProfile(code="mock", provider="mock", model="mock-rules-v1", temperature=0.0)
    t0 = time.perf_counter()
    r1 = await run("lite_v1", profile, repeats=1)
    r2 = await run("lite_v1", profile, repeats=1)
    elapsed = time.perf_counter() - t0
    assert elapsed <= 30.0
    assert r1.status == "done" and r2.status == "done"
    assert r1.metrics == r2.metrics
    assert r1.metrics is not None
    for key in (
        "accuracy_type",
        "accuracy_product",
        "accuracy_system",
        "json_valid_rate",
        "p50_ms",
        "p95_ms",
        "tokens_total",
    ):
        assert key in r1.metrics


def test_forecast_blocks_run_without_llm_calls() -> None:
    profile = LLMProfile(
        code="tight",
        provider="openai_compatible",
        model="x",
        temperature=0.0,
        rpd_limit=1,
    )
    fc = forecast("lite_v1", profile, repeats=1)
    assert fc.fits_limits is False
    assert fc.warning
    assert "rpd_limit" in fc.warning


def test_forecast_blocks_on_key_tokens_remaining() -> None:
    cases_n = len(load_dataset("lite_v1"))
    profile = LLMProfile(
        code="open",
        provider="openai_compatible",
        model="x",
        temperature=0.0,
        rpd_limit=cases_n + 100,
    )
    fc = forecast("lite_v1", profile, repeats=1, key_tokens_remaining=1)
    assert fc.fits_limits is False
    assert "остаток ключа" in fc.warning


@pytest.mark.asyncio
async def test_forecast_blocked_run_has_no_results() -> None:
    profile = LLMProfile(code="tight", provider="mock", model="mock", rpd_limit=2)
    record = await run("lite_v1", profile, repeats=1)
    assert record.status == "failed"
    assert record.results == []


@pytest.mark.asyncio
async def test_key_tokens_blocked_run_has_no_provider_calls() -> None:
    cases_n = len(load_dataset("lite_v1"))
    profile = LLMProfile(
        code="open",
        provider="openai_compatible",
        model="x",
        temperature=0.0,
        rpd_limit=cases_n + 100,
    )
    spy = FailOnceProvider()
    chain = ProviderChain([spy])
    record = await run(
        "lite_v1",
        profile,
        repeats=1,
        chain=chain,
        key_tokens_remaining=1,
    )
    assert record.status == "failed"
    assert record.results == []
    assert spy.calls == 0


@pytest.mark.asyncio
async def test_cancelled_status() -> None:
    profile = LLMProfile(code="mock", provider="mock", model="mock-rules-v1", temperature=0.0)
    cases = load_dataset("lite_v1")[:3]

    import app.bench.runner as runner_mod

    original_load = runner_mod.load_dataset
    original_invoke = runner_mod._invoke_classify

    async def slow_invoke(chain, case, prof, schema):  # type: ignore[no-untyped-def]
        await asyncio.sleep(0.02)
        return await original_invoke(chain, case, prof, schema)

    runner_mod.load_dataset = lambda code: cases  # type: ignore[assignment]
    runner_mod._invoke_classify = slow_invoke  # type: ignore[method-assign]

    try:
        task = asyncio.create_task(run("lite_v1", profile, repeats=1))
        cancelled = False
        for _ in range(200):
            await asyncio.sleep(0.005)
            for rec in runner_mod._RUNS.values():
                if rec.status == "running" and rec.results:
                    rec.request_cancel()
                    cancelled = True
                    break
            if cancelled:
                break
        record = await task
    finally:
        runner_mod.load_dataset = original_load  # type: ignore[assignment]
        runner_mod._invoke_classify = original_invoke  # type: ignore[method-assign]

    assert cancelled
    assert record.status == "cancelled"


@pytest.mark.asyncio
async def test_export_csv_and_json() -> None:
    profile = LLMProfile(code="mock", provider="mock", model="mock-rules-v1", temperature=0.0)
    record = await run("lite_v1", profile, repeats=1)
    csv_body = export_run(record.id, "csv")
    json_body = export_run(record.id, "json")
    assert "case_id" in csv_body and "latency_ms" in csv_body
    parsed = json.loads(json_body)
    assert parsed["run"]["id"] == record.id
    assert len(parsed["results"]) == len(record.results)


@pytest.mark.asyncio
async def test_fail_once_increases_retries_and_fallback() -> None:
    profile = LLMProfile(code="mock", provider="mock", model="mock-rules-v1", temperature=0.0)
    chain = ProviderChain([FailOnceProvider()])
    cases = load_dataset("lite_v1")[:1]
    import app.bench.runner as runner_mod

    original = runner_mod.load_dataset
    runner_mod.load_dataset = lambda code: cases  # type: ignore[assignment]
    record = await run("lite_v1", profile, repeats=1, chain=chain)
    runner_mod.load_dataset = original  # type: ignore[assignment]
    assert record.status == "done"
    row = record.results[0]
    assert row["retries"] >= 1
    assert row["fallback_mock"] is True


def test_prompt_builds_without_placeholders() -> None:
    case = load_dataset("lite_v1")[0]
    body = build_classify_prompt(case)
    assert "{{" not in body
    assert case.text in body
