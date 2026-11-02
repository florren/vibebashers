"""AgentService (T-056 п. 2): слушает signal.received (LISTEN sim_events) и запускает проходы графа с ограничением параллелизма;
при старте дообрабатывает сигналы со статусом new и восстанавливает незавершённые проходы (interrupted → failed)."""

from __future__ import annotations

import asyncio
import contextlib
import datetime as dt
from collections.abc import Mapping
from typing import TYPE_CHECKING, Any

import orjson
import psycopg

from app.agent import proactive
from app.agent.graph import (
    expire_hitl,
    process_signal,
    recover_agent_run,
    resume_after_human,
    resume_proactive_fault,
    wake_due_followups,
    wake_followups_for_client_reply,
    wake_followups_for_incident,
)
from app.db.session import psycopg_dsn
from app.ingest.synthetic import AUTOMATIC_EXCLUDED_SQL
from app.llm.base import LLMProfile
from app.llm.failover import ProviderChain
from app.logging import get_logger
from app.sim.maintenance import spawn_writer, start_daemon, writer

if TYPE_CHECKING:
    from app.sim.engine import Simulator

log = get_logger(__name__)


class AgentService:
    def __init__(
        self,
        chain: ProviderChain,
        profile: LLMProfile,
        *,
        concurrency: int = 4,
        dsn: str | None = None,
        sim: Simulator | None = None,
    ) -> None:
        self.chain, self.profile, self.dsn = chain, profile, dsn
        self.sim = sim
        self.sem = asyncio.Semaphore(concurrency)
        self.personal_sem = asyncio.Semaphore(2)
        self._recover_on_start = True
        self._task: asyncio.Task[None] | None = None
        self._feedback_task: asyncio.Task[None] | None = None
        self._personal_task: asyncio.Task[None] | None = None
        self._reply_task: asyncio.Task[None] | None = None
        self._proactive_task: asyncio.Task[None] | None = None
        self._proactive_wake = asyncio.Event()
        self._inflight: set[asyncio.Task[Any]] = set()
        self._by_signal: dict[int, asyncio.Task[Any]] = {}
        self._by_reply: dict[int, asyncio.Task[Any]] = {}
        self.processed = 0
        self.failed = 0
        self.enabled = True
        self.started_at = dt.datetime.now(dt.UTC)

    def start(self, *, recover: bool = True) -> None:
        self._recover_on_start = recover
        if self._task is None or self._task.done():
            self._task = start_daemon(self._loop, name="agent-listener")
        if self._feedback_task is None or self._feedback_task.done():
            from app.agent.operator_feedback import worker

            self._feedback_task = start_daemon(
                lambda: worker(lambda: (self.chain, self.profile), self.dsn), name="operator-feedback"
            )

        if self._personal_task is None or self._personal_task.done():
            self._personal_task = start_daemon(self._personal_loop, name="personal-chat-queue")
        if self._reply_task is None or self._reply_task.done():
            self._reply_task = start_daemon(self._reply_loop, name="tracking-replies")

        if self._proactive_task is None or self._proactive_task.done():
            self._proactive_task = start_daemon(self._proactive_loop, name="proactive-fault-queue")

    async def _proactive_loop(self) -> None:
        """NOTIFY ускоряет один wakeup; native recheck восстанавливает потерянные события."""
        while True:
            self._proactive_wake.clear()
            try:
                if self.enabled:
                    await self._proactive_cycle()
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                log.warning("proactive_fault_queue_failed", error_type=type(exc).__name__)
            try:
                await asyncio.wait_for(self._proactive_wake.wait(), timeout=2)
            except TimeoutError:
                pass

    @writer("agent-proactive")
    async def _proactive_cycle(self) -> None:
        async with await self._conn() as conn:
            phase_signals: list[int] = []
            if self.sim is not None:
                from app.sim.proactive_phases import advance

                clock_before = (self.sim.run_id, self.sim.clock.sim_time)
                phase_signals = await advance(conn, self.sim)
                await conn.commit()
                if (self.sim.run_id, self.sim.clock.sim_time) != clock_before:
                    # Только hint после committed clock progress. Следующая
                    # итерация снова читает authoritative run/time из PostgreSQL.
                    self._proactive_wake.set()
            signal_ids = list(dict.fromkeys([*phase_signals, *await proactive.produce(conn)]))
            # Граф не держит producer TX/run lock через LLM и другие await.
            await conn.commit()
            pending = await (
                await conn.execute(
                    "select s.id,a.id,a.outcome,s.origin from signals s left join lateral "
                    "(select ar.id,ar.outcome from agent_runs ar where ar.signal_id=s.id "
                    "and ar.sim_run_id=s.run_id and ar.kind='agent' "
                    "order by ar.id desc limit 1) a on true "
                    "where s.id=any(%s::bigint[]) order by s.id",
                    (signal_ids,),
                )
            ).fetchall()
        for signal_id, agent_run_id, outcome, origin in pending:
            if agent_run_id is None:
                self.submit(int(signal_id))
            elif outcome == "deferred" and origin == "proactive":
                self._submit_proactive_resume(int(signal_id))
            elif outcome is None and agent_run_id is not None and self.sim is not None:
                existing = self._by_signal.get(int(signal_id))
                if existing is None or existing.done():
                    self._track_signal(
                        int(signal_id),
                        self._recover_scripted(int(signal_id), int(agent_run_id)),
                        name=f"scripted-recover-{agent_run_id}",
                    )
            # failed — диагностический результат для ручного разбора; poll не
            # создаёт новый AR/платные вызовы каждые две секунды.

    @writer("agent-scripted-recovery")
    async def _recover_scripted(self, signal_id: int, agent_run_id: int) -> None:
        from app.agent.checkpoints import TransactionalSaver
        from app.sim.proactive_phases import fail, journal_inputs, locked

        async with self.sem, await self._conn() as conn:
            run_id: int | None = None
            try:
                row = await (
                    await conn.execute(
                        "select ar.sim_run_id,ar.thread_id from agent_runs ar join sim_runs r on r.id=ar.sim_run_id "
                        "where ar.id=%s and ar.signal_id=%s and ar.kind='agent' and ar.outcome is null "
                        "and ar.interrupted_at is not null and ar.started_at<%s and r.kind='scenario' and r.status='paused'",
                        (agent_run_id, signal_id, self.started_at),
                    )
                ).fetchone()
                if row is None:
                    return
                run_id, thread_id = int(row[0]), row[1]
                scope = await locked(conn, run_id)
                if scope is None:
                    return
                context, at = scope
                if signal_id not in await journal_inputs(conn, context):
                    return
                saved = await TransactionalSaver(conn).aget_tuple({"configurable": {"thread_id": thread_id}})
                if saved is None:
                    raise ValueError("Scripted recovery требует durable checkpoint; нужен ручной разбор")
                values = saved.checkpoint["channel_values"]
                state = values.get("__start__", values)
                human = await (
                    await conn.execute(
                        "select 1 from human_decisions where agent_run_id=%s and decision is null limit 1",
                        (agent_run_id,),
                    )
                ).fetchone()
                if (
                    state.get("agent_run_id") != agent_run_id
                    or state.get("run_id") != run_id
                    or (state.get("signal") or {}).get("id") != signal_id
                    or state.get("outcome") == "awaiting_human"
                    or human
                ):
                    raise ValueError("Scripted recovery checkpoint требует ручного решения")
                # Release phase/run/time locks до graph/model. Existing recovery
                # сам проверяет checkpoint/thread и выбирает pinned AR profiles.
                await conn.commit()
                completed = await recover_agent_run(
                    conn, agent_run_id=agent_run_id, chain=self.chain, profile=self.profile, sim_time=at
                )
                await self._wake_committed_graph(conn, completed)
            except Exception as exc:
                if run_id is not None:
                    await fail(conn, run_id, "customer_graph_failed")
                self.failed += 1
                log.error("scripted_agent_recovery_failed", agent_run_id=agent_run_id, error_type=type(exc).__name__)

    async def _wake_committed_graph(self, conn: psycopg.AsyncConnection[Any], state: Mapping[str, Any] | None) -> None:
        if state is None or self.sim is None:
            return  # No-op/standalone caller не создаёт phase self-waking loop.
        owned = await proactive.current_clock(conn, int(state["run_id"]))
        await conn.commit()
        if owned is not None:
            self._proactive_wake.set()

    def _submit_proactive_resume(self, signal_id: int) -> asyncio.Task[Any]:
        existing = self._by_signal.get(signal_id)
        if existing is not None and not existing.done():
            return existing
        return self._track_signal(signal_id, self._resume_proactive(signal_id), name=f"proactive-resume-{signal_id}")

    @writer("agent-proactive-resume")
    async def _resume_proactive(self, signal_id: int) -> None:
        async with self.sem:
            try:
                async with await self._conn() as conn:
                    state = await resume_proactive_fault(
                        conn, signal_id=signal_id, chain=self.chain, profile=self.profile
                    )
                    await self._wake_committed_graph(conn, state)
            except Exception as exc:
                self.failed += 1
                log.warning("proactive_fault_resume_failed", signal_id=signal_id, error_type=type(exc).__name__)

    async def _reply_loop(self) -> None:
        """Восстанавливает доставленные ответы после рестарта или потери NOTIFY."""
        while True:
            try:
                if self.enabled:
                    await self._reply_cycle()
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                log.warning("tracking_reply_queue_failed", error=type(exc).__name__)
            await asyncio.sleep(2)

    @writer("agent-reply")
    async def _reply_cycle(self) -> None:
        async with await self._conn() as conn:
            rows = await (
                await conn.execute(
                    "select p.id,reply.id,st.sim_time from followups f join signals p on p.id=f.signal_id "
                    "join sim_state st on st.id=1 join lateral (select c.id from signals c where c.parent_signal_id=p.id "
                    "and c.run_id=p.run_id and c.status<>'error' order by c.id desc limit 1) reply on true "
                    "where p.tracking_token is not null and f.reason='awaiting_client' and f.status='scheduled' "
                    "and exists(select 1 from agent_steps a where a.run_id=f.agent_run_id and a.node='followup_monitor') "
                    "order by f.id limit 20"
                )
            ).fetchall()
        for parent_id, child_id, sim_time in rows:
            self.submit_client_reply(int(parent_id), int(child_id), sim_time)

    async def _personal_loop(self) -> None:
        # Публичный чат не ждёт восстановления старой фоновой очереди. Данные остаются в общем signals.
        while True:
            try:
                if self.enabled:
                    await self._personal_cycle()
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                log.warning("personal_queue_failed", error=type(exc).__name__)
            await asyncio.sleep(2)

    @writer("agent-personal")
    async def _personal_cycle(self) -> None:
        async with await self._conn() as conn:
            rows = await (
                await conn.execute(
                    "select s.id from signals s where s.channel_subtype='ui_pers_demo' and s.status='new' and not exists(select 1 from agent_runs a where a.signal_id=s.id and a.kind='agent' and a.outcome is distinct from 'failed') order by s.id limit 20"
                )
            ).fetchall()
            await conn.commit()
        for (sid,) in rows:
            self.submit(int(sid), interactive=True)

    async def stop(self) -> None:
        if self._proactive_task:
            self._proactive_task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self._proactive_task
            self._proactive_task = None
        if self._reply_task:
            self._reply_task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self._reply_task
            self._reply_task = None
        if self._personal_task:
            self._personal_task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self._personal_task
            self._personal_task = None
        if self._feedback_task:
            self._feedback_task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self._feedback_task
            self._feedback_task = None
        if self._task:
            self._task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self._task
        tasks = list(self._inflight)
        for task in tasks:
            task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)
        self._inflight.clear()
        self._by_signal.clear()
        self._task = None

    def _background(self, coro: Any, *, name: str) -> asyncio.Task[Any]:
        task = spawn_writer(coro, kind="agent-timer", name=name)
        self._inflight.add(task)
        task.add_done_callback(self._inflight.discard)
        return task

    async def _conn(self) -> psycopg.AsyncConnection[Any]:
        return await psycopg.AsyncConnection.connect(psycopg_dsn(self.dsn), autocommit=False)

    @writer("agent")
    async def _recover(self) -> None:
        async with await self._conn() as conn:
            await conn.execute(
                "update agent_runs ar set interrupted_at=coalesce(interrupted_at,now()) "
                "where ar.kind='agent' and ar.outcome is null and ar.started_at<%s "
                f"and not exists(select 1 from signals s where s.id=ar.signal_id and {AUTOMATIC_EXCLUDED_SQL})",
                (self.started_at,),
            )
            state = await (
                await conn.execute(
                    "select st.current_run_id,st.sim_time,r.status from sim_state st "
                    "left join sim_runs r on r.id=st.current_run_id where st.id=1"
                )
            ).fetchone()
            await conn.commit()
        # interrupted/paused ждут явного Resume, а не переигрываются при startup.
        if state and state[0] and state[2] == "running":
            await self.validate_recovery(int(state[0]), state[1], started_before=self.started_at)
            await self.recover_run(int(state[0]), state[1], started_before=self.started_at)

    @writer("agent-recovery")
    async def validate_recovery(
        self, run_id: int, sim_time: dt.datetime, *, started_before: dt.datetime | None = None
    ) -> None:
        async with await self._conn() as conn:
            missing = await (
                await conn.execute(
                    "select ar.id from agent_runs ar where ar.sim_run_id=%s and ar.kind='agent' and ar.outcome is null "
                    "and (%s::timestamptz is null or ar.started_at<%s) "
                    f"and not exists(select 1 from signals s where s.id=ar.signal_id and {AUTOMATIC_EXCLUDED_SQL}) "
                    "and not exists(select 1 from langgraph.checkpoints c where c.thread_id=ar.thread_id) limit 1",
                    (run_id, started_before, started_before),
                )
            ).fetchone()
            if missing:
                raise ValueError(f"Проход AR-{missing[0]} не имеет durable checkpoint; нужно ручное восстановление")

    @writer("agent-recovery")
    async def recover_run(
        self, run_id: int, sim_time: dt.datetime, *, started_before: dt.datetime | None = None
    ) -> None:
        async with await self._conn() as conn:
            rows = await (
                await conn.execute(
                    "select ar.id,ar.signal_id from agent_runs ar where ar.sim_run_id=%s and ar.kind='agent' and ar.outcome is null "
                    "and (%s::timestamptz is null or ar.started_at<%s) "
                    f"and not exists(select 1 from signals s where s.id=ar.signal_id and {AUTOMATIC_EXCLUDED_SQL}) order by ar.id",
                    (run_id, started_before, started_before),
                )
            ).fetchall()
            new_signals = await (
                await conn.execute(
                    "select s.id from signals s where s.run_id=%s and s.status='new' "
                    "and not exists(select 1 from agent_runs ar where ar.signal_id=s.id and ar.kind='agent' "
                    "and ar.outcome is distinct from 'failed') "
                    f"and not {AUTOMATIC_EXCLUDED_SQL} order by s.id",
                    (run_id,),
                )
            ).fetchall()
        recovery_tasks = []
        for arid, sid in rows:
            existing = self._by_signal.get(int(sid))
            if existing is not None and not existing.done():
                continue
            task = spawn_writer(
                self._recover_one(int(arid), sim_time), kind="agent-recovery", name=f"agent-recover-{arid}"
            )
            recovery_tasks.append(task)
            self._inflight.add(task)
            self._by_signal[int(sid)] = task

            def finished(value: asyncio.Task[Any], signal_id: int = int(sid)) -> None:
                self._inflight.discard(value)
                if self._by_signal.get(signal_id) is value:
                    self._by_signal.pop(signal_id, None)

            task.add_done_callback(finished)
        for (sid,) in new_signals:
            self.submit(int(sid), sim_time)
        timers = spawn_writer(
            self._recover_timers(run_id, sim_time, recovery_tasks),
            kind="agent-recovery",
            name=f"agent-recover-timers-{run_id}",
        )
        self._inflight.add(timers)
        timers.add_done_callback(self._inflight.discard)

    @writer("agent-recovery")
    async def _recover_timers(self, run_id: int, sim_time: dt.datetime, tasks: list[asyncio.Task[Any]]) -> None:
        try:
            if tasks:
                await asyncio.gather(*tasks)
            async with self.sem, await self._conn() as conn:
                await expire_hitl(conn, sim_time=sim_time, chain=self.chain, profile=self.profile, run_id=run_id)
                await wake_due_followups(conn, sim_time=sim_time, chain=self.chain, profile=self.profile, run_id=run_id)
                await conn.commit()
        except Exception as exc:
            log.error("agent_timer_recovery_failed", run_id=run_id, error_type=type(exc).__name__)

    @writer("agent-recovery")
    async def _recover_one(self, agent_run_id: int, sim_time: dt.datetime) -> None:
        async with self.sem:
            try:
                async with await self._conn() as conn:
                    await recover_agent_run(
                        conn, agent_run_id=agent_run_id, chain=self.chain, profile=self.profile, sim_time=sim_time
                    )
            except Exception as exc:
                log.error("agent_recovery_failed", agent_run_id=agent_run_id, error_type=type(exc).__name__)
                raise

    async def _loop(self) -> None:
        if self._recover_on_start:
            try:
                await self._recover()
            except Exception as exc:
                log.error("agent_startup_recovery_failed", error_type=type(exc).__name__)
        while True:
            conn: psycopg.AsyncConnection[Any] | None = None
            try:
                conn = await psycopg.AsyncConnection.connect(psycopg_dsn(self.dsn), autocommit=True)
                await conn.execute("LISTEN sim_events")
                log.info("agent_listen")
                async for n in conn.notifies():
                    await self._notification(n)
            except asyncio.CancelledError:
                raise
            except Exception as exc:  # noqa: BLE001
                log.warning("agent_listen_failed", error=str(exc)[:200])
                await asyncio.sleep(2)
            finally:
                if conn is not None:
                    await conn.close()

    @writer("agent-notification")
    async def _notification(self, n: Any) -> None:
        if not self.enabled:
            return
        try:
            body = orjson.loads(n.payload)
        except orjson.JSONDecodeError:
            return
        if n.channel == "sim_events" and body.get("event_type") in (
            "fault.started",
            "op.failed",
            "sla.tick",
            "scenario.proactive_prepared",
            "scenario.proactive_notified",
            "scenario.proactive_complaints",
            "scenario.proactive_completed",
            "scenario.proactive_failed",
        ):
            self._proactive_wake.set()
        if n.channel == "sim_events" and body.get("event_type") == "sla.tick":
            sim_raw = body.get("sim_time")
            if sim_raw:
                st = dt.datetime.fromisoformat(sim_raw)
                self._background(self._expire_hitl(st), name="agent-expire-hitl")
                self._background(self._wake_followups(st), name="agent-wake-followups")
        elif n.channel == "sim_events" and body.get("event_type") == "team.release":
            sim_raw = body.get("sim_time")
            payload = body.get("payload") or {}
            inc_id = payload.get("incident_id")
            if sim_raw and inc_id:
                st = dt.datetime.fromisoformat(sim_raw)
                self._background(
                    self._wake_incident_followups(int(inc_id), st),
                    name="agent-wake-release",
                )
        elif n.channel == "sim_events" and body.get("event_type") == "signal.appended":
            payload = body.get("payload") or {}
            if payload.get("signal_id") and payload.get("parent_signal_id"):
                raw_time = body.get("sim_time")
                self.submit_client_reply(
                    int(payload["parent_signal_id"]),
                    int(payload["signal_id"]),
                    dt.datetime.fromisoformat(raw_time) if raw_time else dt.datetime.now(dt.UTC),
                )
        elif n.channel == "sim_events" and body.get("event_type") == "signal.received":
            sid = (body.get("payload") or {}).get("signal_id")
            sim_time = body.get("sim_time")
            if sid:
                async with await self._conn() as lookup:
                    source = await (
                        await lookup.execute(
                            f"select s.channel_subtype,{AUTOMATIC_EXCLUDED_SQL} from signals s where s.id=%s",
                            (sid,),
                        )
                    ).fetchone()
                if not source or source[1]:
                    return
                self.submit(
                    int(sid),
                    dt.datetime.fromisoformat(sim_time) if sim_time else None,
                    interactive=bool(source and source[0] == "ui_pers_demo"),
                )

    def submit(
        self, signal_id: int, sim_time: dt.datetime | None = None, *, interactive: bool = False
    ) -> asyncio.Task[Any]:
        existing = self._by_signal.get(signal_id)
        if existing is not None and not existing.done():
            return existing
        return self._track_signal(
            signal_id,
            self._process(signal_id, sim_time, interactive=True) if interactive else self._process(signal_id, sim_time),
            name=f"agent-{signal_id}",
        )

    def _track_signal(self, signal_id: int, coro: Any, *, name: str) -> asyncio.Task[Any]:
        t = spawn_writer(coro, name=name, kind="agent")
        self._by_signal[signal_id] = t
        self._inflight.add(t)

        def finished(task: asyncio.Task[Any]) -> None:
            self._inflight.discard(task)
            if self._by_signal.get(signal_id) is task:
                self._by_signal.pop(signal_id, None)

        t.add_done_callback(finished)
        return t

    def submit_client_reply(self, parent_id: int, child_id: int, sim_time: dt.datetime) -> asyncio.Task[Any]:
        existing = self._by_reply.get(child_id)
        if existing is not None and not existing.done():
            return existing

        async def continue_reply() -> None:
            # Сначала штатный граф дополнения: его политика и HITL не обходятся.
            await self.submit(child_id, sim_time)
            async with self.sem, await self._conn() as conn:
                child = await (await conn.execute("select status from signals where id=%s", (child_id,))).fetchone()
                if not child or child[0] in ("new", "processing", "error", "awaiting_human"):
                    return
                await wake_followups_for_client_reply(
                    conn,
                    signal_id=parent_id,
                    sim_time=sim_time,
                    chain=self.chain,
                    profile=self.profile,
                )

        task = spawn_writer(continue_reply(), kind="agent-client-reply", name=f"client-reply-{child_id}")
        self._by_reply[child_id] = task
        self._inflight.add(task)

        def finished(done: asyncio.Task[Any]) -> None:
            self._inflight.discard(done)
            if self._by_reply.get(child_id) is done:
                self._by_reply.pop(child_id, None)
            if not done.cancelled() and done.exception() is not None:
                log.error("client_reply_failed", signal_id=parent_id, error=type(done.exception()).__name__)

        task.add_done_callback(finished)
        return task

    @writer("agent")
    async def _expire_hitl(self, sim_time: dt.datetime) -> None:
        async with self.sem:
            try:
                async with await self._conn() as conn:
                    await expire_hitl(conn, sim_time=sim_time, chain=self.chain, profile=self.profile)
            except Exception as exc:  # noqa: BLE001
                log.warning("expire_hitl_failed", error=str(exc)[:200])

    @writer("agent")
    async def _wake_followups(self, sim_time: dt.datetime) -> None:
        async with self.sem:
            try:
                async with await self._conn() as conn:
                    await wake_due_followups(conn, sim_time=sim_time, chain=self.chain, profile=self.profile)
            except Exception as exc:  # noqa: BLE001
                log.warning("wake_followups_failed", error=str(exc)[:200])

    @writer("agent")
    async def _wake_incident_followups(self, incident_id: int, sim_time: dt.datetime) -> None:
        async with self.sem:
            try:
                async with await self._conn() as conn:
                    await wake_followups_for_incident(
                        conn, incident_id=incident_id, sim_time=sim_time, chain=self.chain, profile=self.profile
                    )
            except Exception as exc:  # noqa: BLE001
                log.warning("wake_release_followups_failed", incident_id=incident_id, error=str(exc)[:200])

    @writer("agent")
    async def _process(self, signal_id: int, sim_time: dt.datetime | None, *, interactive: bool = False) -> None:
        semaphore = self.personal_sem if interactive else self.sem
        async with semaphore:
            try:
                async with await self._conn() as conn:
                    state = await process_signal(
                        conn, signal_id=signal_id, chain=self.chain, profile=self.profile, sim_time=sim_time
                    )
                    await self._wake_committed_graph(conn, state)
                if state is not None:
                    self.processed += 1
                    if state.get("outcome") == "failed":
                        self.failed += 1
                    elif state.get("outcome") == "deferred":
                        pass
            except Exception as exc:  # noqa: BLE001
                self.failed += 1
                log.warning("agent_process_failed", signal_id=signal_id, error=str(exc)[:200])

    @writer("agent")
    async def resume(self, human_decision_id: int, sim_time: dt.datetime | None = None) -> dict[str, Any] | None:
        async with self.sem, await self._conn() as conn:
            state = await resume_after_human(
                conn, human_decision_id=human_decision_id, chain=self.chain, profile=self.profile, sim_time=sim_time
            )
            await self._wake_committed_graph(conn, state)
        return dict(state) if state else None
