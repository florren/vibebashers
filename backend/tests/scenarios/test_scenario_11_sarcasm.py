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


async def test_scenario_11_strict_replay_on_immutable_bank(migrated_db: str, monkeypatch, request) -> None:
    """Только настоящие ответы и точный банк записи, а не произвольный текущий seed."""
    from scripts.replay11_bank import configure_profile, seed_bank

    from app.config import get_settings
    from app.contracts.registry import deref
    from app.llm.base import ProviderError
    from app.replay.scenario11_record import fixture, recording_profile, run_graph
    from app.replay.store import request_hash
    from tests.helpers import fresh_replay11_database

    store = CassetteStore(CASSETTES)
    store.load()
    records = [
        r
        for r in store._index.values()
        if r.get("scenario_id") == "social_sarcasm_escalation" and r.get("model") == "GigaChat-3-Pro"
    ]
    if not records:
        pytest.skip("нет настоящей кассеты11; mock не заменяет strict replay")
    monkeypatch.setenv("LLM_PROVIDER", "replay")
    get_settings.cache_clear()
    request.addfinalizer(get_settings.cache_clear)
    chain = ProviderChain([ReplayProvider(store, speed=10000)], append_mock=False)
    assert chain.names == ["replay"] and chain.strict
    async with fresh_replay11_database(migrated_db) as (bank_dsn, _):
        async with await psycopg.AsyncConnection.connect(bank_dsn) as bank:
            await seed_bank(bank, bank_dsn)
            profile = await configure_profile(bank, recording_profile(PROFILE))
            result = await run_graph(bank, chain, profile, source="replay")
            assert [row[0] for row in result["steps"]] == ["normalize", "classify", "decide"]
            assert all(row[1] == "ok" and row[2].startswith("replay:") for row in result["steps"])
            failures = await (
                await bank.execute(
                    "select count(*) from agent_steps where run_id in(select id from agent_runs where signal_id=%s) and status in ('error','fallback')",
                    (result["signal_id"],),
                )
            ).fetchone()
            assert failures and failures[0] == 0
            assert (await (await bank.execute("select count(*) from llm_runtime.wire_attempts")).fetchone())[0] == 0
    # Тот же настоящий ответ нельзя выдавать изменённому тексту под новым hash.
    schema = deref("agent/normalization")
    normalization = [
        r for r in records if r["request_hash"] == request_hash("gigachat", PROFILE.model, r["messages"], schema)
    ]
    assert len(normalization) == 1
    messages = normalization[0]["messages"]
    changed = [*messages[:-1], {"role": "user", "content": fixture()["text"] + " Другой контекст."}]
    with pytest.raises(ProviderError, match="нет кассеты"):
        await chain.complete_structured(changed, schema, profile)
