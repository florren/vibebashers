"""Только synthetic secrets: проверка общей границы до всех diagnostic sinks."""

import copy
import io
import json
import logging
from contextlib import redirect_stderr

import pytest
import structlog

from app.logging import PublicTokenFilter, configure_logging, get_logger
from app.observability.http import HttpStats, safe_public_path
from app.observability.redaction import REDACTED, redact, redact_event, redact_text

AUTH = "synthetic-auth-only-for-unit"
API = "synthetic-api-only-for-unit"
BASIC = "c3ludGhldGljLWJhc2ljLW9ubHktZm9yLXVuaXQ="


@pytest.fixture(autouse=True)
def restore_log_configuration():
    original = structlog.get_config().copy()
    yield
    structlog.configure(**original)


@pytest.mark.parametrize(
    "key",
    [
        "Authorization",
        "AUTHORIZATION",
        "proxy-authorization",
        "api_key",
        "API-KEY",
        "apiKey",
        "X-API-Key",
        "access_token",
        "refresh_token",
        "client_secret",
        "password",
        "key_enc",
        "encrypted_key",
        "OPENROUTER_API_KEY",
        "GIGACHAT_AUTH_KEY_1",
        "app_secret",
        "tracking_token",
    ],
)
def test_named_credentials_are_redacted_case_insensitively(key):
    original = {key: API}
    assert redact(original) == {key: REDACTED}
    assert original[key] == API


def test_nested_redaction_is_nonmutating_idempotent_and_preserves_identifiers():
    original = {
        "headers": {"Authorization": f"Bearer {AUTH}"},
        "items": [{"api_key": API}, ({"access_token": AUTH},)],
        "key_hint": "…1234",
        "key_label": "provider_env_1",
        "key": "bank.name",
        "request_id": "request-123",
        "operation_id": 123,
        "prompt_tokens": 100,
        "completion_tokens": 20,
        "token_count": 120,
        "has_secret": True,
        "error": None,
    }
    before = copy.deepcopy(original)
    result = redact_event(None, "info", original)
    assert original == before
    assert result == redact(result)
    assert AUTH not in json.dumps(result) and API not in json.dumps(result)
    for key in (
        "key_hint",
        "key_label",
        "key",
        "request_id",
        "operation_id",
        "prompt_tokens",
        "completion_tokens",
        "token_count",
        "has_secret",
        "error",
    ):
        assert result[key] == original[key]


@pytest.mark.parametrize(
    "text",
    [
        f"Authorization: Bearer {AUTH}",
        f"authorization=Basic {BASIC}",
        f'{{"api_key": "{API}"}}',
        f"{{'api_key': '{API}'}}",
        f'{{"api_key":"{API}',  # HTTP detail[:200] может оборвать JSON внутри value.
        f'{{\\"api_key\\":\\"{API}\\"}}',
        f"RuntimeError: Bearer {AUTH}",
        f"https://example.invalid/test?api_key={API}&model=synthetic",
        f"exception: API-KEY={API}; status=401",
    ],
)
def test_labeled_strings_and_auth_schemes_are_redacted(text):
    result = redact_text(text)
    assert all(value not in result for value in (AUTH, API, BASIC))
    assert REDACTED in result and redact_text(result) == result


def test_quoted_credentials_with_escaped_quotes_and_truncation_are_fully_redacted():
    value = 'synthetic-"quoted"-secret'
    for text in (json.dumps({"api_key": value}), json.dumps({"api_key": value})[:-2]):
        result = redact_text(text)
        assert "synthetic" not in result and "quoted" not in result
        assert redact_text(result) == result


def test_already_redacted_value_does_not_accumulate_markers():
    result = redact_text("Authorization: Bearer [REDACTED]")
    assert result.count(REDACTED) == 1 and redact_text(result) == result


def test_nonsecret_labels_counts_and_business_text_are_not_redacted():
    text = "key_hint=1234 key_label=provider_1 key=bank.name token_count=10 access_token_count=2 Authorization denied"
    assert redact_text(text) == text
    assert redact({"request_id": "id-123", "customer_id": 123, "is_active": True}) == {
        "request_id": "id-123",
        "customer_id": 123,
        "is_active": True,
    }


