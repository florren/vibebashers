"""T-040: offline охватывает все роли; снимки не содержат credentials."""

from types import SimpleNamespace

import pytest

from app.llm.base import LLMProfile
from app.llm.failover import ProviderChain
from app.llm.run_profiles import _offline, _safe


def profiles():
    return {
        role: LLMProfile(code=role, provider="gigachat", model=f"pinned-{role}", role=role)
        for role in ("main", "fast", "twin")
    }


@pytest.mark.parametrize("mode", ["mock", "replay"])
def test_all_roles_remain_offline(monkeypatch, mode):
    monkeypatch.setattr("app.llm.run_profiles.get_settings", lambda: SimpleNamespace(llm_provider=mode))
    original = profiles()
    result = _offline(original)
    assert {p.provider for p in result.values()} == {mode}
    assert {p.provider for p in original.values()} == {"gigachat"}


def test_explicit_replay_only_chain_preserves_recorded_models(monkeypatch):
    monkeypatch.setattr("app.llm.run_profiles.get_settings", lambda: SimpleNamespace(llm_provider="mock"))
    chain = ProviderChain([SimpleNamespace(name="replay")])
    result = _offline(profiles(), profiles()["main"], chain, check_settings=False)
    assert {p.provider for p in result.values()} == {"replay"}
    assert {p.model for p in result.values()} == {"pinned-main", "pinned-fast", "pinned-twin"}


@pytest.mark.parametrize("extra", [{"api_key": "private"}, {"request": {"headers": {"Authorization": "private"}}}])
def test_profile_secret_fields_are_rejected(extra):
    with pytest.raises(ValueError, match="секреты"):
        _safe(LLMProfile(code="x", provider="gigachat", model="x", extra=extra))


@pytest.mark.parametrize(
    "url", ["https://user:private@example.invalid/v1", "https://example.invalid/v1?api_key=private"]
)
def test_profile_url_credentials_are_rejected(url):
    with pytest.raises(ValueError, match="credentials"):
        _safe(LLMProfile(code="x", provider="gigachat", model="x", base_url=url))


def test_existing_sampling_options_are_preserved():
    value = LLMProfile(
        code="x",
        provider="gigachat",
        model="x",
        extra={"json_schema": True, "structured_attempts": 1, "request": {"max_tokens": 400}},
    )
    assert _safe(value)["extra"] == value.extra


@pytest.mark.parametrize("value", [float("nan"), float("inf"), -1.0, True])
def test_invalid_tariff_is_rejected_before_snapshot(value):
    with pytest.raises(ValueError):
        _safe(LLMProfile(code="x", provider="gigachat", model="x", price_in_per_1m=value))
