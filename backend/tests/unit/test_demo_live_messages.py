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
    body = await emulator._artifact_body(None, kind, PlannedStep("rca", dt.datetime.now(dt.UTC)), {"title": "Очередь"})
    if kind == "verification_report":
        assert body == "Клиент обслужен"
        assert emulator.artifact_meta["content_source"] == "verified_facts"
        assert not seen
        return
    assert "verification" not in seen["evidence"]
    assert seen["verified"] == (kind == "verification_report")
    if kind != "verification_report":
        assert "Клиент обслужен" not in str(seen)
    if kind == "fix_decision":
        assert "ещё не выполнен" in seen["result"]


@pytest.mark.parametrize("accepted_after_retry", [False, True])
async def test_live_reply_is_checked_corrected_and_honestly_falls_back(accepted_after_retry):
    from app.llm.base import Usage
    from app.llm.failover import ChainResult

    class ReviewChain:
        def __init__(self):
            self.calls = []

        def profile_for(self, role, default):
            return default

        async def complete_structured(self, messages, schema, profile):
            self.calls.append(messages)
            n = len(self.calls)
            obj = (
                {
                    "supported": accepted_after_retry and n == 4,
                    "reason": "Разблокировка не подтверждена.",
                }
                if n in (2, 4)
                else {"decision": "accept", "body": "Ваша карта разблокирована."}
            )
            return ChainResult(
                obj,
                Usage(prompt_tokens=10, completion_tokens=5, provider="gigachat", model="test", source="live"),
                "",
                "gigachat",
            )

    chain = ReviewChain()
    body, meta = await respond(
        chain,
        LLMProfile(code="live", provider="gigachat", model="test"),
        {"role": "customer_reply", "outcome": "success", "facts": "Рассмотрение блокировки проверено."},
        "Рассмотрение блокировки проверено.",
    )
    assert len(chain.calls) == 4
    assert "Исправь текст" in chain.calls[2][-1]["content"]
    assert meta["usage"]["total_tokens"] == 60
    assert len(meta["grounding_reviews"]) == 2
    assert meta["grounded"] == accepted_after_retry
    assert meta["source"] == ("live" if accepted_after_retry else "mock")
    if not accepted_after_retry:
        assert body["body"] == "Рассмотрение блокировки проверено."
        assert meta["fallback"]
