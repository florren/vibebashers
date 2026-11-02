"""Durable evidence/receipt storage: только переданное соединение и внешняя TX.

Actual0017 принадлежит run. Модуль не создаёт таблицы, не открывает соединения
и не выполняет commit; внешние producer и Sim owner передают свою TX.
"""

from __future__ import annotations

import datetime as dt
from typing import Any

import psycopg
from psycopg.pq import TransactionStatus
from psycopg.rows import tuple_row

from app.agent.tools.base import ClientStateIntent, StateEvidenceResult


def positive_ids(*values: int) -> None:
    if any(isinstance(value, bool) or not isinstance(value, int) or value <= 0 for value in values):
        raise ValueError("behavior IDs должны быть положительными int без bool")


class BehaviorStore:
    def __init__(self, conn: psycopg.AsyncConnection[Any]) -> None:
        self.conn = conn

    def require_transaction(self) -> None:
        if self.conn.info.transaction_status != TransactionStatus.INTRANS:
            raise ValueError("behavior требует внешнюю tick transaction")

    async def _one(self, sql: str, values: tuple[Any, ...]) -> Any:
        async with self.conn.cursor(row_factory=tuple_row) as cur:
            await cur.execute(sql, values)
            return await cur.fetchone()

    async def enqueue_operation(self, *, run_id: int, operation_id: int) -> bool:
        """Timestamp/client/fault берутся из реальной failed операции, не из payload."""
        self.require_transaction()
        positive_ids(run_id, operation_id)
        row = await self._one(
            "select client_id,started_sim,behavior_valid_failed_operation(id,%s) from operations where id=%s and run_id=%s",
            (run_id, operation_id, run_id),
        )
        if row is None or row[2] is not True:
            raise ValueError("нет failed операции с подтверждённой run/system/code/time/region связью")
        return await self._enqueue(run_id, row[0], "operation", operation_id, row[1])

    async def enqueue_fault(self, *, run_id: int, fault_id: int) -> int:
        """fault.started: полный набор известных failed operations, не sample50/потенциальные клиенты."""
        self.require_transaction()
        positive_ids(run_id, fault_id)
        known = await self._one("select id from faults where id=%s and run_id=%s", (fault_id, run_id))
        status = await self._one("select kind,status from sim_runs where id=%s", (run_id,))
        if (
            known is None
            or status is None
            or status[0] not in ("free", "scenario")
            or status[1] not in ("running", "paused", "interrupted")
        ):
            raise ValueError("fault отсутствует в открытом free/scenario run")
        invalid = await self._one(
            "select id from operations where fault_id=%s and run_id=%s and status='failed' "
            "and not behavior_valid_failed_operation(id,%s) limit 1",
            (fault_id, run_id, run_id),
        )
        if invalid is not None:
            raise ValueError("fault содержит failed operation с неподтверждённой причинной связью")
        cursor = await self.conn.execute(
            "insert into behavior_evidence(run_id,client_id,source_kind,source_id,observed_sim) "
            "select run_id,client_id,'operation',id,started_sim from operations where run_id=%s and fault_id=%s and status='failed' "
            "on conflict do nothing",
            (run_id, fault_id),
        )
        return int(cursor.rowcount)

    async def enqueue_notification(self, *, run_id: int, notification_id: int) -> bool:
        self.require_transaction()
        positive_ids(run_id, notification_id)
        row = await self._one(
            "select n.client_id,n.sent_sim,n.status from notifications n where n.id=%s and n.run_id=%s "
            "and n.recipient_type in ('client','public') and n.client_id is not null",
            (notification_id, run_id),
        )
        if row is None:
            raise ValueError("notification не имеет явного клиента в этом запуске")
        if row[2] not in ("sent", "delivered"):
            return False
        if row[1] is None:
            raise ValueError("sent notification без фактического sim timestamp")
        return await self._enqueue(run_id, row[0], "notification", notification_id, row[1])

    async def enqueue_twin(self, *, run_id: int, reaction_id: int) -> bool:
        """Satisfaction остаётся observation; UPDATE client_states здесь запрещён."""
        self.require_transaction()
        positive_ids(run_id, reaction_id)
        row = await self._one(
            "select client_id,reacted_sim from client_reactions where id=%s and run_id=%s", (reaction_id, run_id)
        )
        if row is None:
            raise ValueError("twin reaction отсутствует в запуске")
        return await self._enqueue(run_id, row[0], "twin_reaction", reaction_id, row[1])

    async def enqueue_sla(self, *, run_id: int, client_id: int, event_id: int) -> bool:
        self.require_transaction()
        positive_ids(run_id, client_id, event_id)
        event = await self._one(
            "select event_type,payload,sim_time from sim_events where id=%s and run_id=%s", (event_id, run_id)
        )
        if event is None or event[0] not in ("sla.breached", "sla.report_missing", "sla.first_response_overdue"):
            raise ValueError("нет проверяемого SLA breach события")
        runtime = await self._one(
            "select episode_no from behavior_runtime where run_id=%s and client_id=%s", (run_id, client_id)
        )
        if runtime is None:
            return False
        from app.sim.behavior.facts import related

        if not await related(
            self.conn,
            {"run_id": run_id, "client_id": client_id, "episode_no": runtime[0]},
            signal_id=event[1].get("signal_id"),
            incident_id=event[1].get("incident_id"),
        ):
            return False
        return await self._enqueue(run_id, client_id, "sla", event_id, event[2])

    async def enqueue_resolution(self, *, run_id: int, client_id: int, incident_id: int) -> bool:
        self.require_transaction()
        positive_ids(run_id, client_id, incident_id)
        incident = await self._one(
            "select coalesce(resolved_sim,closed_sim),status from incidents where id=%s and run_id=%s",
            (incident_id, run_id),
        )
        if incident is None or incident[1] not in ("resolved", "closed") or incident[0] is None:
            raise ValueError("нет фактически resolved incident")
        runtime = await self._one(
            "select episode_no from behavior_runtime where run_id=%s and client_id=%s", (run_id, client_id)
        )
        if runtime is None:
            return False
        from app.sim.behavior.facts import related

        if not await related(
            self.conn,
            {"run_id": run_id, "client_id": client_id, "episode_no": runtime[0]},
            signal_id=None,
            incident_id=incident_id,
        ):
            return False
        return await self._enqueue(run_id, client_id, "resolution", incident_id, incident[0])

    async def current_effect_time(self, run_id: int, *, include_live: bool = False) -> dt.datetime | None:
        """Native clock только своего current run; SHARE фиксирует status до commit."""
        if self.conn.autocommit and self.conn.info.transaction_status != TransactionStatus.INTRANS:
            raise ValueError("effect fence требует внешнюю transaction")
        # Первая statement легитимно открывает implicit caller TX; commit здесь нет.
        row = await self._one("select kind,status from sim_runs where id=%s for share", (run_id,))
        self.require_transaction()
        kinds = ("free", "scenario", "live") if include_live else ("free", "scenario")
        if row is None or row[0] not in kinds or row[1] not in ("running", "paused", "interrupted"):
            return None
        current = await self._one("select sim_time from sim_state where id=1 and current_run_id=%s", (run_id,))
        if not current:
            return None
        at = current[0]
        if not isinstance(at, dt.datetime) or at.utcoffset() is None:
            raise ValueError("current SimTime должен быть aware timestamp")
        return at

    async def active_run(self, run_id: int) -> bool:
        """SHARE/current gate без SimState lock после money locks."""
        return await self.current_effect_time(run_id) is not None

    async def _enqueue(self, run_id: int, client_id: int, kind: str, source_id: int, at: dt.datetime) -> bool:
        row = await self._one("select kind,status from sim_runs where id=%s", (run_id,))
        if row is None or row[0] not in ("free", "scenario") or row[1] not in ("running", "paused", "interrupted"):
            raise ValueError("behavior evidence разрешён только в открытом free/scenario run")
        inserted = await self._one(
            "insert into behavior_evidence(run_id,client_id,source_kind,source_id,observed_sim) "
            "values(%s,%s,%s,%s,%s) on conflict do nothing returning id",
            (run_id, client_id, kind, source_id, at),
        )
        return inserted is not None

    async def receipt(
        self, *, run_id: int, client_id: int, source_kind: str, source_id: int, action: str, at: dt.datetime
    ) -> bool:
        self.require_transaction()
        positive_ids(run_id, client_id, source_id)
        inserted = await self._one(
            "insert into behavior_receipts(run_id,client_id,source_kind,source_id,action,consumed_sim) "
            "values(%s,%s,%s,%s,%s,%s) on conflict do nothing returning source_id",
            (run_id, client_id, source_kind, source_id, action, at),
        )
        return inserted is not None


