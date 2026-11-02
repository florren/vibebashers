"""T-234: сценарии 1/6/8 создаются Mock, затем Graph читает только реальные DTO."""

import json
from pathlib import Path
from unittest.mock import AsyncMock

import psycopg
import pytest
from fastapi.testclient import TestClient

from app.agent.graph import process_signal
from app.config import get_settings
from app.contracts.events.trace.trace_response import TraceResponse
from app.main import create_app
from app.sim import scenarios as sc
from tests.helpers import MOCK_PROFILE, dsn, mock_chain, new_run, sim_now
from tests.integration.test_trace_fanout import fingerprints, walk

pytestmark = pytest.mark.integration


async def test_graph_real_recorded_scenarios_1_6_8_read_only(seeded, monkeypatch):
    """Fixture writes precede all read-only evidence; no delivery/live provider involved."""
    monkeypatch.setenv("DATABASE_URL", seeded)
    get_settings.cache_clear()
    cases = []
    async with await psycopg.AsyncConnection.connect(dsn(seeded)) as conn:
        for scenario_id in ("deposit_promo_rate", "mass_notifications", "qr_fee_public_review"):
            scenario = sc.get(scenario_id)
            rid = await new_run(conn, "T234 offline scenario fixture", scenario_id=scenario_id)
            injected = await sc.inject(conn, scenario, rid, sim_time=await sim_now(conn))
            await conn.commit()
            for item in injected:
                assert await process_signal(conn, signal_id=item["signal_id"], chain=mock_chain(), profile=MOCK_PROFILE)
            await conn.commit()
            sid = injected[0]["signal_id"]
            public_signal = (
                await (await conn.execute("select public_id from signals where id=%s", (sid,))).fetchone()
            )[0]
            incident = await (
                await conn.execute(
                    "select i.public_id from incidents i join incident_signals l on l.incident_id=i.id where l.signal_id=%s order by i.id limit 1",
                    (sid,),
                )
            ).fetchone()
            assert incident is not None
            cases.append(
                {"scenario": scenario_id, "run_id": rid, "signal_ref": public_signal, "incident_ref": incident[0]}
            )
    before = fingerprints(seeded)
    bomb = AsyncMock(side_effect=AssertionError("Graph GET must never invoke LLM"))
    monkeypatch.setattr("app.llm.failover.ProviderChain.complete_structured", bomb)
    observations = []
    with TestClient(create_app()) as client:
        for case in cases:
            for kind in ("signal", "incident"):
                response = client.get(
                    f"/api/trace/{kind}/{case[kind + '_ref']}",
                    params={"run_id": str(case["run_id"]), "include": "detail"},
                )
                assert response.status_code == 200
                data = response.json()
                TraceResponse.model_validate(data)
                assert data["subject"]["kind"] == kind and data["edges"]
                known = {event["id"] for event in data["before"] + data["after"]}
                unknown = {edge[endpoint] for edge in data["edges"] for endpoint in ("from", "to")} - known
                assert len(unknown) <= 1  # assembler subject endpoint invariant used by SVG
                for group in data["groups"]:
                    assert "anchor" in group and "phase" in group
                    page, ids = walk(
                        client,
                        f"/api/trace/{group['anchor']['kind']}/{group['anchor']['ref']}/relations",
                        direction=group["phase"],
                        event_kind=group["kind"],
                        run_id=str(case["run_id"]),
                        limit=50,
                    )
                    assert len(ids) == page["total"]
                encoded = json.dumps(data)
                assert not any(raw in encoded for raw in ("response_raw", "Authorization", '"prompt"'))
                observations.append(
                    {
                        **case,
                        "kind": kind,
                        "nodes": len(known) + 1,
                        "edges": len(data["edges"]),
                        "groups": len(data["groups"]),
                        "subject_alias_unambiguous": len(unknown) == 1,
                    }
                )
    assert bomb.call_count == 0
    assert fingerprints(seeded) == before
    Path("/tmp/vibebashers-t234-real-scenarios.json").write_text(
        json.dumps(
            {
                "mode": "Mock fixture generation, then actual read-only GET; noLLM",
                "cases": cases,
                "observations": observations,
                "all_application_table_fingerprints_unchanged": True,
                "read_phase_llm_calls": 0,
            },
            indent=2,
        )
        + "\n"
    )
    get_settings.cache_clear()
