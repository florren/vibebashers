"""Роли моделей, TLS и гарантированный офлайн без живых провайдеров."""

from __future__ import annotations

import dataclasses
import ssl
from pathlib import Path

import pytest
import yaml

from app.config import Settings
from app.errors import Problem
from app.llm.failover import ProviderChain
from app.llm.gigachat import GigaChatProvider
from app.llm.keys import KeyPool
from app.llm.mock import MockProvider
from app.llm.roles import select
from app.llm.tls import BUNDLED_CA, context

ROOT = Path(__file__).resolve().parents[3]


def rows():
    profiles = yaml.safe_load((ROOT / "data/llm_profiles.yaml").read_text())["llm_profiles"]
    return [{"id": i, **p} for i, p in enumerate(profiles, 1)]


def test_roles_and_selected_profile_override():
    settings = Settings(_env_file=None, llm_provider="gigachat")
    profiles = select(settings, rows(), {})
    assert {r: p.model for r, p in profiles.items()} == {
        "main": "GigaChat-3-Ultra",
        "fast": "GigaChat-3-Lightning",
        "twin": "GigaChat-3-Pro",
    }
    chosen = select(settings, rows(), {"main_profile_id": 2})
    assert chosen["main"].model == "GigaChat-3-Pro"
    assert chosen["main"].role == "main"
    with pytest.raises(Problem):
        select(settings, rows(), {"main_profile_id": 99999})
    inactive = [{**p, "is_active": False} for p in rows()]
    with pytest.raises(Problem):
        select(settings, inactive, {"main_profile_id": 1})


def test_tls_contains_both_certificates_and_rejects_disabled_verification():
    ctx = context()
    assert ctx.verify_mode == ssl.CERT_REQUIRED and ctx.check_hostname
    assert BUNDLED_CA.read_text().count("-----BEGIN CERTIFICATE-----") == 2
    trusted = ctx.get_ca_certs()
    assert any("Russian Trusted Root CA" in str(c["subject"]) for c in trusted)
    assert any("Russian Trusted Sub CA" in str(c["subject"]) for c in trusted)
    with pytest.raises(ValueError, match="TLS"):
        GigaChatProvider(
            KeyPool(), oauth_url="https://example.invalid", base_url="https://example.invalid", verify_ssl=False
        )
    with pytest.raises(FileNotFoundError):
        context("/nonexistent/custom-ca.pem")


@pytest.mark.parametrize("provider", ["mock", "replay"])
async def test_explicit_offline_mode_never_uses_live_keys(provider):
    settings = Settings(_env_file=None, llm_provider=provider)
    profiles = select(settings, rows(), {})
    assert all(p.provider == provider for p in profiles.values())

    class Forbidden(MockProvider):
        name = "gigachat"

        async def complete_structured(self, *args, **kwargs):
            pytest.fail("офлайн не должен вызывать живой провайдер")

        async def stream(self, *args, **kwargs):
            pytest.fail("офлайн streaming не должен вызывать живой провайдер")
            yield ""

    chain = ProviderChain([Forbidden(), MockProvider()])
    for p in profiles.values():
        result = await chain.complete_structured(
            [{"role": "user", "content": "Синтетическая проверка"}],
            {"type": "object", "properties": {"ok": {"type": "boolean"}}, "required": ["ok"]},
            p,
        )
        assert result.provider == "mock"
        assert result.attempts[0].provider == "mock"
        chunks = [part async for part in chain.stream([{"role": "user", "content": "Тест"}], p)]
        assert chunks
    chain.role_profiles = profiles
    assert chain.profile_for("fast", dataclasses.replace(profiles["main"])) == profiles["fast"]


def test_openai_default_and_gigachat_missing_rows_do_not_pick_wrong_provider():
    settings = Settings(_env_file=None, llm_provider="openai_compat")
    assert select(settings, rows(), {})["main"].provider == "openai_compatible"
    missing = select(Settings(_env_file=None, llm_provider="gigachat"), [], {})
    assert missing["fast"].model == "GigaChat-3-Lightning"
    assert missing["twin"].model == "GigaChat-3-Pro"
