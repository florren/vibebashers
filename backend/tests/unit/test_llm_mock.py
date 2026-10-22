"""Mock-провайдер: детерминирован, заполняет все контракты agent/*, эвристики ловят сарказм/отток/благодарность."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from app.contracts.registry import deref, validate
from app.llm.base import LLMProfile, Message
from app.llm.mock import MockProvider, analyze

ROOT = Path(__file__).resolve().parents[3]
AGENT_SCHEMAS = sorted(
    p.name.replace(".schema.json", "") for p in (ROOT / "contracts/events/agent").glob("*.schema.json")
)
TEXTS = [
    "Спасибо, что списали комиссию за QR-оплату 150 ₽, которой «нет» по тарифу)) Отличный сервис, ничего не скажешь.",
    "Приложение не работает третий день, СМС не приходят!!! Закрою счёт и уйду в другой банк, напишу в ЦБ.",
    "Спасибо большое оператору Марии, всё быстро решили!",
    "Подскажите, как открыть вклад на 6 месяцев?",
    "ну ок",
    "",
]
PROFILE = LLMProfile(code="mock", provider="mock", model="mock-rules-v1")


def msgs(text: str) -> list[Message]:
    return [{"role": "system", "content": "Ты — агент банка."}, {"role": "user", "content": text}]


@pytest.mark.parametrize("schema_name", AGENT_SCHEMAS)
@pytest.mark.parametrize("text", TEXTS, ids=[t[:12] or "empty" for t in TEXTS])
async def test_mock_fills_every_agent_contract(schema_name: str, text: str) -> None:
    obj, usage, raw = await MockProvider().complete_structured(
        msgs(text), deref(f"agent/{schema_name}"), PROFILE, timeout_s=1
    )
    assert validate(obj, f"agent/{schema_name}") == []
    assert usage.source == "mock" and json.loads(raw) == obj


async def test_mock_is_deterministic() -> None:
    m = MockProvider()
    a, *_ = await m.complete_structured(msgs(TEXTS[0]), deref("agent/classification"), PROFILE, timeout_s=1)
    b, *_ = await m.complete_structured(msgs(TEXTS[0]), deref("agent/classification"), PROFILE, timeout_s=1)
    assert a == b


def test_heuristics_sarcasm_churn_gratitude() -> None:
    sarcasm = analyze(TEXTS[0])
    assert (
        sarcasm["sarcasm"]
        and sarcasm["sentiment"] == "negative"
        and sarcasm["signal_type"] == "tariff_terms"
        and "sarcasm" in sarcasm["flags"]
    )
    churn = analyze(TEXTS[1])
    assert (
        "churn_threat" in churn["intents"] and "regulator_threat" in churn["intents"] and churn["criticality"] == "high"
    )
    assert analyze(TEXTS[2])["signal_type"] == "gratitude" and analyze(TEXTS[2])["sentiment"] == "positive"
    assert analyze(TEXTS[3])["signal_type"] == "info_request" and analyze(TEXTS[3])["intents"] == ["question"]


async def test_decision_for_angry_client_needs_human_and_creates_incident() -> None:
    obj, *_ = await MockProvider().complete_structured(msgs(TEXTS[1]), deref("agent/decision"), PROFILE, timeout_s=1)
    assert obj["incident_action"] == "create" and obj["needs_human"] is True and obj["criticality"] == "high"
    assert len(obj["human_options"]) >= 2 and obj["incident_type"] == "legal_regulatory"


async def test_mock_stream_yields_text() -> None:
    chunks = [c async for c in MockProvider().stream(msgs(TEXTS[1]), PROFILE, timeout_s=1)]
    assert len(chunks) > 3 and "".join(chunks).strip()
