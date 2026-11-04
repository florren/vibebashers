"""Движок симуляции (T-031): tick-цикл asyncio, персистентность sim_state, управление (start/pause/resume/stop/step/reset_day/
set_speed/set_preset/jump_to), публикация sim.tick в WS. Один движок на процесс: app.state.sim."""

from __future__ import annotations

import asyncio
import contextlib
import copy
import datetime as dt
from collections.abc import Awaitable, Callable
from typing import TYPE_CHECKING, Any

import psycopg

from app.db.session import psycopg_dsn
from app.demo.settings import configuration, ensure, save
from app.logging import get_logger
from app.realtime.hub import hub
from app.sim import baseline as baseline_svc
from app.sim import runs as run_svc
from app.sim.behavior.owner import BehaviorOwner
from app.sim.behavior.policy import DemoPolicy
from app.sim.behavior.runtime import capture, configured_policy, effective_policy, prepare_run, require_run
from app.sim.clock import MSK, PRESETS, SimClock, is_working_day
from app.sim.events import EventBus
from app.sim.generators import World
from app.sim.maintenance import start_daemon, writer
from app.sim.rng import SimRng

if TYPE_CHECKING:
    from app.sim.proactive_scenario import Plan

log = get_logger(__name__)
REAL_TICK_S = 0.5
MAX_BATCH_MIN = 60.0  # за один тик генерируем не больше часа сим-времени (защита от «догоняния» после паузы)


class StaleSimulatorError(ValueError):
    """Устаревший контроллер не вправе перезаписывать native state."""


