"""Сбой OpenRouter без usage сохраняет только безопасный указатель для сверки."""

from __future__ import annotations

import httpx
import pytest

from app.llm.base import LLMProfile, ProviderError
from app.llm.openai_compat import OpenAICompatProvider

BASE = "https://openrouter.ai/api/v1"
KEY = "synthetic-private-key"
MODEL = "synthetic:free"
SCHEMA = {"type": "object", "properties": {"ok": {"type": "boolean"}}, "required": ["ok"]}
GENERATION = "gen-1234567890-Synthetic"


@pytest.mark.parametrize("where", ["body", "header", "both"])
async def test_missing_usage_openrouter_recovery_reference(where):
    calls = []

    def http(request):
        calls.append(request)
        body = {"error": {"code": 502, "message": "Do not publish upstream content: " + KEY}}
        if where in ("body", "both"):
            body["id"] = GENERATION
        headers = {"X-Generation-Id": GENERATION} if where in ("header", "both") else {}
        return httpx.Response(200, json=body, headers=headers)

    provider = OpenAICompatProvider(KEY, BASE, transport=httpx.MockTransport(http))
    try:
        with pytest.raises(ProviderError) as error:
            await provider.complete_structured(
                [{"role": "user", "content": "Синтетическая проверка"}],
                SCHEMA,
                LLMProfile(code="trace", provider="openai_compatible", model=MODEL),
                timeout_s=2,
            )
        assert error.value.kind == "bad_output" and error.value.usage is None and error.value.status is None
        assert f"generation_id={GENERATION}" in error.value.detail
        assert "provider_error_code=502" in error.value.detail
        assert KEY not in str(error.value) and "Do not publish" not in str(error.value)
        assert len(calls) == 1
    finally:
        await provider.aclose()


@pytest.mark.parametrize(
    "body_id,header_id,code,expected_ref,expected_code",
    [
        (None, None, 502, None, 502),
        ("gen-" + "a" * 124, None, 429, "gen-" + "a" * 124, 429),
        ("gen-" + "a" * 125, None, 502, None, 502),
        ("gen-проверка", None, 502, None, 502),
        ("gen-", None, 502, None, 502),
        ("gen-id/unsafe", None, 502, None, 502),
        ("gen-" + KEY, None, 502, None, 502),
        ("gen-" + KEY, GENERATION, 502, GENERATION, 502),
        (GENERATION, "gen-other", 502, None, 502),
        (GENERATION, None, True, GENERATION, None),
        (GENERATION, None, "502", GENERATION, None),
        (GENERATION, None, 502.5, GENERATION, None),
        (GENERATION, None, 10**100, GENERATION, None),
    ],
)
async def test_missing_usage_metadata_is_bounded_and_never_reflects_secret(
    body_id, header_id, code, expected_ref, expected_code
):
    def http(request):
        return httpx.Response(
            200,
            json={"id": body_id, "error": {"code": code, "message": KEY}, "private": KEY},
            headers={"X-Generation-Id": header_id} if header_id is not None else {},
        )

    provider = OpenAICompatProvider(KEY, BASE, transport=httpx.MockTransport(http))
    try:
        with pytest.raises(ProviderError) as error:
            await provider.complete_structured(
                [], SCHEMA, LLMProfile(code="trace", provider="openai_compatible", model=MODEL), timeout_s=2
            )
        detail = error.value.detail
        assert error.value.kind == "bad_output" and error.value.usage is None
        assert KEY not in detail and "private" not in detail
        assert ("generation_id=" in detail) is (expected_ref is not None)
        assert ("provider_error_code=" in detail) is (expected_code is not None)
        if expected_ref is not None:
            assert f"generation_id={expected_ref}" in detail
        if expected_code is not None:
            assert f"provider_error_code={expected_code}" in detail
    finally:
        await provider.aclose()


async def test_local_missing_usage_does_not_adopt_openrouter_reference_convention():
    provider = OpenAICompatProvider(
        KEY,
        "https://local.invalid/v1",
        transport=httpx.MockTransport(
            lambda request: httpx.Response(
                200, json={"id": GENERATION, "error": {"code": 502}}, headers={"X-Generation-Id": GENERATION}
            )
        ),
    )
    try:
        with pytest.raises(ProviderError) as error:
            await provider.complete_structured(
                [], SCHEMA, LLMProfile(code="local", provider="openai_compatible", model="local"), timeout_s=2
            )
        assert error.value.detail == "расход ответа неизвестен: usage отсутствует"
    finally:
        await provider.aclose()


async def test_missing_usage_without_error_envelope_retains_header_not_content():
    provider = OpenAICompatProvider(
        KEY,
        BASE,
        transport=httpx.MockTransport(
            lambda request: httpx.Response(
                200,
                json={"choices": [{"message": {"content": "Private upstream content " + KEY}}]},
                headers={"X-Generation-Id": GENERATION},
            )
        ),
    )
    try:
        with pytest.raises(ProviderError) as error:
            await provider.complete_structured(
                [], SCHEMA, LLMProfile(code="trace", provider="openai_compatible", model=MODEL), timeout_s=2
            )
        assert f"generation_id={GENERATION}" in error.value.detail
        assert "provider_error_code=" not in error.value.detail
        assert KEY not in error.value.detail and "Private upstream content" not in error.value.detail
    finally:
        await provider.aclose()


async def test_paid_missing_usage_keeps_existing_error_kind_and_budget_preflight():
    calls = []

    def http(request):
        calls.append(request.url.path)
        if request.url.path.endswith("/key"):
            return httpx.Response(200, json={"data": {"usage": 0, "limit": 50, "limit_remaining": 50}})
        return httpx.Response(200, json={"id": GENERATION, "error": {"code": 502, "message": KEY}})

    provider = OpenAICompatProvider(KEY, BASE, transport=httpx.MockTransport(http))
    try:
        with pytest.raises(ProviderError) as error:
            await provider.complete_structured(
                [], SCHEMA, LLMProfile(code="paid", provider="openai_compatible", model="synthetic-paid"), timeout_s=2
            )
        assert error.value.kind == "bad_output" and error.value.usage is None and error.value.status is None
        assert error.value.detail.startswith("расход платного ответа неизвестен: usage отсутствует")
        assert f"generation_id={GENERATION}" in error.value.detail
        assert calls == ["/api/v1/key", "/api/v1/chat/completions"]
    finally:
        await provider.aclose()