@pytest.mark.parametrize("env", ["dev", "prod"])
def test_console_jsonl_and_formatted_exception_share_redacted_event(tmp_path, env):
    path = tmp_path / "app.jsonl"
    console = io.StringIO()
    original = {"headers": {"Authorization": f"Bearer {AUTH}"}, "api_key": API}
    with redirect_stderr(console):
        configure_logging(env, path)
        logger = get_logger("synthetic_secret_boundary")
        logger.warning("synthetic", payload=original, key_label="provider_1", prompt_tokens=7)
        try:
            raise ValueError(f"Authorization: Basic {BASIC}; api_key={API}")
        except ValueError:
            logger.exception("synthetic_exception")
    outputs = console.getvalue(), path.read_text()
    assert all(secret not in output for secret in (AUTH, API, BASIC) for output in outputs)
    assert all(REDACTED in output for output in outputs)
    records = [json.loads(line) for line in path.read_text().splitlines()]
    assert records[0]["key_label"] == "provider_1" and records[0]["prompt_tokens"] == 7
    assert "ValueError" in records[1]["exception"]
    assert original["headers"]["Authorization"] == f"Bearer {AUTH}" and original["api_key"] == API


def test_http_error_is_redacted_before_ring_buffer_and_snapshot():
    stats = HttpStats()
    stats.record(
        "GET",
        "/synthetic",
        500,
        1,
        path="/synthetic",
        request_id="request-1",
        error=f"ValueError: Authorization: Bearer {AUTH}; api_key={API}",
    )
    stored = json.dumps(list(stats.errors))
    snapshot = json.dumps(stats.snapshot())
    assert AUTH not in stored + snapshot and API not in stored + snapshot
    assert stats.snapshot()["recent_errors"][0]["request_id"] == "request-1"
    assert REDACTED in stored and REDACTED in snapshot


def test_unknown_tracking_route_is_redacted_before_counter_keys_and_all_sinks(tmp_path, monkeypatch):
    from fastapi import FastAPI
    from fastapi.testclient import TestClient

    from app.observability import http as obs

    token = "synthetic-unknown-route-capability"
    stats = HttpStats()
    monkeypatch.setattr(obs, "stats", stats)
    console = io.StringIO()
    path = tmp_path / "http.jsonl"
    app = FastAPI()
    app.add_middleware(obs.RequestLogMiddleware)
    with redirect_stderr(console):
        configure_logging("prod", path)
        monkeypatch.setattr(obs, "log", get_logger("synthetic_unknown_tracking_route"))
        with TestClient(app) as client:
            assert client.get(f"/api/public/track/{token}/unregistered").status_code == 404
    assert token not in console.getvalue() + path.read_text()
    assert token not in json.dumps(stats.snapshot()) + str(list(stats.by_route_status)) + str(list(stats.errors))
    assert stats.snapshot()["routes"][0]["route"] == "/api/public/track/{token}"


def test_embedded_tracking_url_uses_same_existing_filter_without_changing_other_routes():
    token = "synthetic-embedded-capability"
    value = f"Cannot GET https://example.invalid/track/{token}?private=1"
    assert token not in redact_text(value)
    assert redact_text(redact_text(value)) == redact_text(value)
    plain = "/api/incidents/123, request_id=abcdef, client_id=123"
    assert redact_text(plain) == plain


def test_public_tracking_path_filter_and_capability_protection_are_preserved():
    token = "synthetic-tracking-capability-for-unit"
    path = f"/api/public/track/{token}?extra=synthetic"
    record = logging.LogRecord(
        "uvicorn.access", logging.INFO, "", 0, "%s %s %s %s %s", ("127.0.0.1", "GET", path, "HTTP/1.1", 404), None
    )
    assert PublicTokenFilter().filter(record)
    assert token not in record.getMessage()
    assert safe_public_path(path) == "/api/public/track/{token}"
    assert redact({"tracking_token": token}) == {"tracking_token": REDACTED}


def test_repeated_logging_configuration_keeps_one_existing_public_filter():
    with redirect_stderr(io.StringIO()):
        configure_logging("prod")
        configure_logging("prod")
    filters = logging.getLogger("uvicorn.access").filters
    assert sum(isinstance(item, PublicTokenFilter) for item in filters) == 1
