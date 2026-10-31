"""Служебная подсказка mock не должна заставлять live-модель продолжать assistant-префикс."""

import pytest

from app.demo.roles import respond
from app.llm.base import LLMProfile, ProviderError
from app.llm.failover import ProviderChain, provider_messages
from app.llm.mock import MOCK_HINT_END, MOCK_HINT_START
from app.llm.ratelimit import RateLimiter


@pytest.mark.parametrize("provider", ["gigachat", "openai_compatible"])
async def test_demo_hint_hidden_from_live_preserved_for_mock(provider):
    seen = []

    class Unavailable:
        name = provider

        async def complete_structured(self, messages, schema, profile, *, timeout_s):
            seen.extend(messages)
            raise ProviderError("network", "offline")

    chain = ProviderChain([Unavailable()], rate_limiter=RateLimiter())
    result, meta = await respond(
        chain,
        LLMProfile(code="demo-hint", provider=provider, model="test"),
        {"role": "product_team", "outcome": "on_time", "language": "ru"},
        "Проверка завершена, результат подтверждён.",
    )
    assert len(seen) == 2
    assert all(MOCK_HINT_START not in message["content"] for message in seen)
    assert result["body"] == "Проверка завершена, результат подтверждён."
    assert meta["source"] == "mock" and meta["fallback"]


def test_user_text_and_real_assistant_history_are_not_stripped():
    hint = MOCK_HINT_START + "{}" + MOCK_HINT_END
    messages = [
        {"role": "user", "content": hint},
        {"role": "assistant", "content": "Предыдущий ответ."},
        {"role": "assistant", "content": hint},
    ]
    assert provider_messages(messages, "gigachat") == messages[:2]
    assert len(messages) == 3
    assert provider_messages(messages, "replay") is messages
    assert provider_messages(messages, "mock") is messages


@pytest.mark.parametrize("kind", ["rca", "fix_decision", "progress_report", "release_note", "verification_report"])
async def test_team_receives_only_current_stage_evidence(monkeypatch, kind):
    import datetime as dt

    from app.sim.rng import SimRng
    from app.sim.teams import PlannedStep, TeamEmulator

    seen = {}

    async def capture(chain, profile, context, fallback, decision="accept"):
        seen.update(context)
        return {"body": fallback}, {"source": "mock"}

    monkeypatch.setattr("app.demo.roles.respond", capture)
    emulator = TeamEmulator(
        SimRng(42),
        None,
        None,
        1,
        demo_outcome="on_time",
        llm=(None, None),
        demo_context={
            "observed": "Очередь",
            "action": "Открыть окно",
            "verification": "Клиент обслужен",
            "source": "synthetic_fixture",
        },
    )
    await emulator._artifact_body(None, kind, PlannedStep("rca", dt.datetime.now(dt.UTC)), {"title": "Очередь"})
    assert "verification" not in seen["evidence"]
    assert seen["verified"] == (kind == "verification_report")
    if kind != "verification_report":
        assert "Клиент обслужен" not in str(seen)
    if kind == "fix_decision":
        assert "ещё не выполнен" in seen["result"]
