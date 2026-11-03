"""Durable admission перед Bot API; uncertain outcomes никогда не resend автоматически."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from typing import Any, Protocol
from uuid import UUID

import psycopg
from psycopg.rows import dict_row

from app.config import get_settings
from app.db.session import psycopg_dsn
from app.logging import get_logger
from app.sim.events import dumps
from app.sim.maintenance import MaintenanceBusy, completion, writer_lease
from app.sim.maintenance_db import public_operation
from app.tgbot.configuration import TransportConfiguration, configured
from app.tgbot.outbox import notification_hash, target_for_notification
from app.tgbot.storage import InboundStore, lock_id
from app.tgbot.telegram import DeliveryError, TelegramClient

log = get_logger(__name__)
Connection = psycopg.AsyncConnection[dict[str, Any]]


class Sender(Protocol):
    async def send(self, payload: dict[str, Any]) -> str: ...


@dataclass(frozen=True)
class Claim:
    key: UUID
    notification_id: int
    run_id: int
    body_hash: str
    payload: dict[str, Any] = field(repr=False)


async def _note(conn: Connection, key: UUID) -> dict[str, Any] | None:
    return await (await conn.execute("select * from notifications where delivery_key=%s", (key,))).fetchone()


def _matches(note: dict[str, Any] | None, receipt: dict[str, Any]) -> bool:
    return (
        note is not None
        and note["id"] == receipt["notification_id"]
        and note["run_id"] == receipt["run_id"]
        and notification_hash(note) == receipt["body_hash"]
    )


async def _publish(conn: Connection, note: dict[str, Any], status: str) -> None:
    await conn.execute(
        "select pg_notify('notifications',%s)",
        (dumps({"type": status, "run_id": note["run_id"], "data": {"notification_id": note["id"], "status": status}}),),
    )


async def _recover_and_reconcile(conn: Connection, config: TransportConfiguration) -> None:
    # Caller владеет bot session lock: другой cooperating worker не выполняет HTTP.
    async with conn.transaction():
        stale = await (
            await conn.execute(
                "update channel_runtime.telegram_deliveries set status='unknown', "
                "error_code='telegram_worker_interrupted',completed_at=clock_timestamp() "
                "where bot_id=%s and status='claimed' returning *",
                (config.bot_id,),
            )
        ).fetchall()
        for receipt in stale:
            note = await _note(conn, receipt["delivery_key"])
            if _matches(note, receipt) and note is not None and note["status"] == "queued":
                await conn.execute(
                    "update notifications set status='unknown' where delivery_key=%s", (receipt["delivery_key"],)
                )
                await _publish(conn, note, "unknown")
        # Bank restore может вернуть queued строку с уже завершённой delivery identity.
        final = await (
            await conn.execute(
                "select d.* from channel_runtime.telegram_deliveries d join notifications n "
                "on n.delivery_key=d.delivery_key where d.bot_id=%s and n.status='queued' "
                "and d.status in ('sent','failed','unknown','suppressed') order by d.created_at limit 100",
                (config.bot_id,),
            )
        ).fetchall()
        for receipt in final:
            note = await _note(conn, receipt["delivery_key"])
            if _matches(note, receipt) and note is not None:
                await conn.execute(
                    "update notifications set status=%s,external_ref=%s,sent_sim=%s, "
                    "sent_at=case when %s='sent' then %s else null end where delivery_key=%s",
                    (
                        receipt["status"],
                        receipt["external_ref"],
                        receipt["sent_sim"],
                        receipt["status"],
                        receipt["completed_at"],
                        receipt["delivery_key"],
                    ),
                )
                await _publish(conn, note, receipt["status"])


async def _valid_target(conn: Connection, config: TransportConfiguration, note: dict[str, Any], chat_id: int) -> bool:
    if note["recipient_type"] != "client":
        return False
    if note["template_code"] == "bot_dialogue" and note["signal_id"] is None and note["client_id"] is None:
        return True  # Создан только signed inbound, не из LLM/template dispatcher.
    return await target_for_notification(conn, config, note) == chat_id


async def _claim(conn: Connection, config: TransportConfiguration) -> Claim | None:
    async with conn.transaction():
        row = await (
            await conn.execute(
                "select d.* from channel_runtime.telegram_deliveries d left join channel_runtime.telegram_chat_rate r "
                "on r.bot_id=d.bot_id and r.chat_id=d.chat_id where d.bot_id=%s and d.status='queued' "
                "and (r.last_claimed_at is null or r.last_claimed_at<=clock_timestamp()-interval '1 second') "
                "order by d.created_at,d.delivery_key for update of d skip locked limit 1",
                (config.bot_id,),
            )
        ).fetchone()
        if row is None:
            return None
        lease = await (
            await conn.execute(
                "select pg_try_advisory_lock_shared(%s) as acquired", (lock_id("run", 0, row["run_id"]),)
            )
        ).fetchone()
        if not lease or not lease["acquired"]:
            return None
        note = await _note(conn, row["delivery_key"])
        valid = _matches(note, row) and note is not None and note["status"] == "queued"
        if valid and note is not None:
            valid = await _valid_target(conn, config, note, row["chat_id"])
        if not valid:
            await conn.execute(
                "update channel_runtime.telegram_deliveries set status='failed',error_code='telegram_stale_target',completed_at=clock_timestamp() where delivery_key=%s",
                (row["delivery_key"],),
            )
            if _matches(note, row) and note is not None and note["status"] == "queued":
                await conn.execute(
                    "update notifications set status='failed' where delivery_key=%s", (row["delivery_key"],)
                )
                await _publish(conn, note, "failed")
            return None
        payload = await InboundStore(config.app_secret).decrypt(conn, row["payload_enc"])
        if type(payload.get("chat_id")) is not int or payload["chat_id"] != row["chat_id"]:
            raise ValueError("telegram_payload_identity_invalid")
        await conn.execute(
            "insert into channel_runtime.telegram_chat_rate(bot_id,chat_id,last_claimed_at) "
            "values(%s,%s,clock_timestamp()) on conflict(bot_id,chat_id) do update set last_claimed_at=excluded.last_claimed_at",
            (config.bot_id, row["chat_id"]),
        )
        await conn.execute(
            "update channel_runtime.telegram_deliveries set status='claimed',claimed_at=clock_timestamp() where delivery_key=%s",
            (row["delivery_key"],),
        )
        return Claim(row["delivery_key"], row["notification_id"], row["run_id"], row["body_hash"], payload)


async def _finish(conn: Connection, claim: Claim, status: str, code: str | None, external_ref: str | None) -> None:
    async with conn.transaction():
        await conn.execute("set local lock_timeout='5s'")
        # Пока HTTP ожидает ACK, оператор может выбрать другой run с другими часами.
        # Реальная доставка подтверждена; sim time вне своего current run неизвестен.
        sim = await (
            await conn.execute("select sim_time from sim_state where id=1 and current_run_id=%s", (claim.run_id,))
        ).fetchone()
        sent_sim = sim["sim_time"] if status == "sent" and sim else None
        row = await (
            await conn.execute(
                "update channel_runtime.telegram_deliveries set status=%s,error_code=%s,external_ref=%s,sent_sim=%s,completed_at=clock_timestamp() "
                "where delivery_key=%s and status='claimed' returning completed_at",
                (status, code, external_ref, sent_sim, claim.key),
            )
        ).fetchone()
        if row is None:
            raise ValueError("telegram_claim_lost")
        note = await _note(conn, claim.key)
        if (
            note is not None
            and note["id"] == claim.notification_id
            and note["run_id"] == claim.run_id
            and notification_hash(note) == claim.body_hash
        ):
            await conn.execute(
                "update notifications set status=%s,external_ref=%s,sent_sim=%s,sent_at=case when %s='sent' then %s else null end where delivery_key=%s",
                (status, external_ref, sent_sim, status, row["completed_at"], claim.key),
            )
            await _publish(conn, note, status)


async def deliver_once(config: TransportConfiguration, sender: Sender, *, dsn: str | None = None) -> bool:
    async with writer_lease("tgbot"), public_operation(dsn):
        async with await psycopg.AsyncConnection.connect(
            psycopg_dsn(dsn), autocommit=True, row_factory=dict_row
        ) as conn:
            owner = await (
                await conn.execute(
                    "select pg_try_advisory_lock(%s) as acquired", (lock_id("worker", config.bot_id, 0),)
                )
            ).fetchone()
            if not owner or not owner["acquired"]:
                return False
            await _recover_and_reconcile(conn, config)
            claim = await _claim(conn, config)
            if claim is None:
                return False
            try:
                external_ref = await asyncio.wait_for(sender.send(claim.payload), 15)
            except asyncio.CancelledError:
                finalizer = asyncio.create_task(_finish(conn, claim, "unknown", "telegram_send_cancelled", None))
                try:
                    await completion(finalizer, propagate_cancel=False)
                except Exception as exc:
                    log.error("telegram_finalize_failed", error_type=type(exc).__name__)
                raise
            except DeliveryError as exc:
                await _finish(conn, claim, "failed" if exc.kind == "rejected" else "unknown", exc.code, None)
            except (TimeoutError, OSError) as exc:
                await _finish(conn, claim, "unknown", "telegram_send_unknown", None)
                log.warning("telegram_send_unknown", error_type=type(exc).__name__)
            except Exception as exc:
                await _finish(conn, claim, "unknown", "telegram_worker_error", None)
                log.error("telegram_send_failed", error_type=type(exc).__name__)
            else:
                await _finish(conn, claim, "sent", None, external_ref)
            return True


async def worker() -> None:
    try:
        config = configured(get_settings())
    except ValueError:
        log.warning("telegram_transport_not_configured")
        return
    if config is None:
        return
    client = TelegramClient(config.token)
    try:
        while True:
            try:
                current = configured(get_settings())
            except ValueError:
                current = None
            if current != config:
                log.warning("telegram_configuration_changed_restart_required")
                return
            try:
                worked = await deliver_once(config, client)
            except MaintenanceBusy:
                worked = False
            except Exception as exc:
                log.error("telegram_delivery_failed", error_type=type(exc).__name__)
                worked = False
            if not worked:
                await asyncio.sleep(0.25)
    finally:
        try:
            await client.aclose()
        except Exception as exc:
            log.error("telegram_client_close_failed", error_type=type(exc).__name__)
