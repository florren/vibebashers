"""T-048 policy review: платные вызовы требуют известный бюджет и подтверждённый расход."""

import json
from unittest.mock import AsyncMock

import httpx
import psycopg
import pytest

from app.llm import budget
from app.llm.base import LLMProfile, ProviderError
from app.llm.openai_compat import OpenAICompatProvider, parse_key_payload

PROFILE = LLMProfile(code="paid", provider="openai_compatible", model="vendor/paid")
SCHEMA = {"type": "object", "properties": {"ok": {"type": "boolean"}}, "required": ["ok"]}
MESSAGES = [{"role": "user", "content": "Синтетический тест"}]


@pytest.mark.parametrize(
    "row,expected", [(None, 10), ({}, 10), ({"openrouter_budget_usd": 3}, 3), ({"openrouter_budget_usd": 0}, 0)]
)
async def test_budget_reads_db_override_or_explicit_default(monkeypatch, row, expected):
    conn = AsyncMock()
    conn.execute.return_value.fetchone.return_value = (row,) if row is not None else None
    conn.__aenter__.return_value = conn
    monkeypatch.setattr(budget.psycopg.AsyncConnection, "connect", AsyncMock(return_value=conn))
    assert await budget.load_openrouter_budget(10) == expected
    assert conn.execute.await_args_list[0].args[0] == "set transaction read only"


@pytest.mark.parametrize("value", [None, True, "10", -1, float("nan"), float("inf")])
def test_unknown_or_invalid_budget_is_not_zero(value):
    with pytest.raises(ProviderError, match="бюджет OpenRouter неизвестен"):
        budget.budget_value(value)


async def test_budget_db_failure_is_closed(monkeypatch):
    monkeypatch.setattr(
        budget.psycopg.AsyncConnection, "connect", AsyncMock(side_effect=psycopg.OperationalError("offline"))
    )
    with pytest.raises(ProviderError, match="не удалось проверить бюджет"):
        await budget.load_openrouter_budget(10)


@pytest.mark.parametrize("usage", [None, True, "0", -1])
@pytest.mark.parametrize("stream", [False, True])
async def test_unknown_key_usage_never_starts_paid_completion(usage, stream):
    paths = []

    def handler(request):
        paths.append(request.url.path)
        return httpx.Response(200, json={"data": {"usage": usage, "limit_remaining": 10}})

    provider = OpenAICompatProvider("test", "https://openrouter.ai/api/v1", transport=httpx.MockTransport(handler))
    try:
        with pytest.raises(ProviderError, match="расход OpenRouter неизвестен"):
            if stream:
                _ = [token async for token in provider.stream(MESSAGES, PROFILE, timeout_s=1)]
            else:
                await provider.complete_structured(MESSAGES, SCHEMA, PROFILE, timeout_s=1)
        assert paths == ["/api/v1/key"]
    finally:
        await provider.aclose()


@pytest.mark.parametrize("stream", [False, True])
async def test_runtime_zero_budget_blocks_even_key_request(stream):
    requests = []
    provider = OpenAICompatProvider(
        "test",
        "https://openrouter.ai/api/v1",
        transport=httpx.MockTransport(lambda req: requests.append(req)),
        budget_loader=AsyncMock(return_value=0),
    )
    try:
        with pytest.raises(ProviderError, match="исчерпан"):
            if stream:
                _ = [token async for token in provider.stream(MESSAGES, PROFILE, timeout_s=1)]
            else:
                await provider.complete_structured(MESSAGES, SCHEMA, PROFILE, timeout_s=1)
        assert requests == []
    finally:
        await provider.aclose()


async def test_budget_is_rechecked_before_validation_retry_and_keeps_known_usage():
    paths = []

    def handler(request):
        paths.append(request.url.path)
        if request.url.path.endswith("/key"):
            return httpx.Response(200, json={"data": {"usage": 0 if len(paths) == 1 else 10, "limit_remaining": 20}})
        return httpx.Response(
            200,
            json={
                "choices": [{"message": {"content": '{"ok":"invalid"}'}}],
                "usage": {"prompt_tokens": 5, "completion_tokens": 3},
            },
        )

    loader = AsyncMock(return_value=10)
    provider = OpenAICompatProvider(
        "test", "https://openrouter.ai/api/v1", transport=httpx.MockTransport(handler), budget_loader=loader
    )
    try:
        with pytest.raises(ProviderError, match="достиг бюджета") as error:
            await provider.complete_structured(MESSAGES, SCHEMA, PROFILE, timeout_s=1)
        assert paths == ["/api/v1/key", "/api/v1/chat/completions", "/api/v1/key"]
        assert loader.await_count == 2
        assert error.value.usage.prompt_tokens == 5 and error.value.usage.completion_tokens == 3
    finally:
        await provider.aclose()


@pytest.mark.parametrize("stream", [False, True])
async def test_missing_paid_response_usage_is_explicit_error_not_zero(stream):
    def handler(request):
        if request.url.path.endswith("/key"):
            return httpx.Response(200, json={"data": {"usage": 0, "limit_remaining": None}})
        if stream:
            assert json.loads(request.content)["stream_options"]["include_usage"] is True
            return httpx.Response(
                200,
                text='data: {"choices":[{"delta":{"content":"Да"}}]}\n\ndata: [DONE]\n\n',
                headers={"Content-Type": "text/event-stream"},
            )
        return httpx.Response(200, json={"choices": [{"message": {"content": '{"ok":true}'}}]})

    provider = OpenAICompatProvider("test", "https://openrouter.ai/api/v1", transport=httpx.MockTransport(handler))
    try:
        with pytest.raises(ProviderError, match="расход платного") as error:
            if stream:
                _ = [token async for token in provider.stream(MESSAGES, PROFILE, timeout_s=1)]
            else:
                await provider.complete_structured(MESSAGES, SCHEMA, PROFILE, timeout_s=1)
        assert error.value.usage is None
    finally:
        await provider.aclose()


def test_key_payload_uses_reported_daily_limit():
    assert (
        parse_key_payload({"data": {"free_model_daily_requests": {"limit": 73}, "is_free_tier": True}})["rpd_limit"]
        == 73
    )


async def test_format_error_then_budget_rejection_keeps_usage_unknown():
    paths = []

    def handler(request):
        paths.append(request.url.path)
        if request.url.path.endswith("/key"):
            return httpx.Response(200, json={"data": {"usage": 0 if len(paths) == 1 else 10}})
        return httpx.Response(400, json={"error": {"message": "format unsupported"}})

    provider = OpenAICompatProvider("test", "https://openrouter.ai/api/v1", transport=httpx.MockTransport(handler))
    try:
        with pytest.raises(ProviderError, match="достиг бюджета") as error:
            await provider.complete_structured(MESSAGES, SCHEMA, PROFILE, timeout_s=1)
        assert error.value.usage is None
        assert len(paths) == 3
    finally:
        await provider.aclose()
