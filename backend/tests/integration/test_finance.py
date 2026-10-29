"""Срезы, сценарии, округление, отсутствие дублей и изоляция запусков на PostgreSQL."""

from __future__ import annotations

import datetime as dt
from contextlib import asynccontextmanager
from typing import Any

import psycopg
import pytest
from fastapi.testclient import TestClient
from psycopg.rows import dict_row

from app.api import finance
from app.economics import dcltv
from app.main import create_app

pytestmark = pytest.mark.integration


def test_finance_run_slice(seeded: str, conn: psycopg.Connection[Any], monkeypatch: pytest.MonkeyPatch) -> None:
    dsn = seeded.replace("postgresql+psycopg://", "postgresql://")

    @asynccontextmanager
    async def test_db():
        async with await psycopg.AsyncConnection.connect(dsn, autocommit=True, row_factory=dict_row) as c:
            yield c

    monkeypatch.setattr(finance, "db", test_db)
    rid = conn.execute(
        "insert into sim_runs (kind,label,seed,started_sim) values ('free','finance test',42,'2026-10-29T09:00Z') returning id"
    ).fetchone()[0]
    other = conn.execute(
        "insert into sim_runs (kind,label,seed,started_sim) values ('free','other test',42,'2026-10-29T09:00Z') returning id"
    ).fetchone()[0]
    cid = conn.execute("select id from clients order by id limit 1").fetchone()[0]
    product = conn.execute("select code from products order by code limit 1").fetchone()[0]

    def incident(
        run: int, status: str, kind: str = "fee_refund", at: str = "2026-10-29T10:00Z", client: int | None = cid
    ) -> int:
        return conn.execute(
            """insert into incidents (run_id,title,incident_type,product_code,team_code,complexity,criticality,priority,status,created_by,created_sim,sla_due_sim,take_due_sim,resolved_sim,primary_client_id,outcome_class)
         values (%s,'finance test',%s,%s,'team_cx','easy','low',4,%s,'scenario','2026-10-29T09:00Z','2026-10-30T10:00Z','2026-10-29T11:00Z',%s,%s,'closed_in_sla') returning id""",
            (run, kind, product, status, at, client),
        ).fetchone()[0]

    def economics(iid: int, run: int, saved: float = 366.77, refund: float = 450, rate: float = 458.46) -> None:
        conn.execute(
            """insert into incident_economics (incident_id,run_id,affected_count,rate_code,rate_rub,detractor_share,no_return_share,potential_loss_rub,retention_factor,prevented_loss_rub,refund_amount_rub,computed_sim)
          values (%s,%s,1,'bank_average',%s,1,1,%s,0.8,%s,%s,'2026-10-29T10:00Z')""",
            (iid, run, rate, rate, saved, refund),
        )

    iid = incident(rid, "resolved")
    economics(iid, rid)
    mid = incident(rid, "closed", "misselling", at="2026-10-29T11:00Z")
    economics(mid, rid, saved=3240, refund=0, rate=4050)
    # Несколько алертов одного кейса не умножают условный штраф.
    emp, branch = conn.execute("select id,branch_id from employees order by id limit 1").fetchone()
    sid = conn.execute(
        """insert into audio_sessions (run_id,branch_id,employee_id,source,stt_provider,diarization_mode,started_sim) values (%s,%s,%s,'transcript','none','manual','2026-10-29T10:00Z') returning id""",
        (rid, branch, emp),
    ).fetchone()[0]
    for _ in range(2):
        conn.execute("insert into compliance_alerts (session_id,incident_id,decision) values (%s,%s,'go')", (sid, mid))
    missing = incident(rid, "resolved", at="2026-10-29T12:00Z")
    open_id = incident(rid, "in_progress")
    economics(open_id, rid, saved=999999)
    foreign = incident(other, "resolved")
    economics(foreign, other, saved=999999)
    old = incident(rid, "closed", at="2026-10-28T10:00Z")
    economics(old, rid, saved=20, refund=0)
    conn.execute(
        "update sim_state set current_run_id=%s, sim_time=%s where id=1",
        (rid, dt.datetime(2026, 10, 29, 13, tzinfo=dt.UTC)),
    )
    with TestClient(create_app()) as client:
        url = "/api/v1/finance/impact/total"
        res = client.get(url, params={"period": "day", "limit": 1}).json()
        assert res["incidents_resolved"] == 3 and res["missing_calculations"] == 1
        assert res["total_saved_rub"] == 3606.77 and res["refund_rub"] == 450
        assert res["net_effect_rub"] == 3156.77
        assert res["scenario_saved_rub"] == 4508.46 and res["scenario_fine_rub"] == 50000
        assert res["scenario_with_fine_net_rub"] == 54058.46 and res["fine_cases"] == 1
        assert res["next_offset"] == 1 and len(res["items"]) == 1
        assert res["series"][-1]["saved_rub"] == res["total_saved_rub"]
        assert res["series"][-1]["net_rub"] == res["net_effect_rub"]
        second = client.get(url, params={"period": "day", "limit": 1, "offset": 1}).json()
        assert second["total_saved_rub"] == res["total_saved_rub"]
        assert second["items"][0]["incident_id"] != res["items"][0]["incident_id"]
        half = client.get(url, params={"period": "day", "probability_percent": 50, "fine_per_case_rub": 0}).json()
        assert half["scenario_saved_rub"] == 2254.23 and half["scenario_fine_rub"] == 0
        ref = conn.execute("select public_id from incidents where id=%s", (iid,)).fetchone()[0]
        detail = client.get("/api/v1/finance/impact/incident/" + ref).json()
        assert detail["net_rub"] == -83.23 and detail["scenario_base_rub"] == 458.46
        assert client.get(f"/api/v1/finance/impact/incident/{foreign}").status_code == 404
        custom = client.get(
            url, params={"period": "custom", "start_date": "2026-10-29T10:00Z", "end_date": "2026-10-29T11:00Z"}
        ).json()
        assert custom["incidents_resolved"] == 1 and custom["total_saved_rub"] == 366.77
        assert client.get(url, params={"run_id": "all"}).status_code == 422
        assert client.get(url, params={"run_id": "99999999"}).status_code == 404
        conn.execute("update sim_state set current_run_id=null where id=1")
        empty = client.get(url).json()
        assert empty["run_id"] is None and empty["total_saved_rub"] == 0 and empty["items"] == []
        assert client.get(url, params={"run_id": rid}).json()["incidents_resolved"] == 4
        # Повторное чтение не меняет экономику и не добавляет кейсы.
        assert conn.execute("select count(*) from incident_economics where run_id=%s", (rid,)).fetchone()[0] == 4
        assert conn.execute("select count(*) from incidents where id=%s", (missing,)).fetchone()[0] == 1


