"""Настоящий локальный SMTP sink: квитанция после вопроса, без внешней почты."""

from __future__ import annotations

import datetime as dt
import json
import socketserver
import threading
import urllib.request
from email import policy
from email.parser import BytesParser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import httpx
import psycopg
import pytest

from app.config import get_settings
from app.ingest.normalizer import create_signal, from_api_signal
from app.tracking_mail import send_tracking_receipt
from tests.helpers import dsn, new_run, sim_now


@pytest.fixture
def local_mail_sink(monkeypatch):
    """SMTP доставляет только в память, HTTP читает MIME; внешнего relay нет."""
    messages = []

    class SMTP(socketserver.StreamRequestHandler):
        def handle(self):
            self.wfile.write(b"220 localhost test sink\r\n")
            while line := self.rfile.readline(65537):
                command = line.upper()
                if command.startswith((b"EHLO ", b"HELO ")):
                    self.wfile.write(b"250 localhost\r\n")
                elif command.startswith((b"MAIL FROM:", b"RSET", b"NOOP")):
                    self.wfile.write(b"250 OK\r\n")
                elif command.startswith(b"RCPT TO:"):
                    self.wfile.write(b"250 OK\r\n" if b"<GUEST@EXAMPLE.COM>" in command else b"550 unknown\r\n")
                elif command.strip() == b"DATA":
                    self.wfile.write(b"354 End with dot\r\n")
                    chunks = []
                    while (chunk := self.rfile.readline(65537)) not in (b".\r\n", b""):
                        chunks.append(chunk[1:] if chunk.startswith(b"..") else chunk)
                        assert sum(map(len, chunks)) <= 65536
                    message = BytesParser(policy=policy.default).parsebytes(b"".join(chunks))
                    messages.append(
                        {
                            "to": str(message["To"]),
                            "from": str(message["From"]),
                            "subject": str(message["Subject"]),
                            "body": message.get_content(),
                        }
                    )
                    self.wfile.write(b"250 queued locally\r\n")
                elif command.strip() == b"QUIT":
                    self.wfile.write(b"221 bye\r\n")
                    return
                else:
                    self.wfile.write(b"500 unsupported\r\n")

    class HTTP(BaseHTTPRequestHandler):
        def do_GET(self):
            body = json.dumps(messages).encode()
            self.send_response(200 if self.path == "/messages" else 404)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, *_args):
            pass

    with (
        socketserver.ThreadingTCPServer(("127.0.0.1", 0), SMTP) as smtp,
        ThreadingHTTPServer(("127.0.0.1", 0), HTTP) as web,
    ):
        threads = [threading.Thread(target=server.serve_forever, daemon=True) for server in (smtp, web)]
        for thread in threads:
            thread.start()
        settings = get_settings()
        monkeypatch.setattr(settings, "mailpit_enabled", True)
        monkeypatch.setattr(settings, "mailpit_host", "127.0.0.1")
        monkeypatch.setattr(settings, "mailpit_port", smtp.server_address[1])
        try:
            yield f"http://127.0.0.1:{web.server_address[1]}/messages"
        finally:
            smtp.shutdown()
            web.shutdown()
            for thread in threads:
                thread.join(timeout=3)


def received(base):
    with urllib.request.urlopen(base, timeout=3) as response:
        return json.load(response)


async def test_real_smtp_receipt_in_older_transaction_cannot_predate_question(seeded, local_mail_sink):
    async with await psycopg.AsyncConnection.connect(dsn(seeded)) as setup:
        run = await new_run(setup, "SMTP chronology")
        at = await sim_now(setup)
    async with await psycopg.AsyncConnection.connect(dsn(seeded)) as older:
        started = (await (await older.execute("select now()")).fetchone())[0]
        async with await psycopg.AsyncConnection.connect(dsn(seeded)) as incoming:
            result = await create_signal(
                incoming,
                from_api_signal(
                    {"channel_code": "landing", "client_id": 1, "text": "Синтетическая проверка почтовой квитанции."}
                ),
                source_code="api",
                run_id=run,
                sim_time=at,
            )
            assert result["status"] == "accepted"
            question = (
                await (
                    await incoming.execute("select received_at from signals where id=%s", (result["signal_id"],))
                ).fetchone()
            )[0]
            await incoming.commit()
        assert question > started
        url = "http://localhost/track/public-test-smtp-capability"
        await send_tracking_receipt(
            older,
            signal_id=result["signal_id"],
            run_id=run,
            recipient="guest@example.com",
            public_id=result["public_id"],
            url=url,
            sim_time=at,
            lang="ru",
        )
        status, sent_at, sent_sim, body = await (
            await older.execute(
                "select status,sent_at,sent_sim,body from notifications where signal_id=%s and template_code='tracking_link'",
                (result["signal_id"],),
            )
        ).fetchone()
        wire = received(local_mail_sink)
        assert len(wire) == 1
        assert wire[0]["to"] == "guest@example.com" and wire[0]["from"] == "noreply@example.com"
        assert result["public_id"] in wire[0]["subject"] and url in wire[0]["body"]
        assert "public-test-smtp-capability" not in body
        assert status == "sent" and sent_sim == at
        assert sent_at >= question
        assert sent_at <= dt.datetime.now(dt.UTC)


