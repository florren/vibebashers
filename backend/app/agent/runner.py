"""AgentService (T-056 п. 2): слушает signal.received (LISTEN sim_events) и запускает проходы графа с ограничением параллелизма;
при старте дообрабатывает сигналы со статусом new и восстанавливает незавершённые проходы (interrupted → failed)."""

from __future__ import annotations

import asyncio
import contextlib
import datetime as dt
from typing import Any

import orjson
import psycopg

from app.agent.graph import expire_hitl, process_signal, resume_after_human
from app.db.session import psycopg_dsn
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
        self._task: asyncio.Task[None] | None = None
        self._inflight: set[asyncio.Task[Any]] = set()
        self.processed = 0
        self.failed = 0
        self.enabled = True

    def start(self) -> None:
        if self._task is None or self._task.done():
            self._task = asyncio.create_task(self._loop(), name="agent-listener")

    async def stop(self) -> None:
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
            await conn.execute(
                "update agent_runs set outcome = 'failed', finished_at = now(), error = 'прерван рестартом' where kind = 'agent' and outcome is null"
            )
            await conn.execute("update signals set status = 'new' where status = 'processing'")
            rows = await (
                await conn.execute(
                    "select s.id from signals s, sim_state st where st.id = 1 and s.run_id = st.current_run_id and s.status = 'new' "
                    "and s.origin <> 'scenario' and s.received_sim >= st.sim_time - interval '2 hours' order by s.id limit 50"
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
                            asyncio.create_task(
                                self._expire_hitl(dt.datetime.fromisoformat(sim_raw)),
                                name="agent-expire-hitl",
                            )
                    elif n.channel == "sim_events" and body.get("event_type") == "signal.received":
                        sid = (body.get("payload") or {}).get("signal_id")
                        sim_time = body.get("sim_time")
                        if sid:
                            self.submit(int(sid), dt.datetime.fromisoformat(sim_time) if sim_time else None)
            except asyncio.CancelledError:
                raise
            except Exception as exc:  # noqa: BLE001
                log.warning("agent_listen_failed", error=str(exc)[:200])
                await asyncio.sleep(2)

    def submit(self, signal_id: int, sim_time: dt.datetime | None = None) -> asyncio.Task[Any]:
        t = asyncio.create_task(self._process(signal_id, sim_time), name=f"agent-{signal_id}")
        self._inflight.add(t)
        t.add_done_callback(self._inflight.discard)
        return t

    async def _expire_hitl(self, sim_time: dt.datetime) -> None:
        async with self.sem:
            try:
                async with await self._conn() as conn:
                    await expire_hitl(conn, sim_time=sim_time, chain=self.chain, profile=self.profile)
            except Exception as exc:  # noqa: BLE001
                log.warning("expire_hitl_failed", error=str(exc)[:200])

    async def _process(self, signal_id: int, sim_time: dt.datetime | None) -> None:
        async with self.sem:
            try:
                async with await self._conn() as conn:
                    state = await process_signal(
                        conn, signal_id=signal_id, chain=self.chain, profile=self.profile, sim_time=sim_time
                    )
                if state is not None:
                    self.processed += 1
                    if state.get("outcome") == "failed":
                        self.failed += 1
            except Exception as exc:  # noqa: BLE001
                self.failed += 1
                log.warning("agent_process_failed", signal_id=signal_id, error=str(exc)[:200])

    async def resume(self, human_decision_id: int, sim_time: dt.datetime | None = None) -> dict[str, Any] | None:
        async with self.sem, await self._conn() as conn:
            state = await resume_after_human(
                conn, human_decision_id=human_decision_id, chain=self.chain, profile=self.profile, sim_time=sim_time
            )
        return dict(state) if state else None
