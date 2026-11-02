"""B25 / T-142: сценарии 8–10 на кассетах. Сценарий 10 без живой записи не идёт как replay."""

from __future__ import annotations

import json
import time
from pathlib import Path

import psycopg
import pytest

from app.agent.graph import process_signal
from app.contracts.registry import deref
from app.llm.base import LLMProfile, ProviderError
from app.llm.failover import ProviderChain
from app.replay.provider import ReplayProvider
from app.replay.store import CassetteStore, request_hash
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


async def test_scenario_08_on_replay(replay_bank: str) -> None:
    seeded = replay_bank
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


async def test_changed_seed_context_is_honest_replay_miss(seeded: str) -> None:
    """T-017 меняет synthetic bank; его контекст не выдаётся за старую live-запись."""
    store = _store()
    fixture = json.loads((CASSETTES.parents[1] / "backend/tests/fixtures/replay_bank_v1.json").read_text())
    recorded = store._index[f"{fixture['source_request_hash']}:{PROFILE.model}"]
    schema = deref("agent/instant_decision")
    current = store.get("gigachat", PROFILE.model, recorded["messages"], schema)
    assert current is not None
    current_hash = request_hash("gigachat", PROFILE.model, recorded["messages"], schema)
    assert current["request_hash"] == current_hash
    misses = []

    class AuditedReplay(ReplayProvider):
        def _find(self, messages, schema, profile):
            try:
                return super()._find(messages, schema, profile)
            except ProviderError as exc:
                if exc.kind == "miss":
                    misses.append(request_hash(profile.provider, profile.model, messages, schema))
                raise

    scenario = sc.get("qr_fee_public_review")
    async with await psycopg.AsyncConnection.connect(dsn(seeded)) as conn:
        run_id = await new_run(conn, "changed seed is not recorded bank", scenario_id=scenario["id"])
        now = await sim_now(conn)
        injected = await sc.inject(conn, scenario, run_id, sim_time=now)
        await conn.commit()
        for item in injected:
            state = await process_signal(
                conn,
                signal_id=item["signal_id"],
                chain=ProviderChain([AuditedReplay(store, speed=100.0)]),
                profile=PROFILE,
                sim_time=now,
            )
            assert state is not None and state["outcome"] == "fallback_mock"
    assert misses and current_hash not in misses
