"""Installer config проверяется только на tmp .env, не на рабочем файле пользователя."""

from __future__ import annotations

import importlib.util
import subprocess
import sys
from pathlib import Path

import pytest

from app.config import Settings
from app.tgbot.configuration import configured

ROOT = Path(__file__).resolve().parents[3]
spec = importlib.util.spec_from_file_location("tgbot_env", ROOT / "scripts/tgbot_env.py")
helper = importlib.util.module_from_spec(spec)
spec.loader.exec_module(helper)
TOKEN = "123456:" + "A" * 35


def file(tmp_path, **overrides):
    env = {
        "APP_SECRET": "public-test-storage-vector-000000000000",
        "TELEGRAM_BOT_TOKEN": TOKEN,
        "TGBOT_PUBLIC_BASE_URL": "https://bank.invalid",
        "TGBOT_ENABLED": "false",
        **overrides,
    }
    path = tmp_path / ".env"
    path.write_text(
        "# preserve fixture comment\n"
        + "\n".join(f"{key}={value}" for key, value in env.items())
        + "\nUNRELATED=leave-me\n"
    )
    return path


def test_enable_generates_service_secret_once_and_matches_actual_backend_settings(tmp_path):
    path = file(tmp_path)
    helper.prepare(path, enable=True)
    env = helper.values(path.read_text())
    assert len(env["TGBOT_INTERNAL_SECRET"].encode()) >= 32
    assert env["TELEGRAM_BOT_TOKEN"] == TOKEN and env["UNRELATED"] == "leave-me"
    assert "# preserve fixture comment" in path.read_text()
    settings = Settings(_env_file=path)
    transport = configured(settings)
    assert transport is not None and transport.bot_id == 123456
    assert transport.secret.decode() == env["TGBOT_INTERNAL_SECRET"]
    before = path.read_bytes()
    helper.prepare(path, enable=True)
    assert path.read_bytes() == before
    assert path.stat().st_mode & 0o777 == 0o600


def test_disable_preserves_secrets_and_removes_ambiguous_duplicate_enable(tmp_path):
    path = file(tmp_path, TGBOT_INTERNAL_SECRET="public-test-transport-vector-000000000000")
    path.write_text(path.read_text() + "TGBOT_ENABLED=true\n")
    helper.prepare(path, enable=False)
    env = helper.values(path.read_text())
    assert env["TGBOT_ENABLED"] == "false"
    assert env["TELEGRAM_BOT_TOKEN"] == TOKEN
    assert env["TGBOT_INTERNAL_SECRET"] == "public-test-transport-vector-000000000000"
    assert path.read_text().count("TGBOT_ENABLED=") == 1
    assert configured(Settings(_env_file=path)) is None


@pytest.mark.parametrize(
    "override",
    [
        {"TELEGRAM_BOT_TOKEN": "bad-private-token"},
        {"TGBOT_PUBLIC_BASE_URL": "https://user:private@bank.invalid"},
        {"TGBOT_PUBLIC_BASE_URL": "https://bank.invalid/path"},
        {"TGBOT_INTERNAL_SECRET": "short"},
        {"APP_SECRET": "change-me"},
    ],
)
def test_invalid_enable_is_atomic_and_never_prints_credentials(tmp_path, override):
    path = file(tmp_path, **override)
    before = path.read_bytes()
    result = subprocess.run(
        [sys.executable, str(ROOT / "scripts/tgbot_env.py"), "--env-file", str(path), "--enable"],
        capture_output=True,
        text=True,
    )
    assert result.returncode == 2 and path.read_bytes() == before
    assert TOKEN not in result.stderr and "private" not in result.stderr and "Traceback" not in result.stderr


def test_symlink_config_is_not_replaced_or_followed(tmp_path):
    target = file(tmp_path)
    link = tmp_path / "link.env"
    link.symlink_to(target)
    before = target.read_bytes()
    with pytest.raises(ValueError, match="symlink"):
        helper.prepare(link, enable=False)
    assert link.is_symlink() and target.read_bytes() == before
