"""T-192: сценарий 9 на кассете replay GigaChat-3-Pro, без подмены mock."""

from __future__ import annotations

import time
from pathlib import Path

import psycopg
import pytest

from app.compliance.transcripts import analyze_transcript
from app.llm.base import LLMProfile
from app.llm.failover import ProviderChain
from app.replay.provider import ReplayProvider
from app.replay.store import CassetteStore
from app.sim import scenarios as sc
from tests.helpers import dsn, new_run, sim_now

pytestmark = pytest.mark.integration

PROFILE = LLMProfile(code="gigachat_main", provider="gigachat", model="GigaChat-3-Pro", role="main")
CASSETTES = Path(__file__).resolve().parents[3] / "data" / "cassettes"


def _replay_chain() -> ProviderChain:
    store = CassetteStore(CASSETTES)
    assert store.load() > 0, "нет data/cassettes/*.jsonl"
    hit = any(
        r.get("scenario_id") == "branch_misselling" and r.get("model") == "GigaChat-3-Pro"
        for r in store._index.values()
    )
    assert hit, "нет живой кассеты branch_misselling / GigaChat-3-Pro"
    return ProviderChain([ReplayProvider(store, speed=100.0)])


async def test_scenario_09_transcript_on_replay(seeded: str) -> None:
    scenario = sc.get("branch_misselling")
    assert scenario is not None and sc.is_transcript(scenario)
    chain = _replay_chain()
    t0 = time.perf_counter()
    async with await psycopg.AsyncConnection.connect(dsn(seeded)) as conn:
        run_id = await new_run(conn, "test branch_misselling replay", scenario_id="branch_misselling")
        now = await sim_now(conn)
        tr = await sc.inject_transcript(conn, scenario, run_id, sim_time=now)
        await conn.commit()
        report = await analyze_transcript(conn, tr["transcript_id"], chain=chain, profile=PROFILE, sim_time=now)
        await conn.commit()
        res = await sc.evaluate(conn, scenario, run_id)
        steps = await (
            await conn.execute(
                "select model from agent_steps s join agent_runs ar on ar.id = s.run_id "
                "where ar.sim_run_id = %s and ar.kind = 'compliance_detector'",
                (run_id,),
            )
        ).fetchall()
    elapsed = time.perf_counter() - t0
    models = [r[0] for r in steps]
    assert "replay/GigaChat-3-Pro" in models, f"записанный вызов не воспроизвёлся: {models}"
    assert report["status"] == "done"
    assert elapsed <= 60.0, f"прогон {elapsed:.1f} с > 60 с"
    failed = [c for c in res["checks"] if c["ok"] is False]
    detail = "\n".join(f"{c['code']}: {c['detail']}" for c in res["checks"])
    assert not failed, detail
