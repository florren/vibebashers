"""T-051: только synthetic credentials; отказ вместо подмены model output."""

from __future__ import annotations

import json
import time

import httpx
import pytest

from app.llm.base import LLMProfile, ProviderError
from app.llm.credential_boundary import REFLECTION, CredentialStreamGuard, reject_reflection, retry_after
from app.llm.gigachat import GigaChatProvider
from app.llm.keys import ApiKey, KeyPool
from app.llm.openai_compat import OpenAICompatProvider

SECRET = "synthetic-credential-opaque"
ACCESS = "synthetic-access-opaque"
MESSAGES = [{"role": "user", "content": "fixed synthetic prompt"}]
SCHEMA = {
    "type": "object",
    "properties": {"ok": {"type": "boolean"}, "note": {"type": "string"}},
    "required": ["ok", "note"],
}


@pytest.mark.parametrize(
    "value",
    [
        SECRET,
        {"note": SECRET},
        json.dumps({"note": SECRET}),
        '{"note":"' + "".join(f"\\u{ord(char):04x}" for char in SECRET) + '"}',
        '{"' + "".join(f"\\u{ord(char):04x}" for char in SECRET) + '":true}',
    ],
)
def test_exact_credential_reflection_is_refused(value):
    with pytest.raises(ProviderError) as refused:
        reject_reflection(value, [None, SECRET])
    assert refused.value.detail == REFLECTION and SECRET not in str(refused.value)


def test_valid_text_and_numbers_are_untouched():
    value = {"note": "обычный корректный trace", "count": 17, "nested": [True, None]}
    assert reject_reflection(value, [SECRET]) is None
    assert reject_reflection(value, []) is None
    guard = CredentialStreamGuard([SECRET])
    assert guard.feed("plain ") + guard.feed("trace") + guard.finish() == "plain trace"


def test_stream_holds_only_ambiguous_prefix_and_refuses_split_secret():
    guard = CredentialStreamGuard([SECRET])
    assert guard.feed("prefix synthetic-") == "prefix "
    assert guard.feed("credential-") == ""
    with pytest.raises(ProviderError, match=REFLECTION):
        guard.feed("opaque")
    benign = CredentialStreamGuard([SECRET])
    assert benign.feed("synthetic-") == ""
    assert benign.feed("ordinary") == "synthetic-ordinary"
    assert benign.finish() == ""
    partial = CredentialStreamGuard([SECRET])
    assert partial.feed("synthetic-") == "" and partial.finish() == "synthetic-"


@pytest.mark.parametrize(
    "value,expected", [(None, 20), ("3.5", 3.5), ("invalid", 20), ("nan", 20), ("inf", 20), ("-2", 20), ("0", 0)]
)
def test_retry_after_valid_values_preserved_and_invalid_values_do_not_echo(value, expected):
    assert retry_after(value) == expected


def giga(handler):
    return GigaChatProvider(
        KeyPool([ApiKey("synthetic-label", SECRET)]),
        oauth_url="https://synthetic.invalid/oauth",
        base_url="https://synthetic.invalid/v1",
        transport=httpx.MockTransport(handler),
    )


@pytest.mark.parametrize("stage", ["oauth", "chat"])
@pytest.mark.parametrize("status,kind", [(401, "auth"), (403, "auth"), (429, "rate_limit"), (503, "unavailable")])
async def test_giga_error_diagnostics_never_echo_authorization_before_pool_logging(stage, status, kind, capsys):
    def handler(request):
        if request.url.path.endswith("oauth") and stage == "chat":
            return httpx.Response(200, json={"access_token": ACCESS, "expires_at": (time.time() + 3600) * 1000})
        return httpx.Response(status, text="Authorization: Basic " + SECRET, headers={"Retry-After": "7"})

    provider = giga(handler)
    try:
        with pytest.raises(ProviderError) as refused:
            await provider.complete_structured(
                MESSAGES, SCHEMA, LLMProfile(code="giga", provider="gigachat", model="synthetic"), timeout_s=2
            )
        assert refused.value.kind == kind and refused.value.status == status
        assert SECRET not in str(refused.value)
        assert SECRET not in (provider.pool.keys[0].last_error or "")
        assert SECRET not in capsys.readouterr().out
        if status == 429:
            assert refused.value.retry_after_s == 7
    finally:
        await provider.aclose()


