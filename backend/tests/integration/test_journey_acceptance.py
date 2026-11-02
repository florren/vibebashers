"""T-229: реальные три графа с Mock-provider, отдельно от честного replay gate."""

from __future__ import annotations

import copy
from collections import Counter

import httpx
import psycopg
import pytest
from scripts.journey_check import check_path, recorded_paths

from app.agent.graph import process_signal, wake_due_followups
from app.llm.failover import ProviderChain
from app.main import create_app
from app.sim import scenarios as sc
from app.trace.privacy import mask
from tests.helpers import MOCK_PROFILE, dsn, mock_chain, new_run, sim_now

pytestmark = pytest.mark.integration


@pytest.mark.parametrize(
    "source,trajectory",
    [
        ("qr_fee_public_review", "autonomous"),
        ("deposit_promo_rate", "human"),
        ("social_sarcasm_escalation", "escalation"),
    ],
)
async def test_three_actual_graph_trajectories(seeded, source, trajectory, monkeypatch):
    async with await psycopg.AsyncConnection.connect(dsn(seeded)) as writer:
        scenario = sc.get(source)
        if trajectory == "human":
            # Вариант сценария1 с существующим ultra_vip guard; обычный mass
            # клиент сам по себе не обязан попадать на HITL. Policy не меняется.
            scenario = copy.deepcopy(scenario)
            scenario["inject"] = scenario["inject"][:1]
            scenario["inject"][0]["client"]["segment"] = "ultra_vip"
        rid = await new_run(writer, "T229 actual Mock graph", scenario_id=source)
        now = await sim_now(writer)
        items = await sc.inject(writer, scenario, rid, sim_time=now)
        await writer.commit()
        for item in items:
            await process_signal(
                writer, signal_id=item["signal_id"], chain=mock_chain(), profile=MOCK_PROFILE, sim_time=now
            )
        await writer.commit()
        if trajectory == "autonomous":
            # Нативный общий incident может содержать чужие доставки. Fixture
            # добавляет их до read-only GET; деньги/инструменты не вызываются.
            await writer.execute(
                "INSERT INTO notifications(run_id,recipient_type,client_id,incident_id,channel_code,template_code,body,status,sent_sim,sent_at) "
                "SELECT %s,'client',(SELECT id FROM clients WHERE id<>s.client_id ORDER BY id LIMIT 1),i.incident_id,'chat','ack_received',"
                "'Чужой синтетический ответ','sent',%s,now() FROM signals s JOIN incident_signals i ON i.signal_id=s.id WHERE s.id=%s",
                (rid, now, items[0]["signal_id"]),
            )
            await writer.commit()
        if trajectory == "escalation":
            due = await (
                await writer.execute(
                    "SELECT max(wake_sim) FROM followups WHERE signal_id=%s AND reason='awaiting_client' AND status='scheduled'",
                    (items[0]["signal_id"],),
                )
            ).fetchone()
            assert due and due[0]
            assert (
                await wake_due_followups(
                    writer, sim_time=due[0], chain=mock_chain(), profile=MOCK_PROFILE, signal_id=items[0]["signal_id"]
                )
                == 1
            )
            await writer.commit()
        await writer.execute("SET TRANSACTION READ ONLY")
        paths, missing = await recorded_paths(writer, sc.get("customer_journey"))
        case = next(path for path in paths if path.source == source)
        assert case.run_id == rid
        delivered = await (
            await writer.execute(
                "SELECT body FROM notifications WHERE (signal_id=%s OR incident_id IN "
                "(SELECT incident_id FROM incident_signals WHERE signal_id=%s)) AND run_id=%s "
                "AND client_id IS NOT DISTINCT FROM (SELECT client_id FROM signals WHERE id=%s) "
                "AND recipient_type='client' AND status IN ('sent','delivered') AND sent_at IS NOT NULL "
                "UNION ALL SELECT e.text FROM external_replies e JOIN signals s ON s.external_post_id=e.post_id "
                "WHERE s.id=%s AND e.run_id=%s AND e.author IN ('agent','human')",
                (items[0]["signal_id"], items[0]["signal_id"], rid, items[0]["signal_id"], items[0]["signal_id"], rid),
            )
        ).fetchall()

    def forbidden(*args, **kwargs):
        raise AssertionError("journey GET must never call LLM")

    monkeypatch.setattr(ProviderChain, "complete_structured", forbidden)
    monkeypatch.setattr(ProviderChain, "stream", forbidden)
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=create_app()), base_url="http://test") as http:
        # Mock — явный test-only режим; production CLI требует настоящий replay.
        assert await check_path(http, case, expected_source="mock") == []
        payload = (await http.get(f"/api/journey/{case.ref}", params={"run_id": str(rid)})).json()
        assert Counter(message["text_ru"] for message in payload["client_lane"]) == Counter(
            mask(row[0], 2000) for row in delivered
        )
