"""T-224/225/230: real recorded scenarios, SQL read-only enforcement and run isolation."""

from __future__ import annotations

import datetime as dt
import json
from pathlib import Path
from time import perf_counter

import psycopg
import pytest
from fastapi import HTTPException
from psycopg.rows import dict_row

from app.agent.graph import process_signal
from app.contracts.events.trace.journey import Journey as JourneyResponse
from app.contracts.events.trace.search_response import SearchResponse
from app.contracts.events.trace.trace_response import TraceResponse
from app.search.service import search_objects
from app.sim import scenarios as sc
from app.trace.assembler import assemble
from app.trace.journey import journey, latest
from tests.helpers import MOCK_PROFILE, dsn, mock_chain, new_run, sim_now

pytestmark = pytest.mark.integration


@pytest.mark.parametrize("scenario_id", ["deposit_promo_rate", "qr_fee_public_review", "social_sarcasm_escalation"])
async def test_recorded_scenario_read_only(seeded, scenario_id):
    async with await psycopg.AsyncConnection.connect(dsn(seeded)) as writer:
        scenario = sc.get(scenario_id)
        rid = await new_run(writer, "trace regression", scenario_id=scenario_id)
        injected = await sc.inject(writer, scenario, rid, sim_time=await sim_now(writer))
        await writer.commit()
        for item in injected:
            await process_signal(writer, signal_id=item["signal_id"], chain=mock_chain(), profile=MOCK_PROFILE)
        await writer.commit()
    async with await psycopg.AsyncConnection.connect(dsn(seeded), row_factory=dict_row) as reader:
        await reader.execute("SET TRANSACTION READ ONLY")
        ref = f"SIG-{injected[0]['signal_id']:06d}"
        result, nodes = await assemble(reader, "signal", ref, run_id=str(rid))
        TraceResponse.model_validate(result)
        assert result["after"] and result["before"]
        assert {n["scope_id"] for n in nodes if n["scope_id"]} <= {rid, 1}
        assert not any(k in json.dumps(result) for k in ("response_raw", "prompt_tokens", "Authorization"))
        model = await journey(reader, ref, str(rid), presenter=True)
        JourneyResponse.model_validate(model)
        assert model == await journey(reader, ref, str(rid), presenter=True)
        assert any(
            fact["label_ru"] == "Заметка ведущего"
            for stage in model["stages"]
            for event in stage["events"]
            for fact in event["key_facts"]
        )
        plain = await journey(reader, ref, str(rid), presenter=False)
        assert not any(
            fact["label_ru"] == "Заметка ведущего"
            for stage in plain["stages"]
            for event in stage["events"]
            for fact in event["key_facts"]
        )
        assert len(model["stages"]) == 8
        assert any(s["events"] for s in model["stages"][1:])
        if scenario_id == "qr_fee_public_review":
            assert result["terminal"]["reached"]
            assert model["summary"]["amount_rub"] == 450
            assert any(m["kind"] == "public_reply" for m in model["client_lane"])
        hits = await search_objects(reader, ref.lower())
        SearchResponse.model_validate(hits)
        assert hits["hits"][0]["ref"] == ref
        assert (await latest(reader, "sim", str(rid)))["latest_href"]
        with pytest.raises(psycopg.errors.ReadOnlySqlTransaction):
            await reader.execute("UPDATE signals SET text='must fail' WHERE id=%s", (injected[0]["signal_id"],))


async def test_search_variants_and_explicit_scope(seeded):
    async with await psycopg.AsyncConnection.connect(dsn(seeded), row_factory=dict_row) as conn:
        await conn.execute("SET TRANSACTION READ ONLY")
        for q in (
            "SIG-1",
            "INC-1",
            "CL-1",
            "1",
            "комиссия",
            "' OR 1=1 --",
            "**** 4512",
            "@unknown",
            "+7 900 ***-**-12",
        ):
            SearchResponse.model_validate(await search_objects(conn, q))
        ambiguous = await search_objects(conn, "1")
        assert {"signal", "incident", "client"} <= set(ambiguous["counts_by_kind"])
        assert not (await search_objects(conn, "комиссия", "999999"))["hits"] or all(
            h["run_id"] == "SR-0001" for h in (await search_objects(conn, "комиссия", "999999"))["hits"]
        )
        with pytest.raises(HTTPException) as exc:
            await assemble(conn, "signal", "SIG-000001", run_id="invalid")
        assert exc.value.status_code == 422
        times = []
        for _ in range(10):
            start = perf_counter()
            await assemble(conn, "incident", "INC-000001")
            times.append((perf_counter() - start) * 1000)
        assert max(times) < 300


