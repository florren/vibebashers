"""T-265: источник скора, изоляция, дедупликация и журнал подтверждений на PostgreSQL."""

from __future__ import annotations

import asyncio
import datetime as dt
from contextlib import asynccontextmanager
from decimal import Decimal
from typing import Any

import psycopg
import pytest
from fastapi.testclient import TestClient
from psycopg.rows import dict_row

from app.agent.graph import process_signal
from app.api import finance
from app.main import create_app
from app.sim import scenarios
from tests.helpers import MOCK_PROFILE, dsn, mock_chain, new_run, sim_now

pytestmark = pytest.mark.integration


def patch_db(monkeypatch: pytest.MonkeyPatch, url: str) -> None:
    @asynccontextmanager
    async def connect():
        async with await psycopg.AsyncConnection.connect(dsn(url), autocommit=True, row_factory=dict_row) as conn:
            yield conn

    monkeypatch.setattr(finance, "db", connect)


def add_case(conn: Any, rid: int, cid: int | None, kind: str = "fee_refund", now: dt.datetime | None = None) -> int:
    now = now or dt.datetime(2026, 11, 9, 6, tzinfo=dt.UTC)
    iid = conn.execute(
        """insert into incidents (run_id,title,incident_type,product_code,team_code,complexity,criticality,priority,status,created_by,created_sim,sla_due_sim,take_due_sim,resolved_sim,primary_client_id,outcome_class)
      values (%s,'evidence fixture',%s,'debit_card','team_cx','easy','low',4,'resolved','scenario',%s,%s,%s,%s,%s,'closed_in_sla') returning id""",
        (rid, kind, now, now + dt.timedelta(days=1), now + dt.timedelta(hours=1), now, cid),
    ).fetchone()[0]
    conn.execute(
        """insert into incident_economics (incident_id,run_id,affected_count,rate_code,rate_rub,detractor_share,no_return_share,potential_loss_rub,retention_factor,prevented_loss_rub,refund_amount_rub,computed_sim)
      values (%s,%s,1,'bank_average',458.46,0.1,0.5,22.92,0.9,20.63,10,%s)""",
        (iid, rid, now),
    )
    return int(iid)


def test_agent_snapshot_and_client_deduplication(seeded: str, conn: Any, monkeypatch: pytest.MonkeyPatch) -> None:
    patch_db(monkeypatch, seeded)

    async def run():
        async with await psycopg.AsyncConnection.connect(dsn(seeded)) as writer:
            scenario = scenarios.get("qr_fee_public_review")
            rid = await new_run(writer, "T-265 calibration smoke", scenario_id=scenario["id"])
            items = await scenarios.inject(writer, scenario, rid, sim_time=await sim_now(writer))
            await writer.commit()
            for item in items:
                await process_signal(
                    writer,
                    signal_id=item["signal_id"],
                    chain=mock_chain(),
                    profile=MOCK_PROFILE,
                    sim_time=await sim_now(writer),
                )
            await writer.commit()
            return rid

    rid = asyncio.run(run())
    iid, cid = conn.execute(
        "select id,primary_client_id from incidents where run_id=%s order by id limit 1", (rid,)
    ).fetchone()
    with TestClient(create_app()) as client:
        url = "/api/v1/finance/impact/assessment"
        first = client.get(url, params={"run_id": rid})
        assert first.status_code == 200, first.text
        demo, observed = first.json()["contours"]
        assert demo["known_clients"] == 1 and demo["unknown_clients"] == 0, demo
        assert 0 < demo["risk_total_rub"] < 458.46
        assert demo["refund_rub"] == 450
        assert observed["risk_total_rub"] is None and observed["fine_rub"] is None
        proof = client.get(f"/api/v1/finance/impact/incident/{iid}", params={"run_id": rid}).json()["proof"]
        risk = proof["risks"][0]
        assert risk["model"] == "mock:mock-rules-v1" and risk["score_pipeline"] == "agent-score-v1"
        assert risk["status"] == "calibrated" and risk["step_id"] is not None and risk["predicted_sim"]
        assert risk["dataset_sha256"] == demo["calibration"]["dataset_sha256"]
        duplicate_id = add_case(conn, rid, cid, now=dt.datetime(2026, 11, 9, 7, tzinfo=dt.UTC))
        duplicate = client.get(url, params={"run_id": rid}).json()["contours"][0]
        assert duplicate["duplicate_cases"] == 1 and duplicate["known_clients"] == 1
        assert duplicate["risk_total_rub"] == demo["risk_total_rub"]
        assert Decimal(str(duplicate["net_rub"])) == Decimal(str(demo["net_rub"])) - 10
        window = client.get(
            url,
            params={
                "run_id": rid,
                "period": "custom",
                "start_date": "2026-11-09T06:30Z",
                "end_date": "2026-11-09T08:00Z",
            },
        ).json()["contours"][0]
        assert window["duplicate_cases"] == 1 and window["risk_total_rub"] == 0 and window["refund_rub"] == 10
        conn.execute(
            "update incident_economics set computed_at='2000-01-01T00:00:00Z' where incident_id=%s", (duplicate_id,)
        )
        incomplete = client.get(url, params={"run_id": rid}).json()["contours"][0]
        assert incomplete["risk_total_rub"] == demo["risk_total_rub"]
        assert incomplete["net_rub"] is None and incomplete["reasons"]["incomplete_refunds"] == 1
        other = conn.execute("select id from clients where id<>%s order by id limit 1", (cid,)).fetchone()[0]
        add_case(conn, rid, other)
        partial = client.get(url, params={"run_id": rid}).json()["contours"][0]
        assert partial["unknown_clients"] == 1 and partial["risk_total_rub"] is None and partial["net_rub"] is None
        assert partial["known_risk_rub"] == demo["known_risk_rub"]
        assert client.get(f"/api/v1/finance/impact/incident/{iid}", params={"run_id": 1}).status_code == 404
        conn.execute("update sim_state set current_run_id=null where id=1")
        empty = client.get(url).json()
        assert empty["run_id"] is None and empty["contours"][0]["risk_total_rub"] == 0
        assert empty["contours"][1]["risk_total_rub"] is None


