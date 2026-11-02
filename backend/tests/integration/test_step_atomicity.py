"""T-031/P1: ordinary failure и cancellation не оставляют phantom World IDs."""

from __future__ import annotations

import asyncio
import copy
import datetime as dt
import uuid

import pytest

from app.sim.engine import Simulator
from app.sim.generators import PendingSignal, World
from app.sim.rng import SimRng
from app.sim.sla import SlaEngine

pytestmark = pytest.mark.integration


@pytest.mark.parametrize("cancel", [False, True])
@pytest.mark.parametrize("reload_failure", [False, True])
async def test_failed_tick_restores_time_rng_pending_and_committed_cache_before_retry(
    seeded, monkeypatch, cancel, reload_failure
):
    sim = Simulator(seed=42, dsn=seeded)
    await sim.load_state()
    sim._intensities = dict.fromkeys(("op", "fault", "client_error", "signal_noise"), 0.0)
    await sim.control("start", label="synthetic step rollback", start_paused=True)
    world = await sim._ensure_world()
    conn = await sim.connect()
    now = sim.clock.sim_time
    client = world.by_product["deposit"][0]
    committed_id = (
        await (
            await conn.execute(
                "insert into faults(run_id,system_code,error_code,started_sim,region_codes) "
                "values(%s,'sub_deposits','DEP-TIMEOUT-503',%s,'{}') returning id",
                (sim.run_id, now),
            )
        ).fetchone()
    )[0]
    committed_fault = {
        "id": committed_id,
        "system": "sub_deposits",
        "error_code": "DEP-TIMEOUT-503",
        "started_sim": now,
        "expected_end": now + dt.timedelta(minutes=30),
        "impact": 5,
        "clients": {client.id},
        "corr": uuid.uuid4(),
    }
    world.active_faults = [copy.deepcopy(committed_fault)]
    old_pending = PendingSignal(
        now + dt.timedelta(days=2),
        client,
        "tech_fault",
        "deposit",
        None,
        committed_id,
        "DEP-TIMEOUT-503",
        "sub_deposits",
        uuid.uuid4(),
    )
    world.pending = [old_pending]
    await world.sla_engine.tick(now - dt.timedelta(minutes=1), now)
    await conn.commit()
    cursor_before = world.sla_engine._cursor
    before = (sim.clock.sim_time, sim.clock.day_no, sim.rng.dump_state(), dict(sim.stats))
    data_before = await (
        await conn.execute(
            "select (select count(*) from operations where run_id=%s),"
            "(select count(*) from faults where run_id=%s),(select count(*) from sim_events where run_id=%s)",
            (sim.run_id, sim.run_id, sim.run_id),
        )
    ).fetchone()
    await conn.commit()
    state = {"fail": True, "fail_reload": False}
    failed_ids = []
    error = asyncio.CancelledError if cancel else RuntimeError
    real_load, real_sla_tick = World.load, SlaEngine.tick

    async def load(self):
        if state["fail_reload"]:
            state["fail_reload"] = False
            raise RuntimeError("controlled reload error")
        return await real_load(self)

    async def faults(self, t0, minutes):
        if not state["fail"]:
            return 0
        self.rng.random()
        fid = (
            await (
                await self.conn.execute(
                    "insert into faults(run_id,system_code,error_code,started_sim,region_codes) "
                    "values(%s,'sub_deposits','DEP-TIMEOUT-503',%s,'{}') returning id",
                    (self.run_id, t0),
                )
            ).fetchone()
        )[0]
        failed_ids.append(fid)
        self.active_faults[0].update(impact=99, expected_end=t0 + dt.timedelta(days=9))
        self.active_faults.append({**copy.deepcopy(committed_fault), "id": fid})
        self.pending.append(
            PendingSignal(
                now + dt.timedelta(days=2),
                client,
                "tech_fault",
                "deposit",
                None,
                fid,
                "DEP-TIMEOUT-503",
                "sub_deposits",
                uuid.uuid4(),
            )
        )
        self.team_emulator.done.add((999999, "synthetic-uncommitted", None))
        return 1

    async def operations(self, t0, minutes):
        self.rng.random()
        fault = self.active_faults[-1]
        await self.conn.execute(
            "insert into operations(run_id,client_id,product_code,op_type,system_path,amount_rub,method,"
            "fee_amount,status,error_code,fault_id,started_sim,finished_sim) "
            "values(%s,%s,'deposit','statement',%s,1,'card',0,'failed','DEP-TIMEOUT-503',%s,%s,%s)",
            (self.run_id, client.id, ["sub_deposits"], fault["id"], t0, t0),
        )
        return 1

    async def sla_tick(self, t0, t1):
        if state["fail"]:
            self._cursor = t1
            state["fail_reload"] = reload_failure
            raise error("controlled step error")
        return await real_sla_tick(self, t0, t1)

    monkeypatch.setattr(World, "load", load)
    monkeypatch.setattr(World, "gen_faults", faults)
    monkeypatch.setattr(World, "gen_operations", operations)
    monkeypatch.setattr(SlaEngine, "tick", sla_tick)
    try:
        with pytest.raises(error, match="controlled step error"):
            await sim.step(1)
        assert (sim.clock.sim_time, sim.clock.day_no, sim.rng.dump_state(), sim.stats) == before
        assert sim.world is not world
        assert sim.world.loaded is (not reload_failure)
        assert sim.world.pending == [old_pending]
        assert all(item.source_fault_id not in failed_ids for item in sim.world.pending)
        after = await (
            await conn.execute(
                "select (select count(*) from operations where run_id=%s),"
                "(select count(*) from faults where run_id=%s),(select count(*) from sim_events where run_id=%s)",
                (sim.run_id, sim.run_id, sim.run_id),
            )
        ).fetchone()
        assert after == data_before
        state["fail"] = False
        await sim.step(1)
        assert sim.world.loaded and sim.world.pending == [old_pending]
        assert sim.world.active_faults == [committed_fault]
        assert (999999, "synthetic-uncommitted", None) not in sim.world.team_emulator.done
        assert sim.world.sla_engine._cursor == cursor_before
        assert sim.world.textgen.rnd is sim.rng
        expected_rng = SimRng()
        expected_rng.load_state(before[2])
        expected_rng.random()  # Только успешная operations попытка.
        assert sim.rng.dump_state() == expected_rng.dump_state()
        row = await (await conn.execute("select fault_id from operations where run_id=%s", (sim.run_id,))).fetchone()
        assert row == (committed_id,)
        assert sim.clock.sim_time == now + dt.timedelta(minutes=1)
        assert sim.stats["ops"] == before[3]["ops"] + 1
    finally:
        await sim.shutdown()