@pytest.mark.parametrize("which", ["auth", "access"])
async def test_giga_schema_valid_200_reflection_is_rejected_with_known_usage(which):
    reflected = SECRET if which == "auth" else ACCESS

    def handler(request):
        if request.url.path.endswith("oauth"):
            return httpx.Response(200, json={"access_token": ACCESS, "expires_at": (time.time() + 3600) * 1000})
        return httpx.Response(
            200,
            json={
                "choices": [{"message": {"content": json.dumps({"ok": True, "note": reflected})}}],
                "usage": {"prompt_tokens": 3, "completion_tokens": 4, "total_tokens": 7},
            },
        )

    provider = giga(handler)
    try:
        with pytest.raises(ProviderError) as refused:
            await provider.complete_structured(
                MESSAGES, SCHEMA, LLMProfile(code="giga", provider="gigachat", model="synthetic"), timeout_s=2
            )
        assert refused.value.kind == "bad_output" and refused.value.detail == REFLECTION
        assert refused.value.usage.total_tokens == 7
        assert provider.pool.keys[0].tokens_used == 7
        assert reflected not in str(refused.value)
    finally:
        await provider.aclose()


async def test_openai_schema_valid_200_reflection_is_rejected_with_known_usage():
    def handler(request):
        return httpx.Response(
            200,
            json={
                "choices": [{"message": {"content": json.dumps({"ok": True, "note": SECRET})}}],
                "usage": {"prompt_tokens": 3, "completion_tokens": 4, "total_tokens": 7},
            },
        )

    provider = OpenAICompatProvider(SECRET, "https://synthetic.invalid/v1", transport=httpx.MockTransport(handler))
    try:
        with pytest.raises(ProviderError) as refused:
            await provider.complete_structured(
                MESSAGES,
                SCHEMA,
                LLMProfile(code="sdk", provider="openai_compatible", model="synthetic:free"),
                timeout_s=2,
            )
        assert refused.value.kind == "bad_output" and refused.value.detail == REFLECTION
        assert refused.value.usage.total_tokens == 7 and SECRET not in str(refused.value)
    finally:
        await provider.aclose()


@pytest.mark.parametrize("provider_kind", ["gigachat", "openai_compatible"])
async def test_provider_stream_rejects_split_credential_without_yielding_it(provider_kind):
    frames = []
    for text in ("prefix synthetic-", "credential-", "opaque"):
        frames.append(
            "data: "
            + json.dumps(
                {"choices": [{"delta": {"content": text}}], "usage": {"total_tokens": 7} if text == "opaque" else None}
            )
            + "\n\n"
        )
    frames.append("data: [DONE]\n\n")

    def handler(request):
        if request.url.path.endswith("oauth"):
            return httpx.Response(200, json={"access_token": ACCESS, "expires_at": (time.time() + 3600) * 1000})
        return httpx.Response(200, headers={"Content-Type": "text/event-stream"}, content="".join(frames))

    provider = (
        giga(handler)
        if provider_kind == "gigachat"
        else OpenAICompatProvider(SECRET, "https://synthetic.invalid/v1", transport=httpx.MockTransport(handler))
    )
    emitted = []
    try:
        with pytest.raises(ProviderError, match=REFLECTION):
            async for text in provider.stream(
                MESSAGES, LLMProfile(code="stream", provider=provider_kind, model="synthetic:free"), timeout_s=2
            ):
                emitted.append(text)
        assert "".join(emitted) == "prefix "
        if provider_kind == "gigachat":
            assert provider.pool.keys[0].tokens_used == 7
    finally:
        await provider.aclose()


async def test_giga_error_body_is_absent_from_console_and_jsonl(monkeypatch, tmp_path, capsys):
    import structlog

    from app.logging import configure_logging, get_logger

    previous = structlog.get_config()
    log_path = tmp_path / "synthetic.jsonl"
    configure_logging("test", log_path)
    monkeypatch.setattr("app.llm.keys.log", get_logger("synthetic-key-errors"))
    provider = giga(lambda request: httpx.Response(401, text="Authorization: Basic " + SECRET))
    try:
        with pytest.raises(ProviderError):
            await provider.complete_structured(
                MESSAGES, SCHEMA, LLMProfile(code="test", provider="gigachat", model="synthetic"), timeout_s=2
            )
        captured = capsys.readouterr()
        assert SECRET not in captured.out + captured.err
        stored = log_path.read_text()
        assert "llm_key_error" in stored and SECRET not in stored
    finally:
        await provider.aclose()
        structlog.configure(**previous)


async def test_oauth_private_token_field_is_not_public_model_output():
    # Провайдер может вернуть opaque private access_token; он не выдаётся в API/trace.
    provider = giga(
        lambda request: httpx.Response(
            200, json={"access_token": "private-" + SECRET, "expires_at": (time.time() + 3600) * 1000, "debug": SECRET}
        )
    )
    try:
        with pytest.raises(ProviderError, match=REFLECTION):
            await provider.complete_structured(
                MESSAGES, SCHEMA, LLMProfile(code="test", provider="gigachat", model="synthetic"), timeout_s=2
            )
        assert provider.pool.keys[0].access_token is None
    finally:
        await provider.aclose()
