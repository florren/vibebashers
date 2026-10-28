"""Реакции двойника на новые уведомления: роль twin, отдельный след, лимиты и идемпотентность."""

from __future__ import annotations

import asyncio
import contextlib
import dataclasses
import json
import time
from typing import Any

import psycopg
from psycopg.rows import dict_row
from psycopg.types.json import Jsonb

from app.agent.prompts import load
from app.contracts.registry import deref, validate_schema
from app.db.session import psycopg_dsn
from app.ingest.normalizer import create_signal
from app.llm.base import LLMProfile, ProviderError
from app.llm.failover import ProviderChain
from app.logging import get_logger
from app.realtime.hub import hub
from app.trace.privacy import mask

log = get_logger(__name__)


class TwinService:
    def __init__(self, chain: ProviderChain, profile: LLMProfile) -> None:
        self.chain, self.profile = chain, profile
        self._task: asyncio.Task[None] | None = None

    def start(self) -> None:
        self._task = asyncio.create_task(self._loop(), name="client-twins")

    async def stop(self) -> None:
        if self._task is not None:
            self._task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self._task
            self._task = None

    async def _loop(self) -> None:
        watermark: int | None = None
        pending: dict[int, float] = {}
        while True:
            try:
                async with await psycopg.AsyncConnection.connect(
                    psycopg_dsn(), autocommit=True, row_factory=dict_row, connect_timeout=3
                ) as conn:
                    if watermark is None:
                        await conn.execute(
                            "update agent_runs set outcome='failed',finished_at=now(),error='twin interrupted: server restarted' where kind='client_twin' and outcome is null"
                        )
                        row = await (await conn.execute("select coalesce(max(id),0) id from notifications")).fetchone()
                        watermark = int(row["id"]) if row else 0
                    rows = await (
                        await conn.execute(
                            "select n.id from notifications n join sim_state st on st.current_run_id=n.run_id "
                            "where n.id>%s and n.recipient_type in ('client','public') and n.client_id is not null "
                            "and n.signal_id is not null and n.status in ('sent','delivered') order by n.id limit 20",
                            (watermark,),
                        )
                    ).fetchall()
                    for row in rows:
                        pending[int(row["id"])] = time.monotonic()
                        watermark = int(row["id"])
                    for notification_id, queued_at in list(pending.items()):
                        ready = await (
                            await conn.execute(
                                "select n.run_id=st.current_run_id current_run, exists(select 1 from agent_runs a "
                                "where a.signal_id=n.signal_id and a.kind='agent' and a.finished_at is not null) ready "
                                "from notifications n cross join sim_state st where st.id=1 and n.id=%s",
                                (notification_id,),
                            )
                        ).fetchone()
                        if not ready or not ready["current_run"]:
                            pending.pop(notification_id)
                        elif ready["ready"]:
                            await self.react(conn, notification_id)
                            pending.pop(notification_id)
                        elif time.monotonic() - queued_at > 300:
                            # Незавершённый агент не удерживает уведомления бесконечно.
                            log.warning("twin_notification_expired", notification_id=notification_id)
                            pending.pop(notification_id)
                    # Ограничение памяти на случай массового сбоя агента.
                    while len(pending) > 1000:
                        notification_id = next(iter(pending))
                        pending.pop(notification_id)
                        log.warning("twin_queue_full", notification_id=notification_id)
            except (psycopg.Error, OSError) as exc:
                log.warning("twin_worker_unavailable", error_type=type(exc).__name__)
            await asyncio.sleep(1)

    async def react(self, conn: psycopg.AsyncConnection[Any], notification_id: int) -> int | None:
        """Один ответ на уведомление. Advisory lock сериализует бюджет внутри запуска."""
        async with conn.transaction():
            row = await (
                await conn.execute(
                    "select n.*,c.segment_code,c.psychotype_code,s.origin,s.parent_signal_id,s.external_post_id "
                    "from notifications n join clients c on c.id=n.client_id "
                    "join signals s on s.id=n.signal_id and s.run_id=n.run_id "
                    "where n.id=%s and c.is_active and n.recipient_type in ('client','public') and n.status in ('sent','delivered')",
                    (notification_id,),
                )
            ).fetchone()
            if not row or row["parent_signal_id"] is not None:
                return None
            run_id, client_id = row["run_id"], row["client_id"]
            locked = await (
                await conn.execute("select pg_try_advisory_xact_lock(hashtextextended(%s,0)) ok", (f"twins:{run_id}",))
            ).fetchone()
            if not locked or not locked["ok"]:
                return None
            exists = await (
                await conn.execute(
                    "select id from agent_runs where thread_id=%s and kind='client_twin'", (f"twin:{notification_id}",)
                )
            ).fetchone()
            if exists:
                return None
            settings = await (await conn.execute("select value from settings where key='twins'")).fetchone()
            config = (settings or {}).get("value") or {}
            if not config.get("enabled", True):
                return None
            hitl = await (
                await conn.execute("select id from human_decisions where signal_id=%s limit 1", (row["signal_id"],))
            ).fetchone()
            highlighted = row["segment_code"] in ("vip", "ultra_vip") or row["origin"] in ("scenario", "jury") or hitl
            if not highlighted and client_id % 100 >= 10:
                return None
            sim_time = row["sent_sim"]
            if sim_time is None:
                return None
            usage = await (
                await conn.execute(
                    "select count(*) filter(where kind='client_twin') calls, "
                    "coalesce(sum(total_tokens) filter(where kind='client_twin'),0) twin_tokens, "
                    "coalesce(sum(total_tokens) filter(where kind='agent'),0) agent_tokens "
                    "from agent_runs where sim_run_id=%s and started_sim::date=%s::date",
                    (run_id, sim_time.date()),
                )
            ).fetchone()
            assert usage is not None
            if usage["calls"] >= max(0, int(config.get("daily_limit", 20))):
                return None
            visible = {
                "segment": row["segment_code"],
                "psychotype": row["psychotype_code"],
                "message": mask(row["body"], 1500),
            }
            prompt = load("twin")
            content = json.dumps(visible, ensure_ascii=False)
            # Верхняя оценка входа и ограниченный запас ответа; при нулевом бюджете LLM не вызывается.
            estimate = (
                len(prompt.body) + len(content) + len(json.dumps(deref("agent/client_twin_reaction")))
            ) // 2 + 400
            remaining = (
                int(usage["agent_tokens"] * min(0.15, max(0, float(config.get("token_share", 0.15)))))
                - usage["twin_tokens"]
            )
            if remaining < estimate:
                return None
            profile = self.chain.profile_for("twin", self.profile)
            profile = dataclasses.replace(
                profile,
                extra={
                    **profile.extra,
                    "request": {**profile.extra.get("request", {}), "max_tokens": 400},
                    "structured_attempts": 1,
                },
            )
            selected = await (
                await conn.execute("select id from llm_profiles where code=%s", (profile.code,))
            ).fetchone()
            created = await (
                await conn.execute(
                    "insert into agent_runs(kind,sim_run_id,signal_id,incident_id,client_id,llm_profile_id,prompt_version,graph_version,thread_id,started_sim) "
                    "values('client_twin',%s,%s,%s,%s,%s,%s,'twin-v1',%s,%s) returning id",
                    (
                        run_id,
                        row["signal_id"],
                        row["incident_id"],
                        client_id,
                        selected["id"] if selected else None,
                        prompt.version,
                        f"twin:{notification_id}",
                        sim_time,
                    ),
                )
            ).fetchone()
            assert created is not None
            agent_id = int(created["id"])
        try:
            result = await self.chain.complete_structured(
                [{"role": "system", "content": prompt.body}, {"role": "user", "content": content}],
                deref("agent/client_twin_reaction"),
                profile,
            )
            errors = validate_schema(result.obj, deref("agent/client_twin_reaction"))
            if errors:
                raise ProviderError("bad_output", "ответ двойника не соответствует схеме")
        except ProviderError as exc:
            async with conn.transaction():
                await conn.execute(
                    "update agent_runs set outcome='failed',finished_at=now(),error=%s where id=%s",
                    (f"twin: {exc.kind}", agent_id),
                )
            return agent_id
        async with conn.transaction():
            obj = result.obj
            text = mask(obj["text_ru"], 1500) if obj["text_ru"] else ""
            actual = result.usage
            await conn.execute(
                "update agent_runs set outcome=%s,finished_at=now(),total_tokens=%s,prompt_tokens=%s,completion_tokens=%s,total_latency_ms=%s,cost_estimate=%s where id=%s",
                (
                    "fallback_mock" if result.fallback_mock else "completed",
                    actual.total_tokens,
                    actual.prompt_tokens,
                    actual.completion_tokens,
                    actual.latency_ms,
                    profile.cost(actual.prompt_tokens, actual.completion_tokens),
                    agent_id,
                ),
            )
            await conn.execute(
                "insert into agent_steps(run_id,seq,node,status,input,output,model,prompt_tokens,completion_tokens,latency_ms,finished_at) values(%s,1,'twin_react',%s,%s,%s,%s,%s,%s,%s,now())",
                (
                    agent_id,
                    "fallback" if result.fallback_mock else "ok",
                    Jsonb({"notification_id": notification_id}),
                    Jsonb({**obj, "text_ru": text, "llm_source": actual.source}),
                    actual.model or profile.model,
                    actual.prompt_tokens,
                    actual.completion_tokens,
                    actual.latency_ms,
                ),
            )
            await conn.execute(
                "insert into client_reactions(run_id,client_id,signal_id,incident_id,notification_id,reaction,tone,satisfaction,text,generated_by,agent_run_id,reacted_sim) values(%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)",
                (
                    run_id,
                    client_id,
                    row["signal_id"],
                    row["incident_id"],
                    notification_id,
                    obj["reaction"],
                    obj["tone"],
                    obj["satisfaction"],
                    text,
                    "mock" if actual.source == "mock" else "llm",
                    agent_id,
                    sim_time,
                ),
            )
            await conn.execute(
                "update client_states set care_score=%s where client_id=%s and run_id=%s and is_current",
                (obj["satisfaction"], client_id, run_id),
            )
            if obj["reaction"] in ("asks_again", "escalates") and text:
                # Старые стенды могут ещё не иметь нового справочника: регистрируем только свой источник.
                await conn.execute(
                    "insert into ingest_sources(code,kind,channel_code,is_external) values('client_twin','rest','chat',false) on conflict(code) do nothing"
                )
                ingested = await create_signal(
                    conn,
                    {
                        "external_id": f"twin:{notification_id}",
                        "channel": "chat",
                        "client": {"client_id": client_id},
                        "text": text,
                        "timestamp": sim_time.isoformat(),
                        "geo": {"source": "none"},
                        "origin": "twin",
                        "meta": {"parent_signal_id": row["signal_id"], "client_twin": True},
                    },
                    source_code="client_twin",
                    run_id=run_id,
                    sim_time=sim_time,
                )
                if ingested["status"] == "rejected":
                    raise ValueError("приёмный слой отклонил ответ двойника")
            # Подписчики получают только безопасную проекцию; записи уже находятся в транзакции.
        await hub.publish(
            "clients",
            "client.reaction",
            {"client_id": client_id, "agent_run_id": agent_id, "reaction": obj["reaction"], "text": text},
            run_id=run_id,
        )
        await hub.publish(
            "agent",
            "run_finished",
            {
                "agent_run_id": agent_id,
                "signal_id": row["signal_id"],
                "kind": "client_twin",
                "llm_source": actual.source,
            },
            run_id=run_id,
        )
        return agent_id