async def test_scenario_12_13_replay(replay_bank):
    seeded = replay_bank
    from app.llm.base import LLMProfile
    from app.llm.failover import ProviderChain
    from app.replay.provider import ReplayProvider
    from app.replay.store import CassetteStore

    store = CassetteStore(Path(__file__).resolve().parents[3] / "data/cassettes")
    store.load()
    profile = LLMProfile(code="gigachat_main", provider="gigachat", model="GigaChat-3-Pro", role="main")
    scenario = sc.get("qr_fee_public_review")
    async with await psycopg.AsyncConnection.connect(dsn(seeded)) as writer:
        rid = await new_run(writer, "journey replay", scenario_id=scenario["id"])
        now = await sim_now(writer)
        items = await sc.inject(writer, scenario, rid, sim_time=now)
        await writer.commit()
        for item in items:
            await process_signal(
                writer,
                signal_id=item["signal_id"],
                chain=ProviderChain([ReplayProvider(store, speed=100.0)]),
                profile=profile,
                sim_time=now,
            )
        await writer.commit()
    async with await psycopg.AsyncConnection.connect(dsn(seeded), row_factory=dict_row) as conn:
        await conn.execute("SET TRANSACTION READ ONLY")
        ref = f"SIG-{items[0]['signal_id']:06d}"
        model = await journey(conn, ref, str(rid))
        assert model["summary"]["llm_source"] == "replay"
        fallback_count = await (
            await conn.execute(
                "select count(*) n from agent_steps st join agent_runs ar on ar.id=st.run_id where ar.signal_id=%s and st.status in ('fallback','error')",
                (items[0]["signal_id"],),
            )
        ).fetchone()
        assert fallback_count["n"] == 0
        assert model["client_lane"]
        for n in (await assemble(conn, "signal", ref))[1]:
            if n["kind"] in (
                "signal",
                "incident",
                "agent_run",
                "ledger",
                "human_decision",
                "notification",
                "followup",
                "escalation",
                "task",
            ):
                public = n["data"]["public_id"]
                assert any(h["ref"] == public for h in (await search_objects(conn, public))["hits"])


async def test_fanout_and_query_budget(seeded):

    from app.ingest.normalizer import create_signal, from_api_signal

    async with await psycopg.AsyncConnection.connect(dsn(seeded)) as writer:
        rid = await new_run(writer, "fanout trace")
        incident = await (await writer.execute("SELECT id, created_sim FROM incidents ORDER BY id LIMIT 1")).fetchone()
        for i in range(120):
            message = from_api_signal(
                {"channel_code": "chat", "text": f"Повторное обращение {i}", "client_id": 1}, origin="jury"
            )
            accepted = await create_signal(writer, message, run_id=rid, source_code="api", emit_event=False)
            await writer.execute(
                "INSERT INTO incident_signals (incident_id, signal_id, linked_sim) VALUES (%s,%s,%s)",
                (incident[0], accepted["signal_id"], incident[1] + dt.timedelta(hours=1)),
            )
        await writer.commit()
    async with await psycopg.AsyncConnection.connect(dsn(seeded), row_factory=dict_row) as conn:
        await conn.execute("SET TRANSACTION READ ONLY")

        class Counted:
            queries = 0

            async def execute(self, sql, args=()):
                self.queries += 1
                return await conn.execute(sql, args)

        counted = Counted()
        result, _ = await assemble(counted, "incident", str(incident[0]))
        assert counted.queries <= 20
        assert any(g["kind"] == "signal_created" and g["count"] >= 120 for g in result["groups"])
        assert len([e for e in result["after"] if e["kind"] == "signal_created"]) <= 3
        TraceResponse.model_validate(result)
        branches = await search_objects(conn, "ВСП 0042")
        assert branches["hits"][0]["ref"] == "VSP-0042"
        assert (await assemble(conn, "branch", "VSP-0042"))[0]["subject"]["ref"] == "VSP-0042"
        assert (await search_objects(conn, "0042"))["counts_by_kind"]["branch"] == 1


def test_read_model_scenario_manifests():
    import yaml

    from app.search.grammar import PREFIXES

    root = Path(__file__).resolve().parents[3]
    path = yaml.safe_load((root / "data/scenarios/12_journey.yaml").read_text())
    search = yaml.safe_load((root / "data/scenarios/13_search_trace.yaml").read_text())
    assert {p["trajectory"] for p in path["paths"]} == {"autonomous", "human", "escalation"}
    assert set(search["queries"]["prefixes"]) == set(PREFIXES)
    assert all(sc.get(p["source"]) is not None for p in path["paths"])
