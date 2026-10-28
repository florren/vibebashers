"""Регрессии фонового сервиса: лимиты, очистка задач и безопасные ошибки."""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from unittest.mock import AsyncMock

import pytest

from app.bench import runner
from app.bench.metrics import aggregate
from app.bench.service import BenchRateLimiter, BenchService
from app.llm.base import LLMProfile, ProviderError
from app.llm.failover import ProviderChain
from app.llm.keys import ApiKey
from app.llm.mock import MockProvider
from app.llm.ratelimit import RateLimiter


def test_database_decimal_profile_and_invalid_tool_metric() -> None:
    profile = BenchService.profile(
        {
            "code": "priced",
            "provider": "mock",
            "model": "mock",
            "temperature": Decimal("0.1"),
            "price_in_per_1m": Decimal("100"),
            "price_out_per_1m": Decimal("200"),
        }
    )
    assert profile.cost(1000, 1000) == pytest.approx(0.3)
    metrics = aggregate([{"case_id": 1, "latency_ms": 1, "predicted": {"unexpected": True}, "tool_ok": False}])
    assert metrics["tool_success_rate"] == 0


@pytest.mark.asyncio
async def test_rpm_wait_uses_shared_limiter_and_daily_limit_fails(monkeypatch) -> None:
    from app.bench import service

    acquire = AsyncMock(side_effect=[ProviderError("rate_limit", retry_after_s=30), None])
    sleep = AsyncMock()
    monkeypatch.setattr(service.limiter, "acquire", acquire)
    monkeypatch.setattr(service.asyncio, "sleep", sleep)
    await BenchRateLimiter().acquire("slow", 2, 100)
    assert acquire.await_count == 2
    sleep.assert_awaited_once_with(30)
    acquire.side_effect = ProviderError("rate_limit", retry_after_s=3600)
    with pytest.raises(ProviderError):
        await BenchRateLimiter().acquire("slow", 2, 100)


def test_forecast_daily_counter_resets_at_utc_day_boundary() -> None:
    limiter = RateLimiter()
    limiter.configure("yesterday", 10, 100)
    limiter._b["yesterday"].today = 100
    limiter._b["yesterday"].day = datetime.now(UTC).date() - timedelta(days=1)
    assert limiter.stats()["yesterday"]["today"] == 0


@pytest.mark.asyncio
async def test_cancel_before_task_starts_cleans_registry() -> None:
    service = BenchService()
    task = asyncio.create_task(asyncio.sleep(100))
    record = runner.BenchRunRecord(1, "lite_v1", "mock", "v1", 42, 1, "queued")
    service.tasks[1] = task
    service.records[1] = record
    task.add_done_callback(lambda task: service.finished(1, task))
    task.cancel()
    await asyncio.gather(task, return_exceptions=True)
    assert service.tasks == {} and service.records == {}


@pytest.mark.asyncio
async def test_error_does_not_expose_provider_secret() -> None:
    class Broken(MockProvider):
        name = "synthetic"

        async def complete_structured(self, *args, **kwargs):
            raise ProviderError("auth", "secret-must-stay-private")

    record = await runner.run(
        "lite_v1",
        LLMProfile(code="mock", provider="mock", model="mock"),
        cases=runner.load_dataset("lite_v1")[:1],
        chain=ProviderChain([Broken()], append_mock=False),
    )
    assert record.status == "failed"
    assert record.results == []
    assert "secret-must-stay-private" not in record.error


def test_remaining_counts_cached_usage_and_unlimited_keys() -> None:
    service = BenchService()
    service.keys["used"] = ApiKey("used", "synthetic", tokens_limit=100, tokens_used=90)
    assert service.remaining([{"label": "used", "tokens_limit": 100, "tokens_used": 10}]) == 10
    assert service.remaining([{"label": "unlimited", "tokens_limit": None}]) is None
