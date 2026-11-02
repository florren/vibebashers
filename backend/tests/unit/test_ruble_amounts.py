"""T-059 regression: полная сумма вместо хвоста копеек, без изменения money policy."""

import datetime as dt
from decimal import Decimal
from unittest.mock import AsyncMock

import pytest

from app.agent.nodes import Deps, normalize, regex_hints
from app.agent.state import new_state
from app.agent.tools.base import ToolContext
from app.amounts import first_ruble_amount, ruble_amount_hint
from app.contracts.registry import validate
from app.llm.base import LLMProfile
from app.llm.failover import ProviderChain
from app.llm.mock import MockProvider, analyze

VALID = [
    ("Верните 0 ₽", "0"),
    ("Верните 1 руб", "1"),
    ("Верните 9 рублей", "9"),
    ("Верните 450 руб.", "450"),
    ("Оплата 3 200 рублей", "3200"),
    ("Оплата 5472.45 рублей", "5472.45"),
    ("Оплата 5472,45 рубля", "5472.45"),
    ("Комиссия 0.05 руб", "0.05"),
    ("Комиссия 0,50 ₽", "0.50"),
    ("Комиссия 0,5 рубль", "0.5"),
    ("Оплата 5 472.45 ₽", "5472.45"),
    ("Оплата 5\u00a0472,45 руб", "5472.45"),
    ("Оплата 5\u202f472.45 руб", "5472.45"),
    ("Оплата 5\u2009472,45 руб", "5472.45"),
    ("Оплата 12 345 678,90 р.", "12345678.90"),
    ("Списали123.45руб.", "123.45"),
    ("комиссию54.72руб", "54.72"),
    ("Комиссия54,72РУБЛЕЙ", "54.72"),
    ("Верните комиссию,54.72руб", "54.72"),
    ("Верните комиссию, 54.72руб", "54.72"),
    ("Оплата 999999999999.99 руб", "999999999999.99"),
    ("Оплатил по QR 5472.45 рублей, списали комиссию54.72руб", "5472.45"),
    ("Верните комиссию54.72руб за оплату 5472.45 рублей", "54.72"),
    ("В 2026 году списали 54.72 руб", "54.72"),
]
INVALID = [
    "Списали 123.456 руб",
    "Списали 123..45 руб",
    "Списали 1,234.56 руб",
    "Списали 1.234,56 руб",
    "Списали 12 34 руб",
    "Списали 1 2345.67 руб",
    "Списали 1 23 456 руб",
    "Списали 54, 72 руб",
    "Баланс -450 руб",
    "Баланс - 450 руб",
    "Баланс −450 руб",
    "Дата 12.03.2026 руб",
    "Списали .45 руб",
    "Итого:.45руб",
    "Итого:,45руб",
    "Списали ,45 руб",
    "Списали 100 долларов",
    "Цена 450 рублика",
    "Списали 99 евро",
    "Никакой суммы нет",
]


@pytest.mark.parametrize("text,expected", VALID)
def test_complete_ruble_amount_is_exact_decimal_and_same_hint_in_both_paths(text, expected):
    assert first_ruble_amount(text) == Decimal(expected)
    assert ruble_amount_hint(text) == float(expected)
    assert regex_hints(text)["amount_rub"] == float(expected)
    assert analyze(text)["amount_rub"] == float(expected)


@pytest.mark.parametrize("text", INVALID)
def test_invalid_amount_never_yields_integer_or_fraction_tail(text):
    assert first_ruble_amount(text) is None
    assert ruble_amount_hint(text) is None
    assert "amount_rub" not in regex_hints(text)
    assert analyze(text)["amount_rub"] is None


def test_exact_parser_does_not_round_large_decimal_and_hint_stays_json_finite():
    amount = "12345678901234567890.01"
    assert first_ruble_amount(amount + " руб") == Decimal(amount)
    assert ruble_amount_hint("9" * 400 + " руб") is None


@pytest.mark.parametrize("text,expected", [VALID[5], VALID[6], VALID[11], VALID[21]])
async def test_mock_normalization_cannot_overwrite_correct_regex_hint_with_fraction_tail(text, expected):
    conn = AsyncMock()
    profile = LLMProfile(code="mock", provider="mock", model="mock-rules-v1")
    deps = Deps(
        ToolContext(conn, run_id=1, agent_run_id=2, sim_time=dt.datetime(2026, 11, 1, tzinfo=dt.UTC)),
        ProviderChain([MockProvider()]),
        profile,
    )
    state = new_state(1, {"id": 3, "channel": "chat", "text": text}, 2, "v1")
    result = await normalize(state, deps)
    assert result["errors"] == []
    assert result["normalization"]["entities"]["amount_rub"] == float(expected)
    assert validate(result["normalization"], "agent/normalization") == []