@pytest.mark.asyncio
async def test_recompute_notifies_only_on_change(seeded: str) -> None:
    import json

    from app.realtime.notify import route

    dsn = seeded.replace("postgresql+psycopg://", "postgresql://")
    async with await psycopg.AsyncConnection.connect(dsn, autocommit=True, row_factory=dict_row) as conn:
        messages: list[str] = []

        class RecordingConnection:
            def cursor(self, **kwargs: Any) -> Any:
                return conn.cursor(**kwargs)

            async def execute(self, query: str, args: Any = ()) -> Any:
                if "pg_notify('metrics'" in query:
                    messages.append(args[0])
                return await conn.execute(query, args)

        recording: Any = RecordingConnection()
        row = await (await conn.execute("select id from incidents order by id limit 1")).fetchone()
        assert row is not None
        iid = row["id"]
        await dcltv.compute_incident(recording, iid)
        assert len(messages) == 1
        payload = json.loads(messages[0])
        assert payload["type"] == "FINANCIAL_IMPACT_UPDATED"
        assert payload["data"]["incident_id"] == iid
        assert route("metrics", messages[0]) == ("metrics", payload["type"], payload["data"], payload["run_id"])
        await dcltv.compute_incident(recording, iid)
        assert len(messages) == 1
        stored = await (
            await conn.execute(
                "select e.computed_at >= i.updated_at as fresh from incident_economics e join incidents i on i.id=e.incident_id where i.id=%s",
                (iid,),
            )
        ).fetchone()
        assert stored == {"fresh": True}


@pytest.mark.asyncio
async def test_resolved_without_gift_updates_economics(seeded: str, monkeypatch: pytest.MonkeyPatch) -> None:
    from unittest.mock import AsyncMock

    from app.agent import gifts
    from app.agent.tools.base import ToolContext
    from app.agent.tools.write import update_incident

    no_gift = AsyncMock(return_value=0)
    monkeypatch.setattr(gifts, "issue_automatic", no_gift)
    dsn = seeded.replace("postgresql+psycopg://", "postgresql://")
    async with await psycopg.AsyncConnection.connect(dsn, autocommit=True) as conn:
        row = await (await conn.execute("select id,run_id from incidents order by id limit 1")).fetchone()
        assert row is not None
        iid, rid = row
        await conn.execute("update incidents set status='verifying',outcome_class=null where id=%s", (iid,))
        ctx = ToolContext(conn, run_id=rid, agent_run_id=0, sim_time=dt.datetime(2026, 11, 9, 9, tzinfo=dt.UTC))
        await update_incident(ctx, iid, "resolved", "регрессия: без подарка")
        no_gift.assert_awaited_once()
        result = await (
            await conn.execute(
                "select e.incident_id, i.status, e.computed_at >= i.updated_at from incident_economics e join incidents i on i.id=e.incident_id where i.id=%s",
                (iid,),
            )
        ).fetchone()
        assert result == (iid, "resolved", True)
