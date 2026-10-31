"""Движок симуляции (T-031): tick-цикл asyncio, персистентность sim_state, управление (start/pause/resume/stop/step/reset_day/
set_speed/set_preset/jump_to), публикация sim.tick в WS. Один движок на процесс: app.state.sim."""

from __future__ import annotations

import asyncio
import contextlib
import copy
import datetime as dt
from typing import Any

import psycopg

from app.db.session import psycopg_dsn
from app.demo.settings import configuration, ensure, save
from app.logging import get_logger
from app.realtime.hub import hub
from app.sim import baseline as baseline_svc
from app.sim import runs as run_svc
from app.sim.clock import MSK, PRESETS, SimClock, is_working_day
from app.sim.events import EventBus
from app.sim.generators import World
from app.sim.rng import SimRng
from app.sim.sla import SlaEngine
from app.sim.teams import TeamEmulator

log = get_logger(__name__)
REAL_TICK_S = 0.5
MAX_BATCH_MIN = 60.0  # за один тик генерируем не больше часа сим-времени (защита от «догоняния» после паузы)


class Simulator:
    def __init__(self, seed: int = 42, dsn: str | None = None) -> None:
        self.full_execution = False
        self.seed = seed
        self.dsn = dsn
        self.clock = SimClock(sim_time=dt.datetime(2026, 11, 9, 9, 0, tzinfo=MSK))
        self.rng = SimRng(seed)
        self.conn: psycopg.AsyncConnection[Any] | None = None
        self.world: World | None = None
        self.run_id: int | None = None
        self.run_status: str | None = None
        self._task: asyncio.Task[None] | None = None
        self._lock = asyncio.Lock()
        self._last_minute_published: dt.datetime | None = None
        self.stats: dict[str, int] = {"ticks": 0, "ops": 0, "faults": 0, "client_errors": 0, "signals": 0}

    # --- жизненный цикл --------------------------------------------------------------------------------------------
    async def connect(self) -> psycopg.AsyncConnection[Any]:
        if self.conn is None or self.conn.closed:
            self.conn = await psycopg.AsyncConnection.connect(psycopg_dsn(self.dsn), autocommit=False)
        return self.conn

    async def load_state(self) -> None:
        conn = await self.connect()
        cur = await conn.execute(
            "select sim_time, day_no, speed, running, seed, current_run_id, rng_state, last_tick_at, intensities from sim_state where id = 1"
        )
        row = await cur.fetchone()
        if not row:
            await conn.execute(
                "insert into sim_state (id, sim_time, day_no, speed, running, seed, phase) values (1, %s, 0, %s, false, %s, 'morning') on conflict (id) do nothing",
                (self.clock.sim_time, PRESETS["day_12min"], self.seed),
            )
            await conn.commit()
            return
        sim_time, day_no, speed, running, seed, run_id, rng_state, last_tick_at, intensities = row
        self.clock = SimClock(sim_time=sim_time, speed=float(speed), running=False, day_no=int(day_no))
        self.seed = int(seed)
        self.rng = SimRng(self.seed)
        self.rng.load_state(rng_state)
        self.run_id = int(run_id) if run_id else None
        if self.run_id:
            r = await run_svc.get_run(conn, self.run_id)
            self.run_status = r["status"] if r else None
            if running and r and r["status"] == "running":  # приложение упало на ходу → interrupted (T-041)
                await run_svc.set_run_status(conn, self.run_id, "interrupted")
                self.run_status = "interrupted"
                await conn.execute("update sim_state set running = false where id = 1")
        await conn.commit()
        self._intensities = dict(intensities or {})
        log.info(
            "sim_state_loaded", sim_time=self.clock.sim_time.isoformat(), run_id=self.run_id, status=self.run_status
        )

    async def ensure_live_run(self) -> int:
        """Живой или уже текущий запуск без старта часов и генераторов (ТЗ 4.7).

        Указатель в памяти синхронизируется с БД, чтобы persist не затёр новый live-run.
        Существующие запуски не останавливаются; clock.running, цикл и step не вызываются.
        """
        async with self._lock:
            conn = await self.connect()
            run_id = await run_svc.ensure_live_run(conn)
            if self.run_id != run_id:
                row = await run_svc.get_run(conn, run_id)
                self.run_id = run_id
                self.run_status = row["status"] if row else None
            await conn.commit()
            return run_id

    async def _ensure_world(self) -> World:
        conn = await self.connect()
        if self.run_id is None or self.run_status in ("completed", "stopped", "archived"):
            self.run_id = await run_svc.create_run(
                conn,
                kind="free",
                label=f"Запуск {dt.datetime.now(MSK):%d.%m %H:%M}",
                seed=self.seed,
                sim_time=self.clock.sim_time,
            )
            self.run_status = "running"
            await conn.commit()
        if self.world is None or self.world.run_id != self.run_id:
            self.world = World(conn, EventBus(conn), self.rng, self.run_id, getattr(self, "_intensities", None))
            await self.world.load()
        return self.world

    async def persist(self) -> None:
        conn = await self.connect()
        await conn.execute(
            "update sim_state set sim_time = %s, day_no = %s, speed = %s, running = %s, phase = %s, current_run_id = %s, rng_state = %s::jsonb, last_tick_at = now(), updated_at = now() where id = 1",
            (
                self.clock.sim_time,
                self.clock.day_no,
                self.clock.speed,
                self.clock.running,
                self.clock.phase,
                self.run_id,
                __import__("orjson").dumps(self.rng.dump_state()).decode(),
            ),
        )

    # --- один шаг сим-времени ---------------------------------------------------------------------------------------
    async def step(self, minutes: float) -> None:
        """Продвинуть сим-время на minutes; крупные шаги режутся на блоки ≤ MAX_BATCH_MIN (быстрый прогон генераторов)."""
        while minutes > 1e-9:
            chunk = min(minutes, MAX_BATCH_MIN)
            await self._step_chunk(chunk)
            minutes -= chunk

    async def _step_chunk(self, minutes: float) -> None:
        async with self._lock:
            world = await self._ensure_world()
            conn = await self.connect()
            t0 = self.clock.sim_time
            day_before = self.clock.day_no
            rng_before = self.rng.dump_state()
            stats_before = dict(self.stats)
            pending_before = copy.deepcopy(world.pending)
            faults_before = copy.deepcopy(world.active_faults)
            text_rng_before = world.textgen.rnd.getstate()
            minutes = min(minutes, MAX_BATCH_MIN)
            try:
                self.stats["faults"] += await world.gen_faults(t0, minutes)
                self.stats["ops"] += await world.gen_operations(t0, minutes)
                self.stats["client_errors"] += await world.gen_client_errors(t0, minutes)
                self.clock.sim_time = t0 + dt.timedelta(minutes=minutes)
                if self.clock.sim_time.astimezone(MSK).date() != t0.astimezone(MSK).date():
                    self.clock.day_no += 1
                self.stats["signals"] += await world.flush_signals(self.clock.sim_time, minutes)
                execution = await configuration(conn, self.run_id) if self.run_id else {}
                if not execution.get("enabled"):
                    await world.team_emulator.tick(self.clock.sim_time, world)
                await world.sla_engine.tick(t0, self.clock.sim_time)
                self.stats["ticks"] += 1
                await self.persist()
                await conn.commit()
            except asyncio.CancelledError:
                # Пауза/стоп отменяют незавершённый тик целиком, включая RNG и кеш World.
                await conn.rollback()
                self.clock.sim_time = t0
                self.clock.day_no = day_before
                self.rng.load_state(rng_before)
                self.stats = stats_before
                world.pending = pending_before
                world.active_faults = faults_before
                world.textgen.rnd.setstate(text_rng_before)
                world.team_emulator = TeamEmulator(self.rng, conn, world.bus, world.run_id)
                world.sla_engine = SlaEngine(conn, world.bus, world.run_id)
                await world.team_emulator.load()
                await world.sla_engine.load()
                raise
            except Exception:
                await conn.rollback()
                log.exception("sim_step_failed")
                raise
        await self._publish_tick()

    async def _publish_tick(self) -> None:
        minute = self.clock.sim_time.replace(second=0, microsecond=0)
        if self._last_minute_published == minute:
            return
        self._last_minute_published = minute
        await hub.publish("sim", "sim.tick", self.state_dict(), self.run_id)

    async def _loop(self) -> None:
        while self.clock.running:
            started = asyncio.get_running_loop().time()
            sim_minutes = REAL_TICK_S * self.clock.speed / 60
            try:
                await self.step(sim_minutes)
            except Exception:
                await asyncio.sleep(2)
            elapsed = asyncio.get_running_loop().time() - started
            await asyncio.sleep(max(0.05, REAL_TICK_S - elapsed))

    # --- управление ----------------------------------------------------------------------------------------------------
    async def control(self, action: str, **kw: Any) -> dict[str, Any]:
        conn = await self.connect()
        execution = await configuration(conn, self.run_id) if self.run_id else {}
        if (
            self.run_id is not None
            and execution.get("mode") == "demo"
            and (execution.get("enabled") or (execution.get("status") == "stopped" and action == "resume"))
            and action in ("start", "resume")
            and not kw.get("label")
        ):
            async with self._lock:
                execution.update(status="running", enabled=True)
                await save(conn, self.run_id, execution)
                self.clock.running = True
                self.run_status = "running"
                await run_svc.set_run_status(conn, self.run_id, "running")
                await self.persist()
                await conn.commit()
            await hub.publish("sim", "sim.control", {"action": action, **self.state_dict()}, self.run_id)
            return self.state_dict()
        if execution.get("mode") == "demo" and execution.get("enabled") and action in ("step", "jump_to", "reset_day"):
            raise ValueError("Изолированный сценарий использует событийное время; доступны запуск, пауза и остановка")
        if action == "start":
            if self.run_status in ("stopped", "completed", "archived", None) or self.run_id is None or kw.get("label"):
                async with self._lock:
                    self.run_id = await run_svc.create_run(
                        conn,
                        kind=kw.get("kind") or "free",
                        label=kw.get("label") or f"Запуск {dt.datetime.now(MSK):%d.%m %H:%M}",
                        seed=self.seed,
                        sim_time=self.clock.sim_time,
                        scenario_id=kw.get("scenario_id"),
                        reset_mode=kw.get("reset_mode") or "counters",
                    )
                    self.run_status = "running"
                    self.world = None
                    await conn.commit()
            elif self.run_status in ("paused", "interrupted", "stopped"):
                await run_svc.set_run_status(conn, self.run_id, "running")
                self.run_status = "running"
                await conn.commit()
            if kw.get("start_paused"):
                self.clock.running = False
                if self.run_id:
                    await run_svc.set_run_status(conn, self.run_id, "paused")
                self.run_status = "paused"
            else:
                if self.full_execution and self.run_id:
                    await ensure(conn, self.run_id, running=True)
                    await conn.commit()
                self._start_loop()
        elif action == "resume":
            if self.run_id and self.run_status in ("paused", "interrupted", "stopped"):
                await run_svc.set_run_status(conn, self.run_id, "running")
                self.run_status = "running"
                await conn.commit()
            self._start_loop()
        elif action == "pause":
            await self._stop_loop()
            if self.run_id and self.run_status == "running":
                await run_svc.set_run_status(conn, self.run_id, "paused")
                self.run_status = "paused"
        elif action == "stop":
            await self._stop_loop()
            if self.run_id and self.run_status in ("running", "paused", "interrupted"):
                await run_svc.set_run_status(conn, self.run_id, "stopped", self.clock.sim_time)
                self.run_status = "stopped"
        elif action == "step":
            await self.step(float(kw.get("step_minutes") or 15))
        elif action == "set_speed":
            self.clock.speed = max(0.1, float(kw["speed"]))
        elif action == "set_preset":
            self.clock.set_preset(str(kw["preset"]))
        elif action == "reset_day":
            await self._stop_loop()
            lt = self.clock.sim_time.astimezone(MSK)
            self.clock.sim_time = (lt + dt.timedelta(days=1)).replace(hour=9, minute=0, second=0, microsecond=0)
            self.clock.day_no += 1
            if self.world:
                self.world.pending.clear()
        elif action == "jump_to":
            target = kw["sim_time"]
            if isinstance(target, str):
                target = dt.datetime.fromisoformat(target)
            if target <= self.clock.sim_time:
                raise ValueError("jump_to: только вперёд")
            await self.step((target - self.clock.sim_time).total_seconds() / 60)
        else:
            raise ValueError(f"неизвестное действие: {action}")
        if self.run_id:
            async with self._lock:
                execution = await configuration(conn, self.run_id)
                if not execution and self.full_execution and action in ("start", "resume"):
                    execution = await ensure(conn, self.run_id, running=True)
                if execution:
                    if action in ("start", "resume"):
                        execution.update(enabled=True, status="running")
                    elif action == "pause" and execution.get("enabled"):
                        execution["status"] = "paused"
                    elif action == "stop":
                        execution.update(enabled=False, status="stopped")
                    await save(conn, self.run_id, execution)
        await self.persist()
        await conn.commit()
        await hub.publish("sim", "sim.control", {"action": action, **self.state_dict()}, self.run_id)
        return self.state_dict()

    def _start_loop(self) -> None:
        self.clock.running = True
        if self._task is None or self._task.done():
            self._task = asyncio.create_task(self._loop(), name="sim-loop")

    async def _stop_loop(self) -> None:
        self.clock.running = False
        if self._task and not self._task.done():
            self._task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self._task
        self._task = None

    async def shutdown(self) -> None:
        await self._stop_loop()
        if self.conn and not self.conn.closed:
            with contextlib.suppress(Exception):
                await self.persist()
                await self.conn.commit()
            await self.conn.close()

    async def reload_after_restore(self) -> None:
        """Перечитать sim_state после pg_restore (новое соединение, сброс World)."""
        await self._stop_loop()
        if self.conn and not self.conn.closed:
            with contextlib.suppress(Exception):
                await self.conn.close()
        self.conn = None
        self.world = None
        self._task = None
        await self.load_state()

    # --- состояние (SimState из openapi.yaml) ------------------------------------------------------------------------
    def state_dict(self) -> dict[str, Any]:
        return {
            "sim_time": self.clock.sim_time.isoformat(),
            "day_no": self.clock.day_no,
            "phase": self.clock.phase,
            "speed": self.clock.speed,
            "running": self.clock.running,
            "seed": self.seed,
            "is_working_day": is_working_day(self.clock.sim_time),
            "current_run_id": self.run_id,
            "current_run_status": self.run_status,
            "baseline_available": baseline_svc.info()["available"],
            "stats": self.stats,
        }