async def test_public_claim_receipt_uses_real_smtp_and_track_reads_do_not_resend(seeded, local_mail_sink):
    from app.api.public import _claim_hits
    from app.main import create_app

    _claim_hits.clear()
    try:
        async with await psycopg.AsyncConnection.connect(dsn(seeded)) as conn:
            city, region = await (
                await conn.execute("select id,region_code from cities order by id limit 1")
            ).fetchone()
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(create_app()), base_url="http://localhost"
        ) as client:
            captcha = (await client.get("/api/public/captcha")).json()
            left, right = captcha["question"].split("=", 1)[0].split("+")
            body = {
                "contact": {"email": "guest@example.com", "region_code": region, "city_id": city},
                "text": "Отказали в кредитной карте без объяснений. Почему?",
                "consent": True,
                "captcha": {"id": captcha["id"], "answer": int(left) + int(right)},
            }
            response = await client.post("/api/public/claim", json=body)
            assert response.status_code == 201
            accepted = response.json()
            wire = received(local_mail_sink)
            assert len(wire) == 1 and wire[0]["to"] == "guest@example.com"
            assert accepted["track_url"] in wire[0]["body"]
            assert accepted["public_id"] in wire[0]["subject"]
            track = "/api/public/track/" + accepted["tracking_token"]
            assert (await client.get(track)).status_code == 200
            assert (await client.get(track)).status_code == 200
            assert (await client.post("/api/public/claim", json=body)).status_code == 422
            assert len(received(local_mail_sink)) == 1
        async with await psycopg.AsyncConnection.connect(dsn(seeded)) as conn:
            row = await (
                await conn.execute(
                    "select n.status,n.sent_at>=s.received_at,n.body from notifications n join signals s on s.id=n.signal_id and s.run_id=n.run_id where s.public_id=%s and n.template_code='tracking_link'",
                    (accepted["public_id"],),
                )
            ).fetchone()
            assert row[0] == "sent" and row[1] is True
            assert accepted["tracking_token"] not in row[2]
    finally:
        _claim_hits.clear()


async def test_actual_smtp_recipient_rejection_is_failed_without_sent_timestamp(seeded, local_mail_sink):
    async with await psycopg.AsyncConnection.connect(dsn(seeded)) as conn:
        run = await new_run(conn, "SMTP definite rejection")
        at = await sim_now(conn)
        incoming = await create_signal(
            conn,
            from_api_signal(
                {"channel_code": "landing", "client_id": 1, "text": "Синтетическая проверка отказа локальной почты."}
            ),
            source_code="api",
            run_id=run,
            sim_time=at,
        )
        assert incoming["status"] == "accepted"
        await send_tracking_receipt(
            conn,
            signal_id=incoming["signal_id"],
            run_id=run,
            recipient="rejected@example.com",
            public_id=incoming["public_id"],
            url="http://localhost/track/public-test-rejected-mail",
            sim_time=at,
            lang="en",
        )
        status, sent_at, sent_sim, body = await (
            await conn.execute(
                "select status,sent_at,sent_sim,body from notifications where signal_id=%s and template_code='tracking_link'",
                (incoming["signal_id"],),
            )
        ).fetchone()
        assert status == "failed" and sent_at is None and sent_sim is None
        assert "public-test-rejected-mail" not in body
        assert received(local_mail_sink) == []