async def record_twin_evidence(conn: psycopg.AsyncConnection[Any], run_id: int, reaction_id: int) -> bool:
    """Callback TwinService: тот же commit сохраняет observation и durable evidence."""
    await BehaviorStore(conn).enqueue_twin(run_id=run_id, reaction_id=reaction_id)
    return True


async def record_agent_state_intent(
    conn: psycopg.AsyncConnection[Any], intent: ClientStateIntent
) -> StateEvidenceResult:
    """Graph TX пишет запрос; actual state меняет только owner после проверки фактов."""
    from app.contracts.enums import ClientState

    store = BehaviorStore(conn)
    store.require_transaction()
    if intent.signal_id is None:
        raise ValueError("agent state intent требует фактический signal_id")
    positive_ids(intent.run_id, intent.agent_run_id, intent.client_id, intent.signal_id)
    ClientState(intent.requested_state)
    if not isinstance(intent.trigger, str) or not 1 <= len(intent.trigger) <= 128:
        raise ValueError("agent state trigger должен иметь длину 1..128")
    if not isinstance(intent.at, dt.datetime) or intent.at.utcoffset() is None:
        raise ValueError("agent state требует aware sim_time")
    actual = await store._one(
        "select s.id from agent_runs a join signals s on s.id=a.signal_id "
        "where a.id=%s and a.sim_run_id=%s and s.id=%s and s.run_id=%s and s.client_id=%s "
        "and (a.client_id is null or a.client_id=s.client_id) and s.received_sim<=%s "
        "and (%s::bigint is null or exists(select 1 from incidents i where i.id=%s and i.run_id=s.run_id "
        "and (a.incident_id=i.id or exists(select 1 from incident_signals x where x.incident_id=i.id and x.signal_id=s.id))))",
        (
            intent.agent_run_id,
            intent.run_id,
            intent.signal_id,
            intent.run_id,
            intent.client_id,
            intent.at,
            intent.incident_id,
            intent.incident_id,
        ),
    )
    if actual is None:
        raise ValueError("agent state intent не принадлежит signal/client/run")
    observed_at = await store.current_effect_time(intent.run_id)
    if observed_at is None:
        return StateEvidenceResult(False, None, "inactive_run")
    # Проверка policy/legacy выполняется повторно в write TX после status pin.
    from app.sim.behavior.runtime import require_run

    await require_run(conn, intent.run_id)
    row = await store._one(
        "insert into behavior_agent_intents(run_id,agent_run_id,client_id,signal_id,incident_id,requested_state,trigger,observed_sim) "
        "values(%s,%s,%s,%s,%s,%s,%s,%s) on conflict(run_id,agent_run_id,client_id,signal_id,incident_id,requested_state,trigger) "
        "do update set trigger=excluded.trigger returning id",
        (
            intent.run_id,
            intent.agent_run_id,
            intent.client_id,
            intent.signal_id,
            intent.incident_id,
            intent.requested_state,
            intent.trigger,
            observed_at,
        ),
    )
    assert row is not None
    await store._enqueue(intent.run_id, intent.client_id, "agent_state", row[0], observed_at)
    return StateEvidenceResult(True, int(row[0]))
