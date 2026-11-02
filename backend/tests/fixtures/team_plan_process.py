"""Отдельный Simulator без providers: SIGKILL barrier до первого действия команды."""

from __future__ import annotations

import asyncio
import json
import os
from pathlib import Path

from app.sim.engine import Simulator
from app.sim.teams import _plan_blob


async def main():
    sim = Simulator(dsn=os.environ["DATABASE_URL"])
    await sim.load_state()
    sim._intensities = dict.fromkeys(("op", "fault", "client_error", "signal_noise"), 0)
    world = await sim._ensure_world()
    if os.environ["TEAM_PLAN_PHASE"] == "prime":
        await sim.step(1)
    plans = {str(iid): _plan_blob(plan) for iid, plan in sim.world.team_emulator.plans.items()}
    assert len(plans) == 1
    state = sim.rng.dump_state()
    clock = sim.clock.sim_time
    conn = await sim.connect()
    actions = await (
        await conn.execute("select action,action_sim from team_actions where run_id=%s order by id", (sim.run_id,))
    ).fetchall()
    assert not actions
    result = {"stage": "ready", "plans": plans, "rng": state, "clock": clock.isoformat()}
    output = Path(os.environ["TEAM_PLAN_OUTPUT"])
    if os.environ["TEAM_PLAN_PHASE"] == "prime":
        await conn.rollback()
        output.write_text(json.dumps(result, sort_keys=True))
        while True:
            await asyncio.sleep(60)
    take_at = next(
        step.at for plan in world.team_emulator.plans.values() for step in plan.steps if step.action == "take"
    )
    await sim.step((take_at - clock).total_seconds() / 60)
    actions = await (
        await conn.execute("select action,action_sim from team_actions where run_id=%s order by id", (sim.run_id,))
    ).fetchall()
    assert actions and actions[0] == ("take", take_at)
    assert sim.rng.dump_state() == state
    assert sim.clock.sim_time == take_at
    result.update(stage="complete", action=actions[0][0], action_sim=actions[0][1].isoformat())
    output.write_text(json.dumps(result, sort_keys=True))
    await conn.close()


asyncio.run(main())
