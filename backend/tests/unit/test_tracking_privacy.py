"""Секретные ссылки не попадают в диагностику; SMTP-заголовки защищены от подстановки."""

import logging

from app.api.public import _email_ok, _human
from app.logging import PublicTokenFilter
from app.observability.http import safe_public_path


def test_public_path_masks_whole_token() -> None:
    assert safe_public_path("/api/public/track/secret-token") == "/api/public/track/{token}"
    assert safe_public_path("/track/secret-token") == "/track/{token}"
    assert safe_public_path("/api/signals/123") == "/api/signals/123"


def test_uvicorn_access_log_masks_token_and_query() -> None:
    record = logging.LogRecord(
        "uvicorn.access",
        20,
        "",
        0,
        '%s - "%s %s HTTP/%s" %d',
        ("127.0.0.1", "GET", "/track/private-capability?x=1", "1.1", 200),
        None,
    )
    assert PublicTokenFilter().filter(record)
    assert "private-capability" not in record.getMessage()
    assert "/track/{token}" in record.getMessage()


def test_safe_public_copy_and_synthetic_email() -> None:
    assert _human("Обращение SIG-123 принято") == "Обращение SIG-123 принято"
    assert _human("LLM_ERROR or team_payments") is None
    assert _human("Телефон +7 900 001-22-33") == "Телефон +7 900 ***-**-**"
    assert _email_ok("guest@example.com")
    assert not _email_ok("guest\r\nBcc: other@example.com")
    assert not _email_ok("guest@real-domain.org")


def test_mailpit_smtp_adapter_uses_configured_local_sink(monkeypatch) -> None:
    from email.message import EmailMessage
    from types import SimpleNamespace

    from app import tracking_mail

    sent = []

    class FakeSMTP:
        def __init__(self, host, port, *, timeout):
            assert (host, port, timeout) == ("127.0.0.1", 1025, 5)

        def __enter__(self):
            return self

        def __exit__(self, *args):
            return None

        def send_message(self, message):
            sent.append(message)

    monkeypatch.setattr(
        tracking_mail, "get_settings", lambda: SimpleNamespace(mailpit_host="127.0.0.1", mailpit_port=1025)
    )
    monkeypatch.setattr(tracking_mail.smtplib, "SMTP", FakeSMTP)
    message = EmailMessage()
    message["To"] = "guest@example.com"
    message.set_content("Private local tracking receipt")
    tracking_mail._send(message)
    assert sent == [message]


async def test_client_reply_does_not_bypass_child_hitl(monkeypatch) -> None:
    import datetime as dt
    from contextlib import asynccontextmanager
    from types import SimpleNamespace
    from unittest.mock import AsyncMock

    from app.agent import runner

    service = runner.AgentService(object(), object(), concurrency=1)
    wake = AsyncMock()
    child = AsyncMock(return_value=("awaiting_human",))
    connection = SimpleNamespace(execute=AsyncMock(return_value=SimpleNamespace(fetchone=child)))

    @asynccontextmanager
    async def connected():
        yield connection

    async def connect():
        return connected()

    process = AsyncMock()
    monkeypatch.setattr(service, "_process", process)
    monkeypatch.setattr(service, "_conn", connect)
    monkeypatch.setattr(runner, "wake_followups_for_client_reply", wake)
    await service.submit_client_reply(1, 2, dt.datetime.now(dt.UTC))
    process.assert_awaited_once()
    wake.assert_not_awaited()


async def test_reply_recovery_requeues_persisted_reply_after_lost_notify(monkeypatch) -> None:
    import asyncio
    import datetime as dt
    from contextlib import asynccontextmanager
    from types import SimpleNamespace
    from unittest.mock import AsyncMock, Mock

    from app.agent import runner

    stamp = dt.datetime(2026, 11, 1, tzinfo=dt.UTC)
    service = runner.AgentService(object(), object())
    connection = SimpleNamespace(
        execute=AsyncMock(return_value=SimpleNamespace(fetchall=AsyncMock(return_value=[(7, 9, stamp)])))
    )

    @asynccontextmanager
    async def connected():
        yield connection

    async def connect():
        return connected()

    async def stop_after_iteration(_seconds):
        raise asyncio.CancelledError

    submitted = Mock()
    monkeypatch.setattr(service, "_conn", connect)
    monkeypatch.setattr(service, "submit_client_reply", submitted)
    monkeypatch.setattr(runner.asyncio, "sleep", stop_after_iteration)
    try:
        await service._reply_loop()
    except asyncio.CancelledError:
        pass
    submitted.assert_called_once_with(7, 9, stamp)


