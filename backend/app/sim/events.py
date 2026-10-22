"""Шина событий симулятора: валидация по contracts/events (envelope + семейство), запись в sim_events и pg_notify('sim_events')."""

from __future__ import annotations

import datetime as dt
import uuid
from typing import Any

import orjson
import psycopg

from app.contracts.registry import validate
from app.logging import get_logger

log = get_logger(__name__)
FAMILY_SCHEMA = {
    "op": "sim/op",
    "fault": "sim/fault",
    "client_error": "sim/client_error",
    "signal": "sim/signal",
    "team": "sim/team_action",
    "sla": "sim/sla",
    "client": "behavior/client_event",
    "review": "sim/review",
    "abs": "sim/abs",
    "escalation": "sim/escalation",
    "zone": "sim/zone",
}


class EventValidationError(ValueError):
    pass


def _json_default(o: Any) -> Any:
    if isinstance(o, dt.datetime):
        return o.isoformat()
    if isinstance(o, uuid.UUID):
        return str(o)
    raise TypeError(type(o))


def dumps(obj: Any) -> str:
    return orjson.dumps(obj, default=_json_default).decode()


class EventBus:
    """Одно соединение psycopg (async). emit() вызывается внутри транзакции симулятора; NOTIFY уходит при commit."""

    def __init__(self, conn: psycopg.AsyncConnection[Any], *, strict: bool = True) -> None:
        self.conn = conn
        self.strict = strict
        self.emitted = 0

    async def emit(
        self,
        run_id: int,
        event_type: str,
        payload: dict[str, Any],
        sim_time: dt.datetime,
        *,
        correlation_id: uuid.UUID | None = None,
        causation_id: uuid.UUID | None = None,
        scenario_id: str | None = None,
    ) -> uuid.UUID:
        corr = correlation_id or uuid.uuid4()
        payload = {**payload, "event_type": event_type}
        env = {
            "run_id": run_id,
            "event_type": event_type,
            "sim_time": sim_time.isoformat(),
            "real_time": dt.datetime.now(dt.UTC).isoformat(),
            "correlation_id": str(corr),
            "scenario_id": scenario_id,
            "payload": orjson.loads(dumps(payload)),
        }
        if causation_id:
            env["causation_id"] = str(causation_id)
        errors = validate(env, "envelope")
        fam = event_type.split(".")[0]
        if fam in FAMILY_SCHEMA:
            errors += validate(env["payload"], FAMILY_SCHEMA[fam])
        if errors:
            if self.strict:
                raise EventValidationError(f"{event_type}: {errors[:3]}")
            log.warning("sim_event_invalid", event_type=event_type, errors=errors[:3])
        row = await (
            await self.conn.execute(
                "insert into sim_events (run_id, event_type, payload, sim_time, scenario_id, correlation_id) values (%s, %s, %s::jsonb, %s, %s, %s) returning id",
                (run_id, event_type, dumps(env["payload"]), sim_time, scenario_id, corr),
            )
        ).fetchone()
        env["id"] = row[0] if row else None
        await self.conn.execute("select pg_notify('sim_events', %s)", (dumps(env),))
        self.emitted += 1
        return corr
