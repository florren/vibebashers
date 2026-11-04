"""Package balance never becomes historical token consumption."""

import time

import httpx
import pytest

from app.llm.base import LLMProfile, ProviderError
from app.llm.gigachat import GigaChatProvider
from app.llm.gigachat_balance import parse_balance, require_balance
from app.llm.keys import ApiKey, KeyPool


@pytest.mark.parametrize(
    "body",
    [
        None,
        {},
        {"balance": []},
        {"balance": [None]},
        {"balance": [{"usage": "GigaChat", "value": value} for value in [1, 2]]},
        *[{"balance": [{"usage": "GigaChat", "value": value}]} for value in [-1, True, "12", 1.5, 2**63]],
    ],
)
def test_invalid_balance_is_not_zero_or_a_budget(body):
    with pytest.raises(ProviderError):
        parse_balance(body)


@pytest.mark.parametrize(
    "model,package",
    [
        ("GigaChat-3-Ultra", "GigaChat-Ultra"),
        ("GigaChat-3-Pro", "GigaChat-Pro"),
        ("GigaChat-3-Lightning", "GigaChat"),
        ("GigaChat-2-Max", "GigaChat-Max"),
    ],
)
def test_model_has_its_own_package(model, package):
    assert require_balance({package: 23, "embeddings": 999}, model) == 23
    with pytest.raises(ProviderError):
        require_balance({package: 0, "embeddings": 999}, model)


def test_unknown_or_missing_model_does_not_use_some_other_positive_balance():
    for model in ["unknown", "GigaChat-3-Ultra"]:
        with pytest.raises(ProviderError):
            require_balance({"GigaChat-Pro": 99}, model)


@pytest.mark.parametrize(
    "failure,kind",
    [
        (401, "auth"),
        (403, "quota"),
        (429, "rate_limit"),
        (500, "unavailable"),
        ("json", "bad_output"),
        ("timeout", "timeout"),
        ("network", "network"),
    ],
)
async def test_balance_transport_failure_is_explicit_and_never_an_inference(failure, kind):
    calls = []

    def http(request):
        calls.append(request.url.path)
        if request.url.path == "/oauth":
            return httpx.Response(
                200, json={"access_token": "synthetic-access", "expires_at": int((time.time() + 3600) * 1000)}
            )
        assert request.url.path == "/v1/balance"
        if failure == "timeout":
            raise httpx.ReadTimeout("synthetic", request=request)
        if failure == "network":
            raise httpx.ConnectError("synthetic", request=request)
        if failure == "json":
            return httpx.Response(200, text="invalid json")
        return httpx.Response(failure, headers={"Retry-After": "12"})

    key = ApiKey(label="synthetic", secret="synthetic-balance-secret")
    provider = GigaChatProvider(
        KeyPool([key]),
        oauth_url="https://balance.invalid/oauth",
        base_url="https://balance.invalid/v1",
        transport=httpx.MockTransport(http),
    )
    try:
        with pytest.raises(ProviderError) as caught:
            await provider.fetch_balance(
                key, LLMProfile(code="balance", provider="gigachat", model="GigaChat-3-Ultra"), timeout_s=2
            )
        assert caught.value.kind == kind
        if failure == 429:
            assert caught.value.retry_after_s == 12
        assert calls == ["/oauth", "/v1/balance"]
    finally:
        await provider.aclose()