async def test_receipt_failure_is_recorded_without_persisting_access_token(monkeypatch) -> None:
    import datetime as dt
    import smtplib
    from types import SimpleNamespace
    from unittest.mock import AsyncMock, Mock

    from app import tracking_mail

    conn = SimpleNamespace(execute=AsyncMock(return_value=SimpleNamespace(fetchone=AsyncMock(return_value=(12,)))))
    monkeypatch.setattr(tracking_mail, "get_settings", lambda: SimpleNamespace(mailpit_enabled=True))
    monkeypatch.setattr(tracking_mail, "_send", Mock(side_effect=smtplib.SMTPException("offline")))
    await tracking_mail.send_tracking_receipt(
        conn,
        signal_id=1,
        run_id=2,
        recipient="guest@example.com",
        public_id="SIG-1",
        url="http://localhost/track/private-capability",
        sim_time=dt.datetime(2026, 11, 1, tzinfo=dt.UTC),
        lang="en",
    )
    assert all("private-capability" not in str(call) for call in conn.execute.call_args_list)
    updates = [call for call in conn.execute.call_args_list if call.args[0].startswith("update notifications")]
    assert len(updates) == 1 and updates[0].args[1][0] == "failed" and updates[0].args[1][1] is None


async def test_receipt_disabled_never_opens_smtp_or_creates_notification(monkeypatch) -> None:
    import datetime as dt
    from types import SimpleNamespace
    from unittest.mock import AsyncMock, Mock

    from app import tracking_mail

    conn = SimpleNamespace(execute=AsyncMock())
    send = Mock()
    monkeypatch.setattr(tracking_mail, "get_settings", lambda: SimpleNamespace(mailpit_enabled=False))
    monkeypatch.setattr(tracking_mail, "_send", send)
    await tracking_mail.send_tracking_receipt(
        conn,
        signal_id=1,
        run_id=2,
        recipient="guest@example.com",
        public_id="SIG-1",
        url="http://localhost/track/private-capability",
        sim_time=dt.datetime(2026, 11, 1, tzinfo=dt.UTC),
        lang="ru",
    )
    send.assert_not_called()
    conn.execute.assert_not_awaited()


def test_unhandled_tracking_error_never_logs_or_echoes_capability() -> None:
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    from structlog.testing import capture_logs

    from app.errors import install_error_handlers
    from app.observability.http import RequestLogMiddleware

    app = FastAPI()
    install_error_handlers(app)
    app.add_middleware(RequestLogMiddleware)
    token = "private_capability_123456789012345"

    @app.get("/api/public/track/{token}")
    async def broken(token: str):
        raise RuntimeError("lookup failed for " + token)

    with capture_logs() as logs, TestClient(app, raise_server_exceptions=False) as client:
        response = client.get("/api/public/track/" + token)
    assert response.status_code == 500
    assert response.json()["instance"] == "/api/public/track/{token}"
    assert token not in response.text and token not in str(logs)
    assert response.headers["cache-control"] == "no-store"
    assert response.headers["referrer-policy"] == "no-referrer"


async def test_listener_dispatches_appended_event_to_reply_pipeline(monkeypatch) -> None:
    import asyncio
    import datetime as dt
    import json
    from types import SimpleNamespace
    from unittest.mock import AsyncMock, Mock

    from app.agent import runner

    service = runner.AgentService(object(), object())
    stamp = dt.datetime(2026, 11, 1, tzinfo=dt.UTC)

    async def notifies():
        yield SimpleNamespace(
            channel="sim_events",
            payload=json.dumps(
                {
                    "event_type": "signal.appended",
                    "sim_time": stamp.isoformat(),
                    "payload": {"signal_id": 9, "parent_signal_id": 7},
                }
            ),
        )
        raise asyncio.CancelledError

    conn = SimpleNamespace(execute=AsyncMock(), notifies=notifies)
    submitted = Mock()
    monkeypatch.setattr(service, "_recover", AsyncMock())
    monkeypatch.setattr(service, "submit_client_reply", submitted)
    monkeypatch.setattr(runner.psycopg.AsyncConnection, "connect", AsyncMock(return_value=conn))
    try:
        await service._loop()
    except asyncio.CancelledError:
        pass
    submitted.assert_called_once_with(7, 9, stamp)


async def test_reply_worker_starts_and_stops_with_service(monkeypatch) -> None:
    import asyncio
    from unittest.mock import AsyncMock

    from app.agent import operator_feedback, runner

    service = runner.AgentService(object(), object())
    pending = asyncio.Event()

    async def wait(*_args):
        await pending.wait()

    for name in ("_loop", "_personal_loop", "_reply_loop"):
        monkeypatch.setattr(service, name, AsyncMock(side_effect=wait))
    monkeypatch.setattr(operator_feedback, "worker", AsyncMock(side_effect=wait))
    service.start()
    await asyncio.sleep(0)
    reply = service._reply_task
    assert reply is not None and not reply.done()
    await service.stop()
    assert reply.cancelled() and service._reply_task is None
