"""T-174: p50/p95 сценария 8 на live GigaChat (маркер live, не в обязательном CI)."""

from __future__ import annotations

import os
import statistics
import time

import psycopg
import pytest

from app.agent.graph import process_signal
from app.llm.base import LLMProfile
from app.llm.failover import ProviderChain, build_chain
from app.sim import scenarios as sc
from tests.helpers import dsn, new_run, sim_now

pytestmark = [pytest.mark.integration, pytest.mark.live]


def _live_chain() -> ProviderChain | None:
    if not os.getenv("GIGACHAT_CREDENTIALS") and not os.getenv("GIGACHAT_CLIENT_ID"):
        return None
    from app.config import settings

    return build_chain(settings)


@pytest.mark.skipif(_live_chain() is None, reason="нет GIGACHAT_* — live-замер пропущен")
async def test_scenario_08_live_latency_p50_p95(seeded: str) -> None:
    scenario = sc.get("qr_fee_public_review")
    assert scenario is not None
    chain = _live_chain()
    assert chain is not None
    profile = LLMProfile(code="main", provider="gigachat", model="GigaChat-3-Pro", role="main")
    samples: list[float] = []
    for _ in range(10):
        t0 = time.perf_counter()
        async with await psycopg.AsyncConnection.connect(dsn(seeded)) as conn:
            run_id = await new_run(conn, "live qr_fee latency", scenario_id=scenario["id"])
            now = await sim_now(conn)
            injected = await sc.inject(conn, scenario, run_id, sim_time=now)
            await conn.commit()
            for item in injected:
                await process_signal(conn, signal_id=item["signal_id"], chain=chain, profile=profile, sim_time=now)
        samples.append(time.perf_counter() - t0)
    p50 = statistics.median(samples)
    p95 = sorted(samples)[int(len(samples) * 0.95) - 1]
    print(f"\nlive qr_fee: p50={p50:.1f}s p95={p95:.1f}s samples={[round(x, 1) for x in samples]}")  # noqa: T201
    assert p50 <= 10.0, f"p50 {p50:.1f}s > 10s"
    assert p95 <= 15.0, f"p95 {p95:.1f}s > 15s"
