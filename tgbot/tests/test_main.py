from __future__ import annotations

import logging
import subprocess
import sys
import traceback

import pytest

from cx_tgbot.main import Configuration, InvalidConfiguration, SDKRecordFilter

TOKEN = "123456:" + "A" * 35
SECRET = "public-test-vector-only-000000000000"


def env(**overrides):
    return {"TELEGRAM_BOT_TOKEN": TOKEN, "TGBOT_INTERNAL_SECRET": SECRET, **overrides}


def test_config_secrets_not_in_repr_and_default_origin():
    config = Configuration.from_environment(env())
    assert TOKEN not in repr(config) and SECRET not in repr(config)
    assert config.backend_url == "http://backend:8000"


@pytest.mark.parametrize(
    "override",
    [
        {"TELEGRAM_BOT_TOKEN": "private-invalid-token"},
        {"TGBOT_INTERNAL_SECRET": "short"},
        {"TGBOT_BACKEND_URL": "https://user:private@example.invalid"},
        {"TGBOT_BACKEND_URL": "file:///private"},
        {"TGBOT_BACKEND_URL": "https://example.invalid/prefix"},
        {"TGBOT_BACKEND_URL": "https://example.invalid?private"},
        {"TGBOT_BACKEND_URL": "https://example.invalid:999999"},
    ],
)
def test_invalid_config_never_echoes_values(override):
    with pytest.raises(InvalidConfiguration) as exc:
        Configuration.from_environment(env(**override))
    rendered = "".join(traceback.format_exception(exc.value))
    assert "private" not in rendered and TOKEN not in rendered and SECRET not in rendered


@pytest.mark.parametrize("namespace", ["aiogram.event", "aiohttp.client", "httpx", "httpcore.connection"])
def test_sdk_log_echo_and_traceback_are_removed(namespace):
    try:
        raise ValueError(TOKEN)
    except ValueError:
        record = logging.LogRecord(namespace, logging.ERROR, __file__, 1, "response=%s", (SECRET,), sys.exc_info())
    assert SDKRecordFilter().filter(record)
    assert record.getMessage() == "telegram_transport_sdk_event"
    assert record.exc_info is None and record.exc_text is None and record.stack_info is None


def test_offline_entrypoint_needs_no_configuration_or_network():
    result = subprocess.run(
        [sys.executable, "-m", "cx_tgbot.main", "--offline"], env={}, capture_output=True, text=True
    )
    assert result.returncode == 0
    assert "telegram_transport_offline" in result.stderr


def test_missing_configuration_fails_closed_without_traceback():
    result = subprocess.run([sys.executable, "-m", "cx_tgbot.main"], env={}, capture_output=True, text=True)
    assert result.returncode == 2
    assert "telegram_token_missing_or_invalid" in result.stderr
    assert "Traceback" not in result.stderr
