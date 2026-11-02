"""T041: stale controller не переписывает время/RNG того же current run."""

import psycopg
import pytest

from tests.helpers import dsn
from tests.integration.test_behavior_effect_time import load_sim
from tests.integration.test_behavior_runtime import setup
from tests.integration.test_trace_fanout import fingerprints


@pytest.mark.asyncio
@pytest.mark.parametrize("stop_first", [False, True])
async def test_stale_start_cannot_rewind_clock_or_rewrite_previous_run(seeded, monkeypatch, stop_first):
    async with await psycopg.AsyncConnection.connect(dsn(seeded)) as conn:
        run, _, t0, actual = await setup(conn, monkeypatch, seeded)
        stale = None
        try:
            await actual.step(3)
            stale = await load_sim(seeded)
            await actual.step(2)
            t5 = actual.clock.sim_time
            assert t5 > stale.clock.sim_time > t0
            if stop_first:
                await actual.control("stop")
            with psycopg.connect(dsn(seeded), autocommit=True) as sql:
                before = fingerprints(seeded)
                with pytest.raises(ValueError, match="устарел"):
                    await stale.control(
                        "start", label="stale must not create", reset_mode="counters", start_paused=True
                    )
                assert fingerprints(seeded) == before
                for action, arguments in (("stop", {}), ("pause", {}), ("set_speed", {"speed": 10}), ("reset_day", {})):
                    with pytest.raises(ValueError, match="устарел"):
                        await stale.control(action, **arguments)
                    assert fingerprints(seeded) == before
                assert sql.execute("select current_run_id,sim_time from sim_state where id=1").fetchone() == (run, t5)
            # Новый контроллер штатно читает актуальный native state и создаёт run.
            fresh = await load_sim(seeded)
            try:
                await fresh.control("start", label="fresh valid start", reset_mode="counters", start_paused=True)
                assert fresh.run_id != run and fresh.clock.sim_time == t5
                row = await (await conn.execute("select finished_sim from sim_runs where id=%s", (run,))).fetchone()
                assert row == (t5,)
                await conn.commit()
                row = await (
                    await conn.execute("select started_sim from sim_runs where id=%s", (fresh.run_id,))
                ).fetchone()
                assert row == (t5,)
            finally:
                await fresh.conn.close()
        finally:
            await actual.conn.close()
            if stale is not None:
                await stale.conn.close()


@pytest.mark.asyncio
async def test_same_clock_stale_rng_cannot_be_reset_by_new_start(seeded, monkeypatch):
    async with await psycopg.AsyncConnection.connect(dsn(seeded)) as conn:
        run, _, _, actual = await setup(conn, monkeypatch, seeded)
        stale = await load_sim(seeded)
        try:
            actual.rng.random()
            await actual.persist()
            await actual.conn.commit()
            assert actual.clock.sim_time == stale.clock.sim_time
            assert actual.rng.dump_state() != stale.rng.dump_state()
            with psycopg.connect(dsn(seeded), autocommit=True) as sql:
                before = fingerprints(seeded)
                with pytest.raises(ValueError, match="устарел"):
                    await stale.control("start", label="stale RNG must not create", start_paused=True)
                assert fingerprints(seeded) == before
                assert sql.execute("select current_run_id,rng_state from sim_state where id=1").fetchone() == (
                    run,
                    actual.rng.dump_state(),
                )
        finally:
            await actual.conn.close()
            await stale.conn.close()


@pytest.mark.asyncio
async def test_start_rechecks_state_under_row_lock_after_unlocked_preflight(seeded, monkeypatch):
    async with await psycopg.AsyncConnection.connect(dsn(seeded)) as conn:
        run, _, _, actual = await setup(conn, monkeypatch, seeded)
        stale = await load_sim(seeded)
        original = stale._require_current
        after_partner = None

        async def interleave(connection, *, lock=True, check_state=False):
            nonlocal after_partner
            await original(connection, lock=lock, check_state=check_state)
            if not lock and check_state and after_partner is None:
                await actual.step(1)
                after_partner = fingerprints(seeded)

        monkeypatch.setattr(stale, "_require_current", interleave)
        try:
            with pytest.raises(ValueError, match="устарел"):
                await stale.control("start", label="interleaved stale start", start_paused=True)
            assert after_partner is not None and fingerprints(seeded) == after_partner
            assert (
                await (await conn.execute("select current_run_id,sim_time from sim_state where id=1")).fetchone()
            ) == (run, actual.clock.sim_time)
        finally:
            await actual.conn.close()
            await stale.conn.close()


@pytest.mark.asyncio
async def test_stale_pause_cannot_resurrect_stopped_run_at_same_time_and_rng(seeded, monkeypatch):
    async with await psycopg.AsyncConnection.connect(dsn(seeded)) as conn:
        run, _, t0, actual = await setup(conn, monkeypatch, seeded)
        stale = await load_sim(seeded)
        try:
            await actual.control("stop")
            assert actual.clock.sim_time == stale.clock.sim_time and actual.rng.dump_state() == stale.rng.dump_state()
            before = fingerprints(seeded)
            with pytest.raises(ValueError, match="устарел"):
                await stale.control("pause")
            assert fingerprints(seeded) == before
            assert (
                await (await conn.execute("select status,finished_sim from sim_runs where id=%s", (run,))).fetchone()
            ) == ("stopped", t0)
        finally:
            await actual.conn.close()
            await stale.conn.close()


@pytest.mark.asyncio
async def test_stale_shutdown_closes_connection_without_rewinding_current_state(seeded, monkeypatch):
    async with await psycopg.AsyncConnection.connect(dsn(seeded)) as conn:
        run, _, _, actual = await setup(conn, monkeypatch, seeded)
        stale = await load_sim(seeded)
        try:
            await actual.step(1)
            before = fingerprints(seeded)
            await stale.shutdown()
            assert stale.conn.closed
            assert fingerprints(seeded) == before
            assert (
                await (await conn.execute("select current_run_id,sim_time from sim_state where id=1")).fetchone()
            ) == (run, actual.clock.sim_time)
        finally:
            await actual.conn.close()
            if not stale.conn.closed:
                await stale.conn.close()
