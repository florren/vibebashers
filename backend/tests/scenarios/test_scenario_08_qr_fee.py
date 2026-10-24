"""T-174 / сценарий 8: быстрый путь QR-комиссии на mock-кассете (латентность и шаги графа)."""

from __future__ import annotations

import time

import psycopg
import pytest

from app.agent.graph import process_signal
from app.sim import scenarios as sc
from tests.helpers import MOCK_PROFILE, dsn, mock_chain, new_run, sim_now

pytestmark = pytest.mark.integration


async def test_scenario_08_fast_path_on_cassette(seeded: str) -> None:
    scenario = sc.get("qr_fee_public_review")
    assert scenario is not None
    t0 = time.perf_counter()
    async with await psycopg.AsyncConnection.connect(dsn(seeded)) as conn:
        run_id = await new_run(conn, "test qr_fee fast path", scenario_id=scenario["id"])
        now = await sim_now(conn)
        injected = await sc.inject(conn, scenario, run_id, sim_time=now)
        await conn.commit()
        for item in injected:
            state = await process_signal(
                conn, signal_id=item["signal_id"], chain=mock_chain(), profile=MOCK_PROFILE, sim_time=now
            )
            assert state is not None
        res = await sc.evaluate(conn, scenario, run_id)
        steps = await (
            await conn.execute(
                "select s.node from agent_steps s join agent_runs ar on ar.id = s.run_id "
                "where ar.sim_run_id = %s order by s.seq",
                (run_id,),
            )
        ).fetchall()
        nodes = [r[0] for r in steps]
    elapsed = time.perf_counter() - t0
    report = "\n".join(
        f"  {'✓' if c['ok'] else ('·' if c['ok'] is None else '✗')} {c['code']}: {c['detail']}" for c in res["checks"]
    )
    assert res["counts"]["errors"] == 0, report
    assert "act_instant" in nodes, f"ожидали быстрый путь, узлы: {nodes}"
    assert "classify" not in nodes, f"полный граф не должен вызываться: {nodes}"
    assert elapsed <= 10.0, f"цепочка на кассете {elapsed:.1f} с > 10 с"
    failed = [c for c in res["checks"] if c["ok"] is False]
    assert not failed, report
