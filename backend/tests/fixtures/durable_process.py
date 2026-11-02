"""Изолированный процесс T-041: настоящий lifespan/API/agent, только synthetic DB/mock."""

import asyncio
import json
import os
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import psycopg
from fastapi.testclient import TestClient

from app.agent import graph
from app.ingest import sources
from app.main import create_app


async def idle_poll(stop):
    # Внешние ingest источники не относятся к проверке рестарта агента.
    await stop.wait()


sources.polling_worker = idle_poll
phase = os.environ["DURABLE_PHASE"]
output = Path(os.environ["DURABLE_OUTPUT"])
dsn = os.environ["DATABASE_URL"].replace("postgresql+psycopg://", "postgresql://")
close = graph.NODES["close"]


async def blocked_close(state, deps):
    if "T041 durable-process-proof" in state["signal"]["text"]:
        output.with_suffix(".blocked").write_text(json.dumps({"agent_run_id": state["agent_run_id"]}))
        await asyncio.Event().wait()
    return await close(state, deps)


if phase == "crash":
    graph.NODES["close"] = blocked_close

with TestClient(create_app()) as client, psycopg.connect(dsn, autocommit=True) as db:
    if phase == "crash":
        created = client.post("/api/sim/runs", json={"kind": "free", "label": "T041 process", "seed": 42})
        assert created.status_code == 202, created.text
        rid = created.json()["id"]
        assert client.post("/api/sim/control", json={"action": "pause"}).status_code == 200
        opid, cid, amount, fee = db.execute(
            "select o.id,o.client_id,o.amount_rub,o.fee_amount from operations o join clients c on c.id=o.client_id "
            "where o.error_code='PROC-QR-FEE-CHARGED' and c.segment_code='mass' and o.fee_amount>0 "
            "order by o.started_sim desc limit 1"
        ).fetchone()
        executor = ThreadPoolExecutor(max_workers=1)
        submission = executor.submit(
            client.post,
            "/api/signals",
            json={
                "channel_code": "chat",
                "client_id": cid,
                "compare_with_mock": False,
                "text": f"Оплатил по QR {amount} рублей, списали комиссию {fee} руб. СБП бесплатно, верните комиссию. T041 durable-process-proof",
            },
        )
        for _ in range(600):
            if output.with_suffix(".blocked").exists():
                break
            time.sleep(0.05)
        else:
            raise AssertionError("close barrier не достигнут")
        assert client.post(f"/api/sim/runs/{rid}/resume").status_code == 200
        arid = json.loads(output.with_suffix(".blocked").read_text())["agent_run_id"]
        sid = db.execute("select signal_id from agent_runs where id=%s", (arid,)).fetchone()[0]
        output.write_text(json.dumps({"run_id": rid, "signal_id": sid, "operation_id": opid}))
        while True:
            time.sleep(1)
    else:
        previous = json.loads(output.read_text())
        rid, sid = previous["run_id"], previous["signal_id"]
        status, sim_time, resumed = db.execute(
            "select r.status,st.sim_time,r.resumed_count from sim_state st join sim_runs r on r.id=st.current_run_id"
        ).fetchone()
        assert status == ("interrupted" if phase == "recover" else "paused"), status
        if phase == "recover":
            assert db.execute("select status from agent_runs where signal_id=%s", (sid,)).fetchone()[0] == "interrupted"
        response = client.post(f"/api/sim/runs/{rid}/resume")
        assert response.status_code == 200, response.text
        for _ in range(600):
            row = db.execute("select id,outcome,total_tokens from agent_runs where signal_id=%s", (sid,)).fetchone()
            if row and row[1] == "completed":
                break
            time.sleep(0.05)
        else:
            raise AssertionError("agent recovery не завершён")
        assert (
            db.execute(
                "select count(*) from ledger_entries where operation_id=%s and kind='refund'",
                (previous["operation_id"],),
            ).fetchone()[0]
            == 1
        )
        assert db.execute("select count(*) from agent_runs where signal_id=%s", (sid,)).fetchone()[0] == 1
        assert (
            db.execute("select count(*) from agent_steps where run_id=%s and node='normalize'", (row[0],)).fetchone()[0]
            == 1
        )
        output.with_suffix(f".{phase}").write_text(
            json.dumps(
                {
                    "status_before": status,
                    "sim_time_before": sim_time.isoformat(),
                    "agent_run_id": row[0],
                    "tokens": row[2],
                    "resumed_before": resumed,
                    "resumed_after": response.json()["resumed_count"],
                }
            )
        )
