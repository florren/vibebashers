"""T-048: официальный SDK с фиктивным транспортом, без внешних LLM."""

import json
from contextlib import asynccontextmanager
from types import SimpleNamespace
from unittest.mock import AsyncMock

import httpx
import pytest

from app.api import setup
from app.llm.base import LLMProfile, ProviderError, Usage
from app.llm.openai_compat import OpenAICompatProvider, is_openrouter

SCHEMA = {"type": "object", "properties": {"ok": {"type": "boolean"}}, "required": ["ok"]}
MESSAGES = [{"role": "user", "content": "Тест"}]
PROFILE = LLMProfile(code="test", provider="openai_compatible", model="local")


def response(content):
    return httpx.Response(
        200,
        json={"choices": [{"message": {"content": content}}], "usage": {"prompt_tokens": 5, "completion_tokens": 3}},
    )


@pytest.mark.parametrize(
    "status,kind", [(401, "auth"), (403, "auth"), (402, "quota"), (429, "rate_limit"), (503, "unavailable")]
)
@pytest.mark.parametrize("stream", [False, True])
async def test_sdk_errors_are_sanitized_and_never_implicitly_retried(status, kind, stream):
    requests = []

    def handler(request):
        requests.append(request)
        assert request.headers["X-Stainless-Lang"] == "python"
        return httpx.Response(
            status, json={"error": {"message": "echo-sensitive-value"}}, headers={"Retry-After": "broken"}
        )

    provider = OpenAICompatProvider("test", "https://local.test/v1", transport=httpx.MockTransport(handler))
    try:
        with pytest.raises(ProviderError) as error:
            if stream:
                _ = [token async for token in provider.stream(MESSAGES, PROFILE, timeout_s=1)]
            else:
                await provider.complete_structured(MESSAGES, SCHEMA, PROFILE, timeout_s=1)
        assert error.value.kind == kind and error.value.status == status
        assert "echo-sensitive-value" not in str(error.value)
        assert len(requests) == 1
        if status == 429:
            assert error.value.retry_after_s == 20
    finally:
        await provider.aclose()
    assert provider._client.is_closed


async def test_sdk_format_fallback_preserves_validation_retry_and_usage():
    seen = []

    def handler(request):
        seen.append(json.loads(request.content))
        if len(seen) == 1:
            return httpx.Response(400, json={"error": {"message": "json_schema unsupported"}})
        return response('{"ok": "wrong"}' if len(seen) == 2 else '{"ok": true}')

    provider = OpenAICompatProvider(None, "http://local.test/v1", transport=httpx.MockTransport(handler))
    try:
        obj, usage, _ = await provider.complete_structured(MESSAGES, SCHEMA, PROFILE, timeout_s=1)
        assert obj == {"ok": True}
        assert [item["response_format"]["type"] for item in seen] == ["json_schema", "json_object", "json_object"]
        assert usage.prompt_tokens == 10 and usage.completion_tokens == 6
        assert usage.request_count == 3 and usage.structured_retries == 1 and not usage.json_valid_first_try
        assert "не прошёл валидацию" in seen[-1]["messages"][-1]["content"]
    finally:
        await provider.aclose()


@pytest.mark.parametrize("key", [None, "local-test"])
async def test_sdk_stream_local_profile_url_auth_and_terminal_chunk(key, monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "must-not-forward")
    seen = []

    def handler(request):
        seen.append(request)
        assert str(request.url) == "http://local.test/v1/chat/completions"
        assert request.headers.get("Authorization") == (f"Bearer {key}" if key else None)
        chunks = [
            {"choices": [{"delta": {"content": "Да"}}]},
            {"choices": [{"delta": {"content": "!"}}]},
            {"choices": [], "usage": {"prompt_tokens": 1, "completion_tokens": 2}},
        ]
        body = "".join("data: " + json.dumps(chunk) + "\n\n" for chunk in chunks) + "data: [DONE]\n\n"
        return httpx.Response(200, text=body, headers={"Content-Type": "text/event-stream"})

    provider = OpenAICompatProvider(key, "http://configured.test/v1", transport=httpx.MockTransport(handler))
    profile = LLMProfile(code="local", provider="openai_compatible", model="local", base_url="http://local.test/v1")
    try:
        assert [token async for token in provider.stream(MESSAGES, profile, timeout_s=1)] == ["Да", "!"]
        assert len(seen) == 1
    finally:
        await provider.aclose()


def test_openrouter_host_match_is_exact():
    assert is_openrouter("https://openrouter.ai/api/v1")
    assert not is_openrouter("https://openrouter.ai.attacker.test/v1")
    assert not is_openrouter("https://local.test/openrouter.ai")