class Simulator:
    def __init__(self, seed: int = 42, dsn: str | None = None, *, behavior_policy: DemoPolicy | None = None) -> None:
        self.before_resume: Callable[[int, dt.datetime], Awaitable[None]] | None = None
        self.after_resume: Callable[[int, dt.datetime], Awaitable[None]] | None = None
        self.full_execution = False
        self.behavior_policy = behavior_policy if behavior_policy is not None else configured_policy()
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
            if running and r and r["status"] == "running":
                if last_tick_at is not None:
                    remaining = (
                        last_tick_at + dt.timedelta(seconds=3 * REAL_TICK_S) - dt.datetime.now(dt.UTC)
                    ).total_seconds()
                    if remaining > 0:
                        await conn.rollback()
                        await asyncio.sleep(remaining)
                        latest = await (await conn.execute("select last_tick_at from sim_state where id=1")).fetchone()
                        if latest and latest[0] != last_tick_at:
                            raise RuntimeError("Другой backend продолжает обновлять ticks; восстановление отклонено")
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
        if self.world is None or self.world.run_id != self.run_id or self.world.conn is not conn:
            old = self.world if self.world is not None and self.world.run_id == self.run_id else None
            self.world = World(
                conn,
                EventBus(conn),
                self.rng,
                self.run_id,
                old.intensities if old is not None else getattr(self, "_intensities", None),
                behavior_policy=await effective_policy(conn, self.run_id, self.behavior_policy),
            )
            if old is not None:
                self.world.pending = old.pending
                self.world.active_faults = old.active_faults
        if not self.world.loaded:
            try:
                from app.sim.team_plans import ensure_runtime

                await ensure_runtime(conn, self.run_id, self.clock.sim_time)
                await self.world.load()
            except BaseException:
                await conn.rollback()
                raise
        return self.world

    async def _require_current(
        self, conn: psycopg.AsyncConnection[Any], *, lock: bool = True, check_state: bool = False
    ) -> None:
        """Контроллер фиксирует current до эффектов; чужой pointer не возвращает."""
        query = (
            "select current_run_id,sim_time,rng_state from sim_state where id=1"
            if check_state
            else "select current_run_id from sim_state where id=1"
        )
        if lock:
            query += " for update"
        row = await (await conn.execute(query)).fetchone()
        if row is None or row[0] != self.run_id:
            await conn.rollback()
            raise StaleSimulatorError("Simulator устарел: загрузите текущий run перед управлением")
        # Один и тот же pointer не доказывает актуальность контроллера: чужой
        # tick мог уже зафиксировать новое время/RNG. Проверка до create_run не
        # позволяет stale start остановить старый run и записать прежние часы.
        if check_state and (row[1] != self.clock.sim_time or (row[2] is not None and row[2] != self.rng.dump_state())):
            await conn.rollback()
            raise StaleSimulatorError("Simulator устарел: загрузите актуальные time/run/RNG перед управлением")
        if check_state:
            status = await (await conn.execute("select status from sim_runs where id=%s", (self.run_id,))).fetchone()
            if (status[0] if status else None) != self.run_status:
                await conn.rollback()
                raise StaleSimulatorError("Simulator устарел: загрузите актуальный status текущего run")

    async def persist(self) -> None:
        conn = await self.connect()
        result = await conn.execute(
            "update sim_state set sim_time = %s, day_no = %s, speed = %s, running = %s, phase = %s, rng_state = %s::jsonb, seed=%s, last_tick_at = now(), updated_at = now() "
            "where id=1 and current_run_id is not distinct from %s",
            (
                self.clock.sim_time,
                self.clock.day_no,
                self.clock.speed,
                self.clock.running,
                self.clock.phase,
                __import__("orjson").dumps(self.rng.dump_state()).decode(),
                self.seed,
                self.run_id,
            ),
        )
        if result.rowcount != 1:
            await conn.rollback()
            raise StaleSimulatorError("Simulator устарел: текущий run изменён, state не сохранён")

    # --- один шаг сим-времени ---------------------------------------------------------------------------------------
    @writer("sim-step")
    async def step(self, minutes: float) -> None:
        """Продвинуть сим-время на minutes; крупные шаги режутся на блоки ≤ MAX_BATCH_MIN (быстрый прогон генераторов)."""
        while minutes > 1e-9:
            chunk = min(minutes, MAX_BATCH_MIN)
            await self._step_chunk(chunk)
            minutes -= chunk

    async def _step_chunk(self, minutes: float) -> None:
        async with self._lock:
            await self._reject_scripted_control()
            await self._step_chunk_locked(minutes)
        await self._publish_tick()

    async def _reject_scripted_control(self) -> None:
        from app.sim.proactive_scenario import prepared

        conn = await self.connect()
        if self.run_id is not None and await prepared(conn, self.run_id) is not None:
            await conn.rollback()
            raise ValueError("Scripted-сценарий владеет часами; дождитесь фаз либо выполните Stop/новый запуск")

    @writer("sim-scripted-prepare")
    async def prepare_scenario(self, spec: Plan) -> None:
        from app.sim.proactive_scenario import prepare

        async with self._lock:
            conn = await self.connect()
            try:
                if self.run_id is None:
                    raise ValueError("Сначала создайте paused scenario run")
                await self._require_current(conn, lock=False)
                await prepare(conn, self.run_id, spec)
                await conn.commit()
            except BaseException:
                await conn.rollback()
                raise

    @writer("sim-scripted-step")
    async def prepared_step(self, run_id: int, before: dt.datetime, target: dt.datetime) -> bool:
        """Exactly-once native target для validated prepared case, без второго clock path."""
        from app.sim.proactive_scenario import ScriptedScenarioError, validate_step

        if before.utcoffset() is None or target.utcoffset() is None:
            raise ScriptedScenarioError("phase_clock_changed")
        minutes = (target - before).total_seconds() / 60
        if not 0 < minutes <= MAX_BATCH_MIN:
            raise ScriptedScenarioError("phase_clock_changed")
        async with self._lock:
            conn = await self.connect()
            try:
                await validate_step(conn, run_id, before, target)
                row = await (
                    await conn.execute(
                        "select st.current_run_id,st.sim_time,st.rng_state,st.running,r.kind,r.status "
                        "from sim_state st join sim_runs r on r.id=st.current_run_id where st.id=1 "
                        "for update of st for share of r"
                    )
                ).fetchone()
                if (
                    row is None
                    or row[0] != run_id
                    or row[3]
                    or row[4:] != ("scenario", "paused")
                    or self.run_id != run_id
                    or self.run_status != "paused"
                    or self.clock.running
                    or row[2] != self.rng.dump_state()
                    or row[1] != self.clock.sim_time
                ):
                    raise ScriptedScenarioError("owner_changed")
                if row[1] == target:
                    await conn.rollback()
                    return False
                if row[1] != before:
                    raise ScriptedScenarioError("phase_clock_changed")
                await self._step_chunk_locked(minutes)
            except BaseException:
                await conn.rollback()
                raise
        await self._publish_tick()
        return True

    async def _step_chunk_locked(self, minutes: float) -> None:
        conn = await self.connect()
        policy = await effective_policy(conn, self.run_id, self.behavior_policy)
        if (
            policy is not None
            and self.run_id is not None
            and self.run_status not in ("completed", "stopped", "archived")
        ):
            try:
                await self._require_current(conn)
                if self.run_status == "interrupted":
                    raise ValueError("Прерванный behavior run сначала нужно возобновить")
                # До _ensure_world: legacy отказ не меняет даже memory cache.
                await prepare_run(conn, self.run_id, self.clock.sim_time, policy)
            except BaseException:
                await conn.rollback()
                raise
        world = await self._ensure_world()
        policy = world.behavior_policy
        if policy is not None:
            assert self.run_id is not None
            try:
                await prepare_run(conn, self.run_id, self.clock.sim_time, policy)
                row = await (
                    await conn.execute("select current_run_id,sim_time,rng_state from sim_state where id=1 for update")
                ).fetchone()
                if (
                    row is None
                    or row[0] != self.run_id
                    or row[1] != self.clock.sim_time
                    or (row[2] is not None and row[2] != self.rng.dump_state())
                ):
                    raise ValueError("Behavior tick owner устарел: загрузите актуальные time/run/RNG")
            except BaseException:
                await conn.rollback()
                raise
        t0 = self.clock.sim_time
        day_before = self.clock.day_no
        rng_before = self.rng.dump_state()
        stats_before = dict(self.stats)
        pending_before = copy.deepcopy(world.pending)
        faults_before = copy.deepcopy(world.active_faults)
        minutes = min(minutes, MAX_BATCH_MIN)
        try:
            from app.sim.proactive_scenario import prepared_source

            scripted = self.run_id is not None and await prepared_source(conn, self.run_id)
            if not scripted:
                self.stats["faults"] += await world.gen_faults(t0, minutes)
                self.stats["ops"] += await world.gen_operations(t0, minutes)
                self.stats["client_errors"] += await world.gen_client_errors(t0, minutes)
            self.clock.sim_time = t0 + dt.timedelta(minutes=minutes)
            if self.clock.sim_time.astimezone(MSK).date() != t0.astimezone(MSK).date():
                self.clock.day_no += 1
            # Эффекты tick используют его часы; наружу они видны лишь с общим commit.
            await self.persist()
            if scripted:
                self.stats["signals"] += await world.flush_signals(self.clock.sim_time, minutes, ambient_noise=False)
            else:
                self.stats["signals"] += await world.flush_signals(self.clock.sim_time, minutes)
            execution = await configuration(conn, self.run_id) if self.run_id else {}
            if self.run_id is not None:
                from app.agent.proactive import refresh_service_impacts

                await refresh_service_impacts(conn, self.run_id, self.clock.sim_time)
            if not execution.get("enabled"):
                await world.team_emulator.tick(self.clock.sim_time, world)
            await world.sla_engine.tick(t0, self.clock.sim_time)
            self.stats["ticks"] += 1
            await self.persist()
            if policy is not None:
                assert self.run_id is not None
                await capture(conn, self.run_id)
                owner = BehaviorOwner(conn, policy)
                next_rng = await owner.advance(
                    run_id=self.run_id, to_sim=self.clock.sim_time, allow_paused=self.run_status == "paused"
                )
                self.rng.load_state(next_rng)
                self.stats["signals"] += owner.generated_signals
                await self.persist()
            await conn.commit()
        except BaseException as error:
            # Любая незафиксированная попытка отменяется вместе с logical
            # time/RNG/stats. Частично изменённый World нельзя reuse при retry.
            self.clock.sim_time = t0
            self.clock.day_no = day_before
            self.rng.load_state(rng_before)
            self.stats = stats_before
            restored = World(
                conn,
                EventBus(conn),
                self.rng,
                world.run_id,
                world.intensities,
                behavior_policy=policy,
            )
            restored.pending = pending_before
            restored.active_faults = faults_before
            self.world = restored
            await conn.rollback()
            try:
                await restored.load()
            except Exception as reload_error:
                # Existing pending остаётся в restored; loaded=False заставит
                # следующий step повторить DB reload, а не использовать partial cache.
                await conn.rollback()
                log.error("sim_world_reload_failed", error_type=type(reload_error).__name__)
            else:
                await conn.rollback()  # reload только читает committed DB.
            if not isinstance(error, asyncio.CancelledError):
                log.exception("sim_step_failed")
            raise

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
        if action == "resume" or (
            action == "start" and not kw.get("label") and self.run_status in ("paused", "interrupted")
        ):
            return await self.resume_run()
        if action in {"pause", "stop"}:
            await self._stop_loop()
            # Сначала Python lock, затем sim_runs row lock: demo worker использует
            # тот же порядок. Иначе pause держит row и ждёт worker, который ждёт row.
            async with self._lock:
                conn = await self.connect()
                previous_status = self.run_status
                try:
                    await self._require_current(conn, check_state=True)
                    execution = await configuration(conn, self.run_id) if self.run_id else {}
                    if self.run_id and (
                        self.run_status == "running"
                        or (action == "stop" and self.run_status in ("paused", "interrupted"))
                    ):
                        halt_status = "paused" if action == "pause" else "stopped"
                        await run_svc.set_run_status(
                            conn, self.run_id, halt_status, self.clock.sim_time if action == "stop" else None
                        )
                        self.run_status = halt_status
                    if execution and self.run_id is not None:
                        if action == "pause" and execution.get("enabled"):
                            execution["status"] = "paused"
                        elif action == "stop":
                            execution.update(enabled=False, status="stopped")
                        await save(conn, self.run_id, execution)
                    await self.persist()
                    await conn.commit()
                except BaseException:
                    self.run_status = previous_status
                    await conn.rollback()
                    raise
            await hub.publish("sim", "sim.control", {"action": action, **self.state_dict()}, self.run_id)
            return self.state_dict()
        # Tick и control разделяют одно соединение: даже preflight SELECT/rollback
        # должен дождаться общей транзакции tick, а не видеть его промежуточные часы/RNG.
        async with self._lock:
            conn = await self.connect()
            await self._require_current(conn, lock=False, check_state=True)
            creates_new = action == "start" and (
                self.run_id is None
                or self.run_status in ("stopped", "completed", "archived", None)
                or bool(kw.get("label"))
            )
            if not creates_new and action in {"start", "step", "jump_to", "reset_day"}:
                await self._reject_scripted_control()
            if (
                self.behavior_policy is not None
                and self.run_id is not None
                and action in ("start", "step", "jump_to", "reset_day")
                and not creates_new
            ):
                try:
                    await require_run(conn, self.run_id, policy=self.behavior_policy)
                except BaseException:
                    await conn.rollback()
                    raise
            execution = await configuration(conn, self.run_id) if self.run_id else {}
        if (
            self.run_id is not None
            and execution.get("mode") == "demo"
            and (execution.get("enabled") or (execution.get("status") == "stopped" and action == "resume"))
            and action in ("start", "resume")
            and not kw.get("label")
        ):
            async with self._lock:
                await self._require_current(conn, check_state=True)
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
            async with self._lock:
                await self._require_current(conn, check_state=True)
                previous = (
                    self.run_id,
                    self.run_status,
                    self.seed,
                    self.rng,
                    self.clock.running,
                    dict(self.stats),
                    self.world,
                )
                try:
                    if (
                        self.run_status in ("stopped", "completed", "archived", None)
                        or self.run_id is None
                        or kw.get("label")
                    ):
                        selected_seed = kw.get("seed")
                        if selected_seed is None:
                            base = await (
                                await conn.execute(
                                    "select seed from sim_runs where kind='baseline' order by id limit 1"
                                )
                            ).fetchone()
                            selected_seed = base[0] if base else self.seed
                        new_seed = int(selected_seed)
                        self.run_id = await run_svc.create_run(
                            conn,
                            kind=kw.get("kind") or "free",
                            label=kw.get("label") or f"Запуск {dt.datetime.now(MSK):%d.%m %H:%M}",
                            seed=new_seed,
                            sim_time=self.clock.sim_time,
                            llm_profile_id=kw.get("llm_profile_id"),
                            scenario_id=kw.get("scenario_id"),
                            reset_mode=kw.get("reset_mode") or "counters",
                        )
                        self.seed = new_seed
                        self.rng = SimRng(self.seed)
                        self.stats = {key: 0 for key in self.stats}
                        self.run_status = "running"
                        self.world = None
                    self.clock.running = not bool(kw.get("start_paused"))
                    if not self.clock.running:
                        if self.run_id:
                            await run_svc.set_run_status(conn, self.run_id, "paused")
                        self.run_status = "paused"
                    if self.full_execution and self.run_id:
                        await ensure(conn, self.run_id, running=self.clock.running)
                    await self.persist()
                    await conn.commit()
                except BaseException:
                    await conn.rollback()
                    self.run_id, self.run_status, self.seed, self.rng, self.clock.running, self.stats, self.world = (
                        previous
                    )
                    raise
                if self.clock.running:
                    self._start_loop()
            await hub.publish("sim", "sim.control", {"action": action, **self.state_dict()}, self.run_id)
            return self.state_dict()
        elif action in ("set_speed", "set_preset"):
            async with self._lock:
                await self._require_current(conn, check_state=True)
                previous_speed = self.clock.speed
                try:
                    if action == "set_speed":
                        self.clock.speed = max(0.1, float(kw["speed"]))
                    else:
                        self.clock.set_preset(str(kw["preset"]))
                    await self.persist()
                    await conn.commit()
                except BaseException:
                    await conn.rollback()
                    self.clock.speed = previous_speed
                    raise
            await hub.publish("sim", "sim.control", {"action": action, **self.state_dict()}, self.run_id)
            return self.state_dict()
        elif action == "step":
            await self.step(float(kw.get("step_minutes") or 15))
        elif action == "reset_day":
            await self._stop_loop()
            async with self._lock:
                lt = self.clock.sim_time.astimezone(MSK)
                target = (lt + dt.timedelta(days=1)).replace(hour=9, minute=0, second=0, microsecond=0)
                reset_policy = await effective_policy(conn, self.run_id, self.behavior_policy)
            if reset_policy is not None:
                await self.step((target - self.clock.sim_time).total_seconds() / 60)
            else:
                async with self._lock:
                    await self._require_current(conn, check_state=True)
                    self.clock.sim_time = target
                    self.clock.day_no += 1
                    if self.world:
                        self.world.pending.clear()
                    await self.persist()
                    await conn.commit()
                await hub.publish("sim", "sim.control", {"action": action, **self.state_dict()}, self.run_id)
                return self.state_dict()
        elif action == "jump_to":
            target = kw["sim_time"]
            if isinstance(target, str):
                target = dt.datetime.fromisoformat(target)
            if target <= self.clock.sim_time:
                raise ValueError("jump_to: только вперёд")
            await self.step((target - self.clock.sim_time).total_seconds() / 60)
        else:
            raise ValueError(f"неизвестное действие: {action}")
        async with self._lock:
            if self.run_id:
                await self._require_current(conn, check_state=True)
                execution = await configuration(conn, self.run_id)
                if not execution and self.full_execution and action in ("start", "resume"):
                    execution = await ensure(conn, self.run_id, running=True)
                if execution:
                    if action in ("start", "resume"):
                        execution.update(enabled=True, status="running")
                    await save(conn, self.run_id, execution)
            await self.persist()
            await conn.commit()
        await hub.publish("sim", "sim.control", {"action": action, **self.state_dict()}, self.run_id)
        return self.state_dict()

    async def resume_run(self) -> dict[str, Any]:
        """Resume продолжает только последний paused/interrupted, не создаёт новый run."""
        async with self._lock:
            await self._reject_scripted_control()
            conn = await self.connect()
            row = await (
                await conn.execute(
                    "select st.current_run_id,r.status,st.sim_time,st.rng_state,st.seed,st.day_no "
                    "from sim_state st left join sim_runs r on r.id=st.current_run_id where st.id=1 for update of st"
                )
            ).fetchone()
            if not row or row[0] != self.run_id or row[1] not in ("paused", "interrupted"):
                await conn.rollback()
                raise ValueError("возобновить можно только текущий paused/interrupted запуск")
            rid, _, sim_time, rng_state, seed, day_no = row
            try:
                policy = await effective_policy(conn, int(rid), self.behavior_policy)
                if policy is not None:
                    await prepare_run(conn, int(rid), sim_time, policy)
                if self.before_resume:
                    await self.before_resume(int(rid), sim_time)
                self.seed = int(seed)
                self.rng = SimRng(self.seed)
                self.rng.load_state(rng_state)
                self.clock.sim_time, self.clock.day_no = sim_time, int(day_no)
                self.world = None
                await run_svc.set_run_status(conn, int(rid), "running", event_type="resumed")
                self.run_status = "running"
                execution = await configuration(conn, int(rid))
                if not execution and self.full_execution:
                    execution = await ensure(conn, int(rid), running=True)
                if execution:
                    execution.update(enabled=True, status="running")
                    await save(conn, int(rid), execution)
                self.clock.running = True
                await self.persist()
                await conn.commit()
            except BaseException:
                await conn.rollback()
                raise
            if execution.get("mode") != "demo":
                self._start_loop()
        if self.after_resume:
            await self.after_resume(int(rid), sim_time)
        await hub.publish("sim", "sim.control", {"action": "resume", **self.state_dict()}, int(rid))
        return self.state_dict()

    def _start_loop(self) -> None:
        self.clock.running = True
        if self._task is None or self._task.done():
            self._task = start_daemon(self._loop, name="sim-loop")

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
            try:
                async with self._lock:
                    await self._require_current(self.conn, check_state=True)
                    await self.persist()
                    await self.conn.commit()
            except StaleSimulatorError:
                await self.conn.rollback()
                log.info("sim_shutdown_stale_skipped", run_id=self.run_id)
            except Exception:
                await self.conn.rollback()
                log.exception("sim_shutdown_failed", run_id=self.run_id)
                raise
            finally:
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
