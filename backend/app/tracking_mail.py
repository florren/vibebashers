"""Квитанция публичного обращения в локальный Mailpit (T-120), без внешнего SMTP."""

from __future__ import annotations

import asyncio
import datetime as dt
import smtplib
from email.message import EmailMessage
from typing import Any

from app.config import get_settings
from app.logging import get_logger
from app.sim.events import dumps

log = get_logger(__name__)


def _send(message: EmailMessage) -> None:
    settings = get_settings()
    with smtplib.SMTP(settings.mailpit_host, settings.mailpit_port, timeout=5) as smtp:
        smtp.send_message(message)


async def send_tracking_receipt(
    conn: Any,
    *,
    signal_id: int,
    run_id: int,
    recipient: str,
    public_id: str,
    url: str,
    sim_time: dt.datetime,
    lang: str,
) -> None:
    settings = get_settings()
    if not settings.mailpit_enabled:
        return
    en = lang == "en"
    subject = f"Request {public_id} received" if en else f"Обращение {public_id} принято"
    body = (
        f"Your request has been received. Follow its progress and reply here: {url}\nKeep this private link."
        if en
        else f"Обращение принято. Следить за обработкой и отвечать на уточнения: {url}\nСохраните эту личную ссылку."
    )
    # Сама ссылка — секрет доступа. В центре уведомлений сохраняем только безопасный текст.
    safe_body = (
        "Your request has been received. Use the saved tracking link."
        if en
        else "Обращение принято. Используйте сохранённую ссылку для отслеживания."
    )
    row = await (
        await conn.execute(
            "insert into notifications(run_id,recipient_type,signal_id,channel_code,template_code,subject,body,status) "
            "values (%s,'client',%s,'email','tracking_link',%s,%s,'queued') returning id",
            (run_id, signal_id, subject, safe_body),
        )
    ).fetchone()
    notification_id = int(row["id"] if isinstance(row, dict) else row[0])
    message = EmailMessage()
    message["From"] = "noreply@example.com"
    message["To"] = recipient
    message["Subject"] = subject
    message.set_content(body)
    status = "sent"
    try:
        await asyncio.to_thread(_send, message)
    except (OSError, smtplib.SMTPException, ValueError) as exc:
        status = "failed"
        log.warning("tracking_mail_failed", signal_id=signal_id, error_type=type(exc).__name__)
    await conn.execute(
        "update notifications set status=%s,sent_sim=%s,sent_at=case when %s='sent' then now() else null end where id=%s",
        (status, sim_time if status == "sent" else None, status, notification_id),
    )
    await conn.execute(
        "select pg_notify('notifications',%s)",
        (dumps({"type": status, "run_id": run_id, "data": {"id": notification_id, "signal_id": signal_id}}),),
    )
