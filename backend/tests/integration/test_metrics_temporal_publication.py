"""T256/T041: native delayed positive/negative после двух контроллеров, без clock rewind."""

import asyncio

import psycopg
import pytest
from psycopg.types.json import Jsonb

from app.agent.graph import load_deps
from app.contracts.registry import deref, validate
from app.economics.calibration import PIPELINE
from app.ingest.normalizer import create_signal, from_api_signal
from app.llm.mock import MockProvider
from app.sim.behavior.signals import record_classified
from tests.helpers import MOCK_PROFILE, dsn, mock_chain
from tests.integration.test_behavior_effect_time import load_sim
from tests.integration.test_behavior_runtime import setup
from tests.integration.test_cabinet_api import fingerprint
from tests.integration.test_metrics_cx_index import cx_db as cx_db
from tests.integration.test_metrics_cx_index import metrics_client as metrics_client
from tests.integration.test_metrics_cx_index import sql as sql


@pytest.mark.asyncio
@pytest.mark.parametrize("sentiment", ["positive", "negative"])
async def test_native_stale_start_cannot_publish_future_classification_as_past(
    cx_db, sql, metrics_client, monkeypatch, sentiment
):
    saved = sql.execute(
        "SELECT sim_time,current_run_id,seed,rng_state,running,day_no FROM sim_state WHERE id=1"
    ).fetchone()
    entered, release = asyncio.Event(), asyncio.Event()

    class Delayed(MockProvider):
        async def complete_structured(self, *args, **kwargs):
            entered.set()
            await release.wait()
            value, usage, meta = await super().complete_structured(*args, **kwargs)
            value["sentiment"] = sentiment
            return value, usage, meta

    run = new = None
    actual = stale = fresh = task = None
    try:
        async with await psycopg.AsyncConnection.connect(dsn(cx_db)) as conn:
            run, client, t0, actual = await setup(conn, monkeypatch, cx_db)
            signal = (
                await create_signal(
                    conn,
                    from_api_signal(
                        {"channel_code": "chat", "client_id": client, "text": "Учебное сообщение для временной границы"}
                    ),
                    source_code="api",
                    run_id=run,
                    sim_time=t0,
                    emit_event=False,
                )
            )["signal_id"]
            agent = (
                await (
                    await conn.execute(
                        "INSERT INTO agent_runs(kind,sim_run_id,signal_id,client_id,started_sim,prompt_version) "
                        "VALUES('agent',%s,%s,%s,%s,'T256 native temporal') RETURNING id",
                        (run, signal, client, t0),
                    )
                ).fetchone()
            )[0]
            deps = await load_deps(
                conn, chain=mock_chain(), profile=MOCK_PROFILE, run_id=run, agent_run_id=agent, sim_time=t0
            )
            await conn.commit()
            task = asyncio.create_task(
                Delayed().complete_structured(
                    [{"role": "user", "content": "Учебное сообщение для временной границы"}],
                    deref("agent/classification"),
                    MOCK_PROFILE,
                    timeout_s=1,
                )
            )
            await asyncio.wait_for(entered.wait(), 2)
            await actual.step(3)
            stale = await load_sim(cx_db)
            await actual.step(2)
            t5 = actual.clock.sim_time
            release.set()
            value, _, _ = await asyncio.wait_for(task, 2)
            assert not validate(value, "agent/classification")
            await conn.execute("UPDATE signals SET classification=%s WHERE id=%s", (Jsonb(value), signal))
            await deps.record_step(
                "classify",
                "ok",
                {},
                value
                | {
                    "score_pipeline": PIPELINE,
                    "churn_predicted_sim": t0.isoformat(),
                },
            )
            await record_classified(deps.ctx, signal)
            await conn.commit()
            receipts = await (
                await conn.execute(
                    "SELECT observed_sim FROM behavior_agent_intents WHERE run_id=%s",
                    (run,),
                )
            ).fetchall()
            assert receipts == ([] if sentiment == "positive" else [(t5,)])
            assert t0 < stale.clock.sim_time < t5
            before = fingerprint(sql)
            with pytest.raises(ValueError, match="устарел"):
                await stale.control(
                    "start", label="T256 rejected stale", kind="free", reset_mode="counters", start_paused=True
                )
            assert fingerprint(sql) == before
            assert sql.execute("SELECT current_run_id,sim_time FROM sim_state WHERE id=1").fetchone() == (run, t5)
            fresh = await load_sim(cx_db)
            await fresh.control(
                "start", label="T256 fresh native", kind="free", reset_mode="counters", start_paused=True
            )
            new = fresh.run_id
            assert new != run and fresh.clock.sim_time == t5
            assert sql.execute("SELECT finished_sim FROM sim_runs WHERE id=%s", (run,)).fetchone() == (t5,)
            assert sql.execute("SELECT started_sim FROM sim_runs WHERE id=%s", (new,)).fetchone() == (t5,)
            before = fingerprint(sql)
            for endpoint in ("cx-index", "overview"):
                for requested in (str(run), "current", "all"):
                    response = metrics_client.get("/api/metrics/" + endpoint, params={"run_id": requested})
                    assert response.status_code == 200, response.text[:300]
                    result = response.json()
                    assert result["as_of_sim"].replace("Z", "+00:00") == t5.isoformat()
                    if endpoint == "cx-index" and requested == str(run):
                        assert result["components"]["negativity"]["known"] == 1
                        assert result["components"]["negativity"]["value"] == value["negativity"]
                    if requested == "current":
                        assert result["scope"]["resolved_run_id"] == new
                        if endpoint == "overview":
                            assert result["kpi"]["signals_today"] == 0
            assert fingerprint(sql) == before
    finally:
        release.set()
        if task is not None:
            await asyncio.gather(task, return_exceptions=True)
        for sim in (actual, stale, fresh):
            if sim is not None:
                await sim.conn.close()
        sql.execute(
            "UPDATE sim_state SET sim_time=%s,current_run_id=%s,seed=%s,rng_state=%s,running=%s,day_no=%s WHERE id=1",
            (*saved[:3], Jsonb(saved[3]), *saved[4:]),
        )
        for rid in (new, run):
            if rid is not None:
                sql.execute("DELETE FROM sim_runs WHERE id=%s", (rid,))
