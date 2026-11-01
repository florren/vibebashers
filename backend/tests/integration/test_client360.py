"""T-091: реальный read API, сим-время, изоляция, закрытие счёта и истинные статусы подарков."""

from __future__ import annotations

import datetime as dt

import psycopg
import pytest
from fastapi.testclient import TestClient
from psycopg.types.json import Jsonb

from app.config import get_settings
from app.ingest.normalizer import create_signal, from_api_signal
from app.main import create_app
from tests.helpers import dsn, new_run

pytestmark = pytest.mark.integration


async def test_client360_scoped_history_and_simulated_operation_window(seeded: str, monkeypatch) -> None:
    monkeypatch.setenv("DATABASE_URL", seeded)
    get_settings.cache_clear()
    stamp = dt.datetime(2001, 1, 10, 12, tzinfo=dt.UTC)
    async with await psycopg.AsyncConnection.connect(dsn(seeded)) as conn:
        client_id = (await (await conn.execute("select id from clients order by id limit 1")).fetchone())[0]
        base = (
            await (await conn.execute("select id from sim_runs where kind='baseline' order by id limit 1")).fetchone()
        )[0]
        product = (
            await (
                await conn.execute("select product_code from client_products where client_id=%s limit 1", (client_id,))
            ).fetchone()
        )[0]
        system, error = await (
            await conn.execute("select system_code,code from error_codes order by code limit 1")
        ).fetchone()
        gift = (await (await conn.execute("select code from gift_catalog order by code limit 1")).fetchone())[0]
        await conn.execute("update sim_state set sim_time=%s where id=1", (stamp,))
        old = await new_run(conn, "old customer history")
        current = await new_run(conn, "current customer history")
        await conn.execute(
            "update clients set contacts=%s,is_active=false where id=%s",
            (
                Jsonb(
                    {
                        "phone": "+7 900 001-22-33",
                        "email": "guest@example.com",
                        "token": "must-not-leak",
                        "preferred": "chat",
                    }
                ),
                client_id,
            ),
        )
        fault = (
            await (
                await conn.execute(
                    "insert into faults(run_id,system_code,error_code,started_sim) values (%s,%s,%s,%s) returning id",
                    (current, system, error, stamp - dt.timedelta(hours=2)),
                )
            ).fetchone()
        )[0]

        async def operation(run, age, status="success", fault_id=None):
            return (
                await (
                    await conn.execute(
                        "insert into operations(run_id,client_id,product_code,op_type,system_path,status,amount_rub,fault_id,started_sim) values (%s,%s,%s,'transfer',%s,%s,450,%s,%s) returning id",
                        (run, client_id, product, [system], status, fault_id, stamp - dt.timedelta(hours=age)),
                    )
                ).fetchone()
            )[0]

        base_op = await operation(base, 2)
        old_op = await operation(old, 1)
        failed = await operation(current, 1, "failed", fault)
        too_old = await operation(current, 73)
        future = await operation(current, -1)
        for run, state, minutes in [(base, "calm", 60), (old, "waiting", 30), (current, "churned", 15)]:
            await conn.execute(
                "insert into client_states(run_id,client_id,state,since_sim,trigger,care_score,hazard) values (%s,%s,%s,%s,'timer',0.250,0.1000)",
                (run, client_id, state, stamp - dt.timedelta(minutes=minutes)),
            )
        signal_ids = {}
        for run in (old, current):
            msg = from_api_signal(
                {
                    "channel_code": "chat",
                    "client_id": client_id,
                    "text": "Синтетическое обращение для проверки истории",
                },
                origin="jury",
            )
            result = await create_signal(conn, msg, source_code="api", run_id=run, sim_time=stamp, emit_event=False)
            assert result["status"] == "accepted"
            signal_ids[run] = result["signal_id"]
        closure = (
            await (
                await conn.execute(
                    "insert into incidents(run_id,title,incident_type,team_code,complexity,criticality,priority,status,created_by,created_sim,sla_due_sim,take_due_sim) values (%s,'Закрытие счёта','account_closure','team_cx','medium','medium',3,'closed','behavior_model',%s,%s,%s) returning id",
                    (current, stamp, stamp, stamp),
                )
            ).fetchone()
        )[0]
        await conn.execute(
            "insert into churn_events(run_id,client_id,churn_sim,reason,closure_incident_id) values (%s,%s,%s,'unresolved_incident',%s)",
            (current, client_id, stamp, closure),
        )
        gift_ids = {}
        for status, hitl in [
            ("open", False),
            ("open", True),
            ("approved", True),
            ("changed", True),
            ("done", False),
            ("rejected", False),
            ("cancelled", False),
        ]:
            key = (status, hitl)
            gift_ids[key] = (
                await (
                    await conn.execute(
                        "insert into tasks(run_id,kind,client_id,incident_id,payload,status,requires_hitl,created_sim) values (%s,'gift',%s,%s,%s,%s,%s,%s) returning id",
                        (
                            current,
                            client_id,
                            closure,
                            Jsonb({"gift": {"gift_code": gift, "points": 300}, "when": "now"}),
                            status,
                            hitl,
                            stamp,
                        ),
                    )
                ).fetchone()
            )[0]
        old_gift = (
            await (
                await conn.execute(
                    "insert into tasks(run_id,kind,client_id,payload,status,created_sim) values (%s,'gift',%s,%s,'done',%s) returning id",
                    (old, client_id, Jsonb({"gift": {"gift_code": gift}}), stamp),
                )
            ).fetchone()
        )[0]
        await conn.commit()
    try:
        with TestClient(create_app()) as client:
            path = f"/api/clients/{client_id}/360"
            response = client.get(path)
            assert response.status_code == 200, response.text
            data = response.json()
            assert {op["id"] for op in data["operations"]} == {base_op, failed}
            assert all(op["id"] not in (old_op, too_old, future) for op in data["operations"])
            assert next(op for op in data["operations"] if op["id"] == failed)["fault_id"] == fault
            assert data["current_state"]["state"] == "churned"
            assert data["current_state"]["care_score"] == 0.25
            assert {item["run_id"] for item in data["state_history"]} <= {base, current}
            assert signal_ids[current] in {item["id"] for item in data["signals"]}
            assert signal_ids[old] not in {item["id"] for item in data["signals"]}
            assert any(
                item["id"] == closure and item["incident_type"] == "account_closure" for item in data["incidents"]
            )
            assert data["psychotype"]["communication_hint_ru"]
            assert data["contacts"] == {"phone": "***", "email": "***", "preferred": "chat"}
            ids = {item["id"] for item in data["gifts"]}
            assert {
                gift_ids[("open", False)],
                gift_ids[("approved", True)],
                gift_ids[("changed", True)],
                gift_ids[("done", False)],
            } <= ids
            assert (
                not {gift_ids[("open", True)], gift_ids[("rejected", False)], gift_ids[("cancelled", False)], old_gift}
                & ids
            )
            all_runs = client.get(path, params={"run_id": "all"}).json()
            assert old_op in {op["id"] for op in all_runs["operations"]}
            assert old_gift in {item["id"] for item in all_runs["gifts"]}
            historical = client.get(path, params={"run_id": old}).json()
            assert {op["id"] for op in historical["operations"]} == {base_op, old_op}
            assert historical["current_state"]["state"] == "waiting"
            assert not any(item["id"] == closure for item in historical["incidents"])
            assert client.get(path, params={"ops_hours": 168}).json()["operations"]
            assert client.get(path, params={"ops_hours": 0}).status_code == 422
            assert client.get(path, params={"run_id": "bad"}).status_code == 422
            assert client.get(path, params={"run_id": "-1"}).status_code == 422
            assert client.get(path, params={"run_id": "999999"}).status_code == 404
            assert client.get("/api/clients/999999/360").status_code == 404
            with psycopg.connect(dsn(seeded)) as conn:
                representatives = conn.execute(
                    "select distinct on (psychotype_code) id,psychotype_code from clients order by psychotype_code,id"
                ).fetchall()
            hints = set()
            for sample_id, code in representatives:
                style = client.get(f"/api/clients/{sample_id}/360").json()["psychotype"]
                assert style["code"] == code
                assert style["communication_hint_ru"] != "Объясните следующий шаг и согласуйте удобный канал связи."
                hints.add(style["communication_hint_ru"])
            assert len(hints) == len(representatives)
            with psycopg.connect(dsn(seeded)) as conn:
                conn.execute("update sim_state set current_run_id=null where id=1")
            baseline_only = client.get(path).json()
            assert {op["id"] for op in baseline_only["operations"]} == {base_op}
            assert {item["run_id"] for item in baseline_only["state_history"]} <= {base}
    finally:
        get_settings.cache_clear()
