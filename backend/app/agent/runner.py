"""AgentService (T-056 п. 2): слушает signal.received (LISTEN sim_events) и запускает проходы графа с ограничением параллелизма;
при старте дообрабатывает сигналы со статусом new и восстанавливает незавершённые проходы (interrupted → failed)."""

from __future__ import annotations

import asyncio
import contextlib
import datetime as dt
from typing import Any

import orjson
import psycopg

from app.agent.graph import (
    expire_hitl,
    process_signal,
    resume_after_human,
    wake_due_followups,
    wake_followups_for_client_reply,
    wake_followups_for_incident,
)
from app.db.session import psycopg_dsn
from app.ingest.synthetic import AUTOMATIC_EXCLUDED_SQL
from app.llm.base import LLMProfile
from app.llm.failover import ProviderChain
from app.logging import get_logger

log = get_logger(__name__)


class AgentService:
    def __init__(
        self, chain: ProviderChain, profile: LLMProfile, *, concurrency: int = 4, dsn: str | None = None
    ) -> None:
        self.chain, self.profile, self.dsn = chain, profile, dsn
        self.sem = asyncio.Semaphore(concurrency)
        self.personal_sem = asyncio.Semaphore(2)
        self._task: asyncio.Task[None] | None = None
        self._feedback_task: asyncio.Task[None] | None = None
        self._personal_task: asyncio.Task[None] | None = None
        self._reply_task: asyncio.Task[None] | None = None
        self._inflight: set[asyncio.Task[Any]] = set()
        self._by_signal: dict[int, asyncio.Task[Any]] = {}
        self._by_reply: dict[int, asyncio.Task[Any]] = {}
        self.processed = 0
        self.failed = 0
        self.enabled = True
        self.started_at = dt.datetime.now(dt.UTC)

    def start(self) -> None:
        if self._task is None or self._task.done():
            self._task = asyncio.create_task(self._loop(), name="agent-listener")
        if self._feedback_task is None or self._feedback_task.done():
            from app.agent.operator_feedback import worker

            self._feedback_task = asyncio.create_task(
                worker(lambda: (self.chain, self.profile), self.dsn), name="operator-feedback"
            )

        if self._personal_task is None or self._personal_task.done():
            self._personal_task = asyncio.create_task(self._personal_loop(), name="personal-chat-queue")
        if self._reply_task is None or self._reply_task.done():
            self._reply_task = asyncio.create_task(self._reply_loop(), name="tracking-replies")

    async def _reply_loop(self) -> None:
        """Восстанавливает доставленные ответы после рестарта или потери NOTIFY."""
        while True:
            try:
                if self.enabled:
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
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                log.warning("tracking_reply_queue_failed", error=type(exc).__name__)
            await asyncio.sleep(2)

    async def _personal_loop(self) -> None:
        # Публичный чат не ждёт восстановления старой фоновой очереди. Данные остаются в общем signals.
        while True:
            try:
                if self.enabled:
                    async with await self._conn() as conn:
                        rows = await (
                            await conn.execute(
                                "select s.id from signals s where s.channel_subtype='ui_pers_demo' and s.status='new' and not exists(select 1 from agent_runs a where a.signal_id=s.id and a.kind='agent' and a.outcome is distinct from 'failed') order by s.id limit 20"
                            )
                        ).fetchall()
                        await conn.commit()
                    for (sid,) in rows:
                        self.submit(int(sid), interactive=True)
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                log.warning("personal_queue_failed", error=type(exc).__name__)
            await asyncio.sleep(2)

    async def stop(self) -> None:
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
        for t in list(self._inflight):
            t.cancel()
        self._task = None

    async def _conn(self) -> psycopg.AsyncConnection[Any]:
        return await psycopg.AsyncConnection.connect(psycopg_dsn(self.dsn), autocommit=False)

    async def _recover(self) -> None:
        async with await self._conn() as conn:
            st = await (await conn.execute("select sim_time from sim_state where id = 1")).fetchone()
            sim_time = st[0] if st else dt.datetime.now(dt.UTC)
            await expire_hitl(conn, sim_time=sim_time, chain=self.chain, profile=self.profile)
            await wake_due_followups(conn, sim_time=sim_time, chain=self.chain, profile=self.profile)
            await conn.execute(
                "update agent_runs set outcome = 'failed', finished_at = now(), error = 'прерван рестартом' "
                "where kind = 'agent' and outcome is null and started_at < %s "
                "and not exists (select 1 from followups f where f.agent_run_id = agent_runs.id and f.status = 'scheduled') "
                f"and exists(select 1 from signals s where s.id=agent_runs.signal_id and not {AUTOMATIC_EXCLUDED_SQL})",
                (self.started_at,),
            )
            await conn.execute(
                "update signals s set status = 'new' where s.status = 'processing' and not exists(select 1 from agent_runs a where a.signal_id=s.id and a.started_at>=%s) "
                f"and not {AUTOMATIC_EXCLUDED_SQL}",
                (self.started_at,),
            )
            rows = await (
                await conn.execute(
                    "select s.id from signals s, sim_state st where st.id = 1 and s.run_id = st.current_run_id and s.status = 'new' "
                    "and s.origin <> 'scenario' and s.channel_subtype is distinct from 'ui_pers_demo' and s.received_sim >= st.sim_time - interval '2 hours' "
                    f"and not {AUTOMATIC_EXCLUDED_SQL} order by s.id limit 50"
                )
            ).fetchall()
            await conn.commit()
        for (sid,) in rows:
            self.submit(int(sid))

    async def _loop(self) -> None:
        with contextlib.suppress(Exception):
            await self._recover()
        while True:
            try:
                conn = await psycopg.AsyncConnection.connect(psycopg_dsn(self.dsn), autocommit=True)
                await conn.execute("LISTEN sim_events")
                log.info("agent_listen")
                async for n in conn.notifies():
                    if not self.enabled:
                        continue
                    try:
                        body = orjson.loads(n.payload)
                    except orjson.JSONDecodeError:
                        continue
                    if n.channel == "sim_events" and body.get("event_type") == "sla.tick":
                        sim_raw = body.get("sim_time")
                        if sim_raw:
                            st = dt.datetime.fromisoformat(sim_raw)
                            asyncio.create_task(self._expire_hitl(st), name="agent-expire-hitl")
                            asyncio.create_task(self._wake_followups(st), name="agent-wake-followups")
                    elif n.channel == "sim_events" and body.get("event_type") == "team.release":
                        sim_raw = body.get("sim_time")
                        payload = body.get("payload") or {}
                        inc_id = payload.get("incident_id")
                        if sim_raw and inc_id:
                            st = dt.datetime.fromisoformat(sim_raw)
                            asyncio.create_task(
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
                                continue
                            self.submit(
                                int(sid),
                                dt.datetime.fromisoformat(sim_time) if sim_time else None,
                                interactive=bool(source and source[0] == "ui_pers_demo"),
                            )
            except asyncio.CancelledError:
                raise
            except Exception as exc:  # noqa: BLE001
                log.warning("agent_listen_failed", error=str(exc)[:200])
                await asyncio.sleep(2)

    def submit(
        self, signal_id: int, sim_time: dt.datetime | None = None, *, interactive: bool = False
    ) -> asyncio.Task[Any]:
        existing = self._by_signal.get(signal_id)
        if existing is not None and not existing.done():
            return existing
        t = asyncio.create_task(
            self._process(signal_id, sim_time, interactive=True) if interactive else self._process(signal_id, sim_time),
            name=f"agent-{signal_id}",
        )
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

        task = asyncio.create_task(continue_reply(), name=f"client-reply-{child_id}")
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

    async def _expire_hitl(self, sim_time: dt.datetime) -> None:
        async with self.sem:
            try:
                async with await self._conn() as conn:
                    await expire_hitl(conn, sim_time=sim_time, chain=self.chain, profile=self.profile)
            except Exception as exc:  # noqa: BLE001
                log.warning("expire_hitl_failed", error=str(exc)[:200])

    async def _wake_followups(self, sim_time: dt.datetime) -> None:
        async with self.sem:
            try:
                async with await self._conn() as conn:
                    await wake_due_followups(conn, sim_time=sim_time, chain=self.chain, profile=self.profile)
            except Exception as exc:  # noqa: BLE001
                log.warning("wake_followups_failed", error=str(exc)[:200])

    async def _wake_incident_followups(self, incident_id: int, sim_time: dt.datetime) -> None:
        async with self.sem:
            try:
                async with await self._conn() as conn:
                    await wake_followups_for_incident(
                        conn, incident_id=incident_id, sim_time=sim_time, chain=self.chain, profile=self.profile
                    )
            except Exception as exc:  # noqa: BLE001
                log.warning("wake_release_followups_failed", incident_id=incident_id, error=str(exc)[:200])

    async def _process(self, signal_id: int, sim_time: dt.datetime | None, *, interactive: bool = False) -> None:
        semaphore = self.personal_sem if interactive else self.sem
        async with semaphore:
            try:
                async with await self._conn() as conn:
                    state = await process_signal(
                        conn, signal_id=signal_id, chain=self.chain, profile=self.profile, sim_time=sim_time
                    )
                if state is not None:
                    self.processed += 1
                    if state.get("outcome") == "failed":
                        self.failed += 1
                    elif state.get("outcome") == "deferred":
                        pass
            except Exception as exc:  # noqa: BLE001
                self.failed += 1
                log.warning("agent_process_failed", signal_id=signal_id, error=str(exc)[:200])

    async def resume(self, human_decision_id: int, sim_time: dt.datetime | None = None) -> dict[str, Any] | None:
        async with self.sem, await self._conn() as conn:
            state = await resume_after_human(
                conn, human_decision_id=human_decision_id, chain=self.chain, profile=self.profile, sim_time=sim_time
            )
        return dict(state) if state else None