def test_fine_evidence_versions_replay_withdrawal_and_scope(
    seeded: str, conn: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    patch_db(monkeypatch, seeded)
    now = dt.datetime(2026, 11, 9, 6, tzinfo=dt.UTC)
    rid = conn.execute(
        "insert into sim_runs(kind,label,seed,started_sim) values ('free','T-265 evidence',42,%s) returning id", (now,)
    ).fetchone()[0]
    cid = conn.execute("select id from clients order by id limit 1").fetchone()[0]
    iid = add_case(conn, rid, cid, "misselling", now)
    emp, branch = conn.execute("select id,branch_id from employees order by id limit 1").fetchone()
    sid = conn.execute(
        """insert into audio_sessions(run_id,branch_id,employee_id,client_id,source,stt_provider,diarization_mode,started_sim)
      values (%s,%s,%s,%s,'transcript','none','manual',%s) returning id""",
        (rid, branch, emp, cid, now - dt.timedelta(hours=3)),
    ).fetchone()[0]
    alert = conn.execute(
        "insert into compliance_alerts(session_id,incident_id,decision) values (%s,%s,'go') returning id", (sid, iid)
    ).fetchone()[0]
    before = conn.execute("select count(*) from ledger_entries").fetchone()[0]
    payload = {
        "scope": "demo",
        "incident_id": iid,
        "alert_id": alert,
        "policy_id": "demo-fine-v1",
        "deal_ref": "DEMO-DEAL-1",
        "idempotency_key": "DEMO-KEY-1",
        "intervention_sim": (now - dt.timedelta(hours=2)).isoformat(),
        "deal_closed_sim": (now - dt.timedelta(hours=1)).isoformat(),
        "outcome": "prevented",
        "evidence_ref": "DEMO-SYNTHETIC-EVIDENCE-1",
        "recorded_by": "demo_operator",
    }
    with TestClient(create_app()) as client:

        def assessed():
            response = client.get("/api/v1/finance/impact/assessment", params={"run_id": rid})
            assert response.status_code == 200, response.text
            return response.json()["contours"]

        def record(body):
            return client.post("/api/v1/finance/impact/evidence", params={"run_id": rid}, json=body)

        assert assessed()[0]["fine_rub"] == 0  # go без доказательства не даёт суммы.
        first = record(payload)
        assert first.status_code == 201, first.text
        repeat = record(payload)
        assert repeat.status_code == 201 and repeat.json()["replayed"] and repeat.json()["id"] == first.json()["id"]
        assert record({**payload, "deal_ref": "other"}).status_code == 409
        admitted = assessed()[0]
        assert admitted["qualified_deals"] == 1 and admitted["fine_rub"] == 50000
        assert admitted["risk_total_rub"] is None and admitted["combined_net_rub"] is None
        assert record({**payload, "idempotency_key": "DEMO-KEY-2"}).status_code == 201
        assert assessed()[0]["qualified_deals"] == 1 and assessed()[0]["fine_rub"] == 50000
        assert record({**payload, "idempotency_key": "DEMO-KEY-3", "outcome": "unknown"}).status_code == 201
        assert assessed()[0]["fine_rub"] == 0 and assessed()[0]["excluded_deals"] == 1
        assert (
            record(
                {
                    **payload,
                    "idempotency_key": "DEMO-KEY-4",
                    "intervention_sim": (now - dt.timedelta(minutes=30)).isoformat(),
                }
            ).status_code
            == 201
        )
        assert assessed()[0]["reasons"]["late_intervention"] == 1
        assert (
            record(
                {
                    **payload,
                    "idempotency_key": "DEMO-KEY-5",
                    "deal_closed_sim": (now + dt.timedelta(hours=1)).isoformat(),
                }
            ).status_code
            == 422
        )
        assert record({**payload, "scope": "observed"}).status_code == 409
        assert record({**payload, "idempotency_key": "BAD-ALERT", "alert_id": 999999}).status_code == 404
        assert record({**payload, "amount_rub": 900000}).status_code == 422
        assert record({**payload, "intervention_sim": "2026-11-09T04:00:00"}).status_code == 422
        records = client.get(f"/api/v1/finance/impact/incident/{iid}", params={"run_id": rid}).json()["proof"][
            "records"
        ]
        assert len(records) == 4 and records[-1]["evidence_ref"] == payload["evidence_ref"]
        with pytest.raises(psycopg.errors.RaiseException):
            conn.execute("update financial_evidence set outcome='prevented' where id=%s", (first.json()["id"],))
        assert conn.execute("select count(*) from ledger_entries").fetchone()[0] == before