async def test_setup_accepts_keyless_local_without_forwarding_openrouter_key(monkeypatch):
    @asynccontextmanager
    async def db():
        yield object()

    monkeypatch.setattr(setup, "db", db)
    monkeypatch.setattr(setup, "load_keys", AsyncMock(return_value=[]))
    monkeypatch.setattr(
        setup,
        "get_settings",
        lambda: SimpleNamespace(
            openrouter_api_key="private-or-key",
            openrouter_base_url="https://openrouter.ai/api/v1",
            openrouter_budget_usd=10,
            app_port=8000,
        ),
    )
    seen = []

    class Provider:
        def __init__(self, key, base, **kwargs):
            seen.append((key, base))

        async def complete_structured(self, *args, **kwargs):
            return {"ok": True}, Usage(), "{}"

        async def aclose(self):
            pass

    monkeypatch.setattr(setup, "OpenAICompatProvider", Provider)
    result = await setup.post_setup_test_llm(
        setup.TestLlmBody(provider="openai_compatible", model="local", base_url="http://local.test/v1")
    )
    assert result["ok"] is True
    assert seen == [(None, "http://local.test/v1")]


async def test_startup_missing_default_model_deactivates_profile_without_stopping(monkeypatch):
    from app import main
    from app.llm.openai_compat import DEFAULT_MODEL_IDS, PREFERRED_REPLACEMENT

    conn = AsyncMock()
    conn.__aenter__.return_value = conn
    monkeypatch.setattr(main.psycopg.AsyncConnection, "connect", AsyncMock(return_value=conn))
    provider = OpenAICompatProvider(
        "test",
        "https://openrouter.ai/api/v1",
        transport=httpx.MockTransport(
            lambda req: httpx.Response(
                200, json={"data": [{"id": model} for model in [*DEFAULT_MODEL_IDS[1:], PREFERRED_REPLACEMENT]]}
            )
        ),
    )
    try:
        await main._sync_openrouter_models(SimpleNamespace(providers=[provider]))
        conn.commit.assert_awaited_once()
        assert conn.execute.await_count == 1
        params = conn.execute.await_args.args[1]
        assert params[1] == DEFAULT_MODEL_IDS[0]
        assert params[0].obj == {"suggested_model": PREFERRED_REPLACEMENT}
        assert "is_active = false" in conn.execute.await_args.args[0]
    finally:
        await provider.aclose()


@pytest.mark.parametrize("local_key", [None, "local-specific"])
async def test_chain_routes_endpoint_credentials_without_forwarding_openrouter_secret(local_key, tmp_path):
    from app.config import Settings
    from app.llm.failover import build_chain, profile_by_code

    settings = Settings(
        _env_file=None,
        llm_chain="openai_compat",
        openrouter_api_key="or-specific",
        local_llm_base_url="http://local.test/v1",
        local_llm_api_key=local_key,
        cassettes_dir=str(tmp_path),
    )
    seen = []

    def handler(req):
        seen.append((req.url.host, req.headers.get("Authorization")))
        return response('{"ok":true}')

    chain = build_chain(settings, transport=httpx.MockTransport(handler))
    provider = chain.providers[0]
    try:
        await provider.complete_structured(MESSAGES, SCHEMA, profile_by_code(settings, "local_openai"), timeout_s=1)
        await provider.complete_structured(MESSAGES, SCHEMA, profile_by_code(settings, "or_gpt_oss_120b"), timeout_s=1)
        assert seen == [
            ("local.test", f"Bearer {local_key}" if local_key else None),
            ("openrouter.ai", "Bearer or-specific"),
        ]
    finally:
        await provider.aclose()


async def test_benchmark_local_profile_resolves_env_without_openrouter_key(monkeypatch):
    from app.bench import service
    from app.config import Settings

    settings = Settings(_env_file=None, openrouter_api_key="or-private", local_llm_base_url="http://local.test/v1")
    monkeypatch.setattr(service, "get_settings", lambda: settings)
    profile = LLMProfile(
        code="local_openai", provider="openai_compatible", model="local", base_url="", extra={"local": True}
    )
    _chain, providers, selected = service.BenchService().chain(profile, [])
    try:
        assert selected is None
        assert providers[0].base_url == "http://local.test/v1"
        assert providers[0].api_key is None
    finally:
        await providers[0].aclose()


@pytest.mark.parametrize("body", [{"data": [{"id": None}]}, {"data": "broken"}, []])
async def test_malformed_catalog_does_not_deactivate_or_stop_startup(body):
    from app.llm.openai_compat import openrouter_deactivation_plan

    provider = OpenAICompatProvider(
        "test",
        "https://openrouter.ai/api/v1",
        transport=httpx.MockTransport(lambda req: httpx.Response(200, json=body)),
    )
    try:
        assert await openrouter_deactivation_plan(provider) == []
    finally:
        await provider.aclose()
