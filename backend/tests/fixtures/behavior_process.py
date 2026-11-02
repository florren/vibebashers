"""Изолированный production Simulator: prime barrier, kill/restart и digest."""

from __future__ import annotations

import asyncio
import datetime as dt
import hashlib
import json
import os
import uuid
from pathlib import Path

from app.sim.behavior.policy import DemoPolicy
from app.sim.behavior.runtime import POLICY_PATH
from app.sim.engine import Simulator
from app.sim.generators import PendingSignal

OUTPUT = Path(os.environ["BEHAVIOR_OUTPUT"])
PHASE = os.environ["BEHAVIOR_PHASE"]
URL = os.environ["DATABASE_URL"]
WALL_STARTED = dt.datetime.now(dt.UTC)


async def digest(sim):
    conn = await sim.connect()
    run = sim.run_id
    queries = {
        "clock": ("select sim_time,day_no,rng_state,current_run_id,running from sim_state where id=1", ()),
        "runtime": (
            "select client_id,episode_no,state_id,opened_sim,closed_sim,care_snapshot,first_complaint_sim,patience_due_sim,next_hazard_sim,repeat_count,sla_breached,silent_decline,policy_hash from behavior_runtime where run_id=%s order by client_id",
            (run,),
        ),
        "states": (
            "select client_id,state,since_sim,trigger,care_score,hazard,signal_id,incident_id,is_current from client_states where run_id=%s order by id",
            (run,),
        ),
        "signals": (
            "select id,channel_code,client_id,text,received_sim,source_operation_id,source_fault_id,classification,flags,meta from signals where run_id=%s order by id",
            (run,),
        ),
        "events": ("select event_type,payload,sim_time from sim_events where run_id=%s order by id", (run,)),
        "work": (
            "select client_id,episode_no,kind,source_id,due_sim,status,consumed_sim from behavior_work where run_id=%s order by id",
            (run,),
        ),
        "world_timers": (
            "select client_id,due_sim,client_snapshot,signal_type,product_code,source_operation_id,source_fault_id,error_code,system_code,correlation_id,consumed_sim from behavior_pending_signals where run_id=%s order by id",
            (run,),
        ),
        "receipts": (
            "select client_id,source_kind,source_id,action,consumed_sim from behavior_receipts where run_id=%s order by client_id,source_kind,source_id,action",
            (run,),
        ),
        "ticks": (
            "select client_id,logical_tick_sim from behavior_tick_receipts where run_id=%s order by client_id,logical_tick_sim",
            (run,),
        ),
    }
    result = {}
    real_clock = {"events_raw_sha256": None, "validated_review_fields": []}
    for name, (sql, args) in queries.items():
        rows = await (await conn.execute(sql, args)).fetchall()
        if name == "events":
            real_clock["events_raw_sha256"] = hashlib.sha256(
                json.dumps(rows, sort_keys=True, default=str, ensure_ascii=False).encode()
            ).hexdigest()
            normalized = []
            for kind, payload, at in rows:
                if kind == "review.posted":
                    stamp = dt.datetime.fromisoformat(payload["posted_at"])
                    assert stamp.utcoffset() is not None
                    native = (
                        await (
                            await conn.execute(
                                "select posted_at from external_posts where id=%s and run_id=%s",
                                (payload["post_id"], run),
                            )
                        ).fetchone()
                    )[0]
                    assert stamp == native and WALL_STARTED <= stamp <= dt.datetime.now(dt.UTC)
                    real_clock["validated_review_fields"].append(
                        {
                            "event_type": kind,
                            "post_id": payload["post_id"],
                            "native_equal": True,
                            "within_wall_bounds": True,
                        }
                    )
                    # Единственная разрешённая нормализация: declared wall field.
                    # Все прочие payload поля, SimTime, IDs и count сравниваются.
                    payload = payload | {"posted_at": "<declared-real-time>"}
                normalized.append((kind, payload, at))
            rows = normalized
        result[name] = {
            "count": len(rows),
            "sha256": hashlib.sha256(
                json.dumps(rows, sort_keys=True, default=str, ensure_ascii=False).encode()
            ).hexdigest(),
        }
    await conn.rollback()
    return result, real_clock


async def main():
    policy = DemoPolicy.load(POLICY_PATH, validation_only=True)
    sim = Simulator(dsn=URL, behavior_policy=policy)
    await sim.load_state()
    sim._intensities = {"op": 0, "fault": 0, "client_error": 0, "signal_noise": 0}
    conn = await sim.connect()
    run = sim.run_id
    assert run is not None
    if PHASE == "prime":
        world = await sim._ensure_world()
        client = (
            await (
                await conn.execute(
                    "select client_id from operations where run_id=%s and status='failed' order by id limit 1", (run,)
                )
            ).fetchone()
        )[0]
        person = next(item for item in world.clients if item.id == client)
        person.channel_weights = {"chat": 1.0}
        due = sim.clock.sim_time + dt.timedelta(minutes=10)
        world.pending.append(
            PendingSignal(
                due,
                person,
                "client_error",
                "deposit",
                None,
                None,
                None,
                None,
                uuid.uuid5(uuid.NAMESPACE_URL, f"t161-process/{run}/{client}"),
            )
        )
        await sim.control("pause")
        await sim.step(1)
        complaint = (
            await (
                await conn.execute("select due_sim from behavior_work where run_id=%s and kind='complaint'", (run,))
            ).fetchone()
        )[0]
        target = max(due, complaint)
        semantic, wall = await digest(sim)
        OUTPUT.write_text(
            json.dumps(
                {"stage": "ready", "target": target.isoformat(), "digest": semantic, "declared_wall_clock": wall}
            )
        )
        gate = OUTPUT.with_suffix(".continue")
        while not gate.exists():
            await asyncio.sleep(0.05)
    else:
        assert sim.run_status == "paused" and not sim.clock.running
        before, _ = await digest(sim)
        assert before["signals"]["count"] == 0  # Ни load_state, ни wall time не будят таймеры.
        target = dt.datetime.fromisoformat(os.environ["BEHAVIOR_TARGET"])
    await sim.step((target - sim.clock.sim_time).total_seconds() / 60)
    result, wall = await digest(sim)
    assert result["signals"]["count"] == 2
    OUTPUT.write_text(json.dumps({"stage": "complete", "digest": result, "declared_wall_clock": wall}))
    await conn.close()


asyncio.run(main())
