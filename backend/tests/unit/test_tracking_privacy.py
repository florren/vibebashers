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
