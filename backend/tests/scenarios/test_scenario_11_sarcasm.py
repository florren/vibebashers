"""T-220: сценарий 11 на mock-агенте. Кассета replay не подменяется mock-ответом."""

from __future__ import annotations

from pathlib import Path

import psycopg
import pytest

from app.agent.graph import process_signal
from app.llm.base import LLMProfile
from app.llm.failover import ProviderChain
from app.replay.provider import ReplayProvider
from app.replay.store import CassetteStore
from app.sim import scenarios as sc
from tests.helpers import MOCK_PROFILE, dsn, mock_chain, new_run, sim_now

CASSETTES = Path(__file__).resolve().parents[3] / "data" / "cassettes"
PROFILE = LLMProfile(code="gigachat_main", provider="gigachat", model="GigaChat-3-Pro", role="main")


async def test_scenario_11_social_sarcasm(seeded: str) -> None:
    scenario = sc.get("social_sarcasm_escalation")
    assert scenario is not None
    assert scenario["expected"]["sentiment"] == "negative"
    async with await psycopg.AsyncConnection.connect(dsn(seeded)) as conn:
        run_id = await new_run(conn, "test scenario 11", scenario_id=scenario["id"])
        now = await sim_now(conn)
        injected = await sc.inject(conn, scenario, run_id, sim_time=now)
        await conn.commit()
        for item in injected:
            state = await process_signal(
                conn, signal_id=item["signal_id"], chain=mock_chain(), profile=MOCK_PROFILE, sim_time=now
            )
            assert state is not None
        res = await sc.evaluate(conn, scenario, run_id)
    failed = [c for c in res["checks"] if c["ok"] is False]
    detail = "\n".join(f"{c['code']}: {c['detail']}" for c in res["checks"])
    assert res["counts"]["errors"] == 0, detail
    assert not failed, detail


async def test_scenario_11_social_sarcasm_on_replay(seeded: str) -> None:
    store = CassetteStore(CASSETTES)
    store.load()
    hit = any(
        r.get("scenario_id") == "social_sarcasm_escalation" and r.get("model") == "GigaChat-3-Pro"
        for r in store._index.values()
    )
    if not hit:
        pytest.skip("нет живой кассеты сценария 11, mock как replay не подставляем")
    scenario = sc.get("social_sarcasm_escalation")
    assert scenario is not None
    chain = ProviderChain([ReplayProvider(store, speed=100.0)])
    async with await psycopg.AsyncConnection.connect(dsn(seeded)) as conn:
        run_id = await new_run(conn, "test scenario 11 replay", scenario_id=scenario["id"])
        now = await sim_now(conn)
        injected = await sc.inject(conn, scenario, run_id, sim_time=now)
        await conn.commit()
        for item in injected:
            state = await process_signal(
                conn, signal_id=item["signal_id"], chain=chain, profile=PROFILE, sim_time=now
            )
            assert state is not None
        res = await sc.evaluate(conn, scenario, run_id)
    failed = [c for c in res["checks"] if c["ok"] is False]
    detail = "\n".join(f"{c['code']}: {c['detail']}" for c in res["checks"])
    assert res["counts"]["errors"] == 0, detail
    assert not failed, detail
