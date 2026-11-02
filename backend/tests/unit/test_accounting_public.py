"""Synthetic-only public metadata and operator CLI boundaries."""

import datetime as dt
import json

import pytest

from app.llm import accounting, accounting_cli
from app.llm.base import ProviderError

DAY = dt.date(2026, 11, 2)


def test_unknown_legacy_hint_is_not_remaining_or_observed_floor():
    result = accounting.public_observation(
        {"tokens_used": 17, "tokens_limit": 20, "requests_today": 4, "rpd_limit": 10}, None, DAY
    )
    assert result["tokens_used"] == 17 and result["observed_tokens_floor"] == 0
    assert result["usage_source"] == "legacy_unverified" and not result["usage_known"]
    assert result["requests_today"] == 4 and not result["requests_known"]
    assert result["tokens_remaining"] is None and result["requests_remaining"] is None


@pytest.mark.parametrize("pending", [False, True])
def test_reconciled_floor_overrides_hint_and_pending_never_looks_fully_known(pending):
    result = accounting.public_observation(
        {"tokens_used": 17, "tokens_limit": 20, "rpd_limit": 10},
        {
            "confirmed_tokens": 5,
            "reconciled": True,
            "usage_known": True,
            "usage_source": "operator_declared_app_usage",
            "daily_requests": 2,
            "daily_known": True,
            "pending": pending,
        },
        DAY,
    )
    assert result["tokens_used"] == result["observed_tokens_floor"] == 5
    assert result["usage_known"] is (not pending)
    assert result["tokens_remaining"] == (None if pending else 15)
    assert result["requests_today"] == 2 and result["requests_remaining"] == 8


def test_previous_day_registration_rolls_daily_counter_without_certifying_token_origin():
    result = accounting.public_observation(
        {"tokens_used": 17, "tokens_limit": 20, "rpd_limit": 10},
        {"created_at": dt.datetime(2026, 11, 1, tzinfo=dt.UTC)},
        DAY,
    )
    assert result["requests_today"] == 0 and result["requests_known"]
    assert not result["usage_known"] and result["tokens_remaining"] is None
    assert result["requests_remaining"] == 10


def test_unlimited_known_usage_has_nullable_remaining_without_fabricated_zero():
    result = accounting.public_observation(
        {}, {"reconciled": True, "usage_known": True, "daily_known": True, "daily_requests": 0}, DAY
    )
    assert result["usage_known"] and result["tokens_remaining"] is None and result["requests_remaining"] is None


def test_cli_parser_never_echoes_rejected_argument(capsys):
    secret = "synthetic-invalid-argument-key"
    with pytest.raises(SystemExit) as stopped:
        accounting_cli.parser().parse_args(["status", "--profile-id", secret, "--key-id", "1"])
    assert stopped.value.code == 2
    assert secret not in capsys.readouterr().err


async def test_incomplete_reconciliation_is_rejected_before_config_read(monkeypatch):
    async def bomb(_args):
        pytest.fail("missing explicit observations must not read/decrypt/migrate configuration")

    monkeypatch.setattr(accounting_cli, "selection", bomb)
    args = accounting_cli.parser().parse_args(["reconcile", "--profile-id", "1", "--key-id", "1"])
    with pytest.raises(ProviderError, match="всех observation"):
        await accounting_cli.execute(args)


def test_cli_failure_does_not_echo_exception_or_credentials(monkeypatch, capsys):
    secret = "synthetic-error-credential"

    async def rejected(args):
        raise ProviderError("auth", secret)

    monkeypatch.setattr(accounting_cli, "execute", rejected)
    monkeypatch.setattr("sys.argv", ["accounting_cli", "status", "--profile-id", "1", "--key-id", "1"])
    assert accounting_cli.main() == 2
    captured = capsys.readouterr()
    assert secret not in captured.out + captured.err
    assert json.loads(captured.out) == {"ok": False, "error": "auth"}
