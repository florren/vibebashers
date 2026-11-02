"""Bench env credentials stay on their configured endpoint; all HTTP is Fake."""

import httpx
import pytest

from app.bench import service as bench
from app.config import Settings
from app.llm.base import LLMProfile, ProviderError
from app.llm.openai_compat import OpenAICompatProvider

ORIGIN = "https://synthetic-router.invalid/api/v1"
LOCAL = "http://127.0.0.1:4242/v1"
OR_KEY = "synthetic-router-credential"
LOCAL_KEY = "synthetic-local-credential"


@pytest.fixture
def endpoints(monkeypatch):
    settings = Settings(
        _env_file=None,
        app_env="test",
        llm_provider="mock",
        openrouter_api_key=OR_KEY,
        openrouter_base_url=ORIGIN,
        local_llm_api_key=LOCAL_KEY,
        local_llm_base_url=LOCAL,
    )
    monkeypatch.setattr(bench, "get_settings", lambda: settings)
    calls = []

    def fake(request):
        calls.append((str(request.url), request.headers.get("Authorization")))
        return httpx.Response(
            200,
            json={
                "id": "synthetic",
                "object": "chat.completion",
                "created": 1,
                "model": "synthetic:free",
                "choices": [{"index": 0, "message": {"role": "assistant", "content": "{}"}, "finish_reason": "stop"}],
                "usage": {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0},
            },
        )

    def factory(*args, **kwargs):
        return OpenAICompatProvider(*args, **kwargs, transport=httpx.MockTransport(fake))

    monkeypatch.setattr(bench, "OpenAICompatProvider", factory)
    return calls


@pytest.mark.parametrize(
    "local,base,secret",
    [(False, ORIGIN, OR_KEY), (False, ORIGIN + "/", OR_KEY), (True, LOCAL, LOCAL_KEY), (True, LOCAL + "/", LOCAL_KEY)],
)
async def test_intended_source_only_on_exact_endpoint_with_normalized_trailing_slash(endpoints, local, base, secret):
    profile = LLMProfile(
        code="synthetic", provider="openai_compatible", model="synthetic:free", base_url=base, extra={"local": local}
    )
    _, providers, _ = bench.BenchService().chain(profile, [])
    try:
        result, usage, _ = await providers[0].complete_structured([], {"type": "object"}, profile, timeout_s=1)
        assert result == {} and usage.total_tokens == 0
        assert endpoints == [(base.rstrip("/") + "/chat/completions", "Bearer " + secret)]
    finally:
        for provider in providers:
            await provider.aclose()


@pytest.mark.parametrize(
    "local,base",
    [
        (False, LOCAL),
        (False, ORIGIN + "/other"),
        (False, "https://other.invalid/api/v1"),
        (True, ORIGIN),
        (True, LOCAL + "/other"),
        (True, "http://127.0.0.1:4243/v1"),
    ],
)
def test_env_source_never_follows_wrong_endpoint_host_or_path(endpoints, local, base):
    profile = LLMProfile(
        code="synthetic", provider="openai_compatible", model="synthetic:free", base_url=base, extra={"local": local}
    )
    with pytest.raises(ProviderError) as denied:
        bench.BenchService().chain(profile, [])
    assert denied.value.kind == "auth"
    assert endpoints == []


def test_forecast_uses_server_floor_and_deduplicates_physical_aliases():
    service = bench.BenchService()
    from app.llm.keys import ApiKey

    service.keys["a"] = ApiKey("a", "synthetic", tokens_limit=100, tokens_used=99)
    first = {
        "id": 1,
        "label": "a",
        "_quota_group": "private-synthetic-group",
        "tokens_limit": 100,
        "tokens_used": 17,
        "usage_known": True,
        "tokens_remaining": 80,
    }
    second = {**first, "id": 2, "label": "b"}
    assert service.remaining([first, second]) == 80
    assert service.remaining([{**first, "usage_known": False, "tokens_remaining": None}]) is None
    assert service.remaining([{**first, "_quota_conflict": True}]) is None


def test_forecast_unknown_budget_is_not_treated_as_unlimited_and_uses_durable_profile_day():
    from app.bench.runner import BenchCase

    service = bench.BenchService()
    row = {
        "id": 1,
        "code": "synthetic",
        "provider": "openai_compatible",
        "model": "synthetic:free",
        "role": "bench_only",
        "base_url": ORIGIN,
        "rpd_limit": 5,
        "_requests_known": True,
        "_requests_today": 4,
    }
    key = {
        "id": 1,
        "label": "synthetic",
        "provider": "openai_compatible",
        "is_active": True,
        "endpoint_url": ORIGIN,
        "tokens_limit": 1000000,
        "tokens_used": 17,
        "usage_known": False,
        "requests_known": False,
        "tokens_remaining": None,
    }
    cases = [BenchCase(i, str(i), "chat", "fixed synthetic", {"signal_type": "complaint"}, []) for i in (1, 2)]
    unknown = service.forecast("synthetic", cases, row, [key], 1)
    assert not unknown["fits_limits"] and "неизвестен" in unknown["warning"]
    known = service.forecast(
        "synthetic", cases, row, [{**key, "usage_known": True, "requests_known": True, "tokens_remaining": 1000000}], 1
    )
    assert not known["fits_limits"] and "доступно 1 запросов сегодня" in known["warning"]
    # A process-local limiter reset cannot restore the already spent profile RPD.
    assert known["llm_profile_id"] == 1 and "_quota_group" not in known
