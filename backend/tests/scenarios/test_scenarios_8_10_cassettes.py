"""B25 / T-142: сценарии 8–10 на кассетах. Сценарий 10 без живой записи не идёт как replay."""

from __future__ import annotations

import time
from pathlib import Path

import psycopg
import pytest

from app.agent.graph import process_signal
from app.llm.base import LLMProfile
from app.llm.failover import ProviderChain
from app.replay.provider import ReplayProvider
from app.replay.store import CassetteStore
from app.sim import scenarios as sc
from tests.helpers import dsn, new_run, sim_now

CASSETTES = Path(__file__).resolve().parents[3] / "data" / "cassettes"
PROFILE = LLMProfile(code="gigachat_main", provider="gigachat", model="GigaChat-3-Pro", role="main")


def _store() -> CassetteStore:
    store = CassetteStore(CASSETTES)
    store.load()
    return store


def test_scenario_10_skipped_without_cassette() -> None:
    ids = {r.get("scenario_id") for r in _store()._index.values() if r.get("model") == "GigaChat-3-Pro"}
    assert "qr_fee_public_review" in ids
    assert "branch_misselling" in ids
    if "retail_transcript_red_phrases" not in ids:
        pytest.skip("нет живой кассеты сценария 10, mock как replay не подставляем")


async def test_scenario_08_on_replay(seeded: str) -> None:
    scenario = sc.get("qr_fee_public_review")
    assert scenario is not None
    chain = ProviderChain([ReplayProvider(_store(), speed=100.0)])
    t0 = time.perf_counter()
    async with await psycopg.AsyncConnection.connect(dsn(seeded)) as conn:
        run_id = await new_run(conn, "cassette qr_fee", scenario_id=scenario["id"])
        now = await sim_now(conn)
        injected = await sc.inject(conn, scenario, run_id, sim_time=now)
        await conn.commit()
        for item in injected:
            state = await process_signal(conn, signal_id=item["signal_id"], chain=chain, profile=PROFILE, sim_time=now)
            assert state is not None
            assert state["outcome"] == "completed", state["errors"]
            assert state["errors"] == []
        steps = await (
            await conn.execute(
                "select model from agent_steps s join agent_runs ar on ar.id = s.run_id where ar.sim_run_id = %s",
                (run_id,),
            )
        ).fetchall()
    models = [r[0] for r in steps]
    assert any(m and m.startswith("replay") and "GigaChat-3-Pro" in m for m in models), models
    assert time.perf_counter() - t0 <= 60.0
