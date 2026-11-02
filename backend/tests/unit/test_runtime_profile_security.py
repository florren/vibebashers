"""T-051: synthetic secret boundary before DB/network."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from app.config import get_settings
from app.llm.credentials import endpoint, public_key
from app.main import create_app


@pytest.mark.parametrize(
    "url",
    [
        "https://user:synthetic-secret@example.invalid/v1",
        "https://example.invalid/v1?opaque=synthetic-secret",
        "https://example.invalid/v1#synthetic-secret",
        "file:///synthetic-secret",
    ],
)
def test_endpoint_rejects_credentials_and_non_http(url):
    with pytest.raises(ValueError, match="endpoint"):
        endpoint(url)


def test_public_projection_is_positive_and_does_not_mutate():
    item = {
        "id": 1,
        "provider": "gigachat",
        "_secret": "synthetic-plain",
        "encrypted_key": "synthetic-cipher",
        "credential_uid": "synthetic-private",
        "future_private_field": "synthetic-private",
    }
    output = public_key(item)
    assert output["id"] == 1
    assert not set(output) & {"_secret", "encrypted_key", "credential_uid", "future_private_field"}
    assert item["_secret"] == "synthetic-plain"


@pytest.mark.parametrize(
    "path,payload",
    [
        ("/api/settings/llm-keys", {"provider": "gigachat", "label": "synthetic", "key": "x"}),
        (
            "/api/settings/llm-keys",
            {
                "provider": "gigachat",
                "label": "synthetic",
                "key": "synthetic-key",
                "endpoint_url": "https://user:synthetic-url-secret@example.invalid/v1",
            },
        ),
        (
            "/api/settings/llm-profiles",
            {
                "code": "synthetic",
                "provider": "gigachat",
                "model": "demo",
                "extra": {"request": {"headers": {"Authorization": "Bearer synthetic-header-secret"}}},
            },
        ),
        (
            "/api/setup/test-llm",
            {
                "provider": "gigachat",
                "model": "demo",
                "base_url": "https://example.invalid/v1?key=synthetic-url-secret",
                "api_key": "synthetic-key",
            },
        ),
    ],
)
def test_validation_errors_do_not_echo_secret_inputs(monkeypatch, path, payload):
    monkeypatch.setenv("APP_ENV", "test")
    monkeypatch.setenv("LLM_PROVIDER", "mock")
    monkeypatch.setenv("LLM_CHAIN", "mock")
    get_settings.cache_clear()
    try:
        with TestClient(create_app()) as client:
            response = client.post(path, json=payload)
        assert response.status_code == 422
        assert "synthetic-key" not in response.text
        assert "synthetic-url-secret" not in response.text
        assert "synthetic-header-secret" not in response.text
        for error in response.json()["errors"]:
            assert set(error) <= {"type", "loc", "msg"}
    finally:
        get_settings.cache_clear()


@pytest.mark.parametrize("mode", ["mock", "replay"])
async def test_explicit_chain_offline_mode_never_invokes_live_candidates(mode):
    from app.llm.base import LLMProfile
    from app.llm.failover import ProviderChain

    class LiveSentinel:
        name = "gigachat"

        async def complete_structured(self, *args, **kwargs):
            pytest.fail("forced offline must not invoke live provider")

        async def stream(self, *args, **kwargs):
            pytest.fail("forced offline must not invoke live stream")
            yield ""

    chain = ProviderChain([LiveSentinel()], offline_mode=mode)
    profile = LLMProfile(code="live", provider="gigachat", model="synthetic-live", api_key_id=123)
    result = await chain.complete_structured(
        [{"role": "user", "content": "fixed synthetic"}], {"type": "object"}, profile
    )
    assert result.usage.source == "mock"
    assert [part async for part in chain.stream([{"role": "user", "content": "fixed synthetic"}], profile)]


def test_authoritative_role_providers_are_independent(monkeypatch):
    from types import SimpleNamespace

    from app.llm.base import LLMProfile
    from app.llm.run_profiles import _forced

    monkeypatch.setattr("app.llm.run_profiles.get_settings", lambda: SimpleNamespace(llm_provider="gigachat"))
    roles = {
        role: LLMProfile(code=role, provider="mock" if role == "main" else "gigachat", model=role, role=role)
        for role in ("main", "fast", "twin")
    }
    assert {role: p.provider for role, p in _forced(roles).items()} == {
        "main": "mock",
        "fast": "gigachat",
        "twin": "gigachat",
    }
    monkeypatch.setattr("app.llm.run_profiles.get_settings", lambda: SimpleNamespace(llm_provider="replay"))
    assert {p.provider for p in _forced(roles).values()} == {"replay"}


def test_generic_credential_write_routes_reject_before_db_and_hide_invalid_body(monkeypatch):
    from contextlib import asynccontextmanager

    from app.api import settings

    @asynccontextmanager
    async def forbidden_db():
        pytest.fail("legacy credential writes must be refused before SQL")
        yield None

    monkeypatch.setattr(settings, "db", forbidden_db)
    monkeypatch.setenv("APP_ENV", "test")
    monkeypatch.setenv("LLM_PROVIDER", "mock")
    monkeypatch.setenv("LLM_CHAIN", "mock")
    get_settings.cache_clear()
    try:
        with TestClient(create_app()) as client:
            assert client.patch("/api/settings", json={"llm_keys": [{"key": "synthetic-key"}]}).status_code == 422
            assert (
                client.post(
                    "/api/settings/import", json={"settings": {"llm_keys": [{"key": "synthetic-key"}]}}
                ).status_code
                == 422
            )
            response = client.patch("/api/settings", json=["synthetic-key"])
        assert response.status_code == 422 and "synthetic-key" not in response.text
    finally:
        get_settings.cache_clear()


def test_lifespan_releases_runtime_key_state_even_if_loop_is_still_referenced(monkeypatch):
    import asyncio

    from app.llm import runtime_provider

    monkeypatch.setenv("APP_ENV", "test")
    monkeypatch.setenv("LLM_PROVIDER", "mock")
    monkeypatch.setenv("LLM_CHAIN", "mock")
    get_settings.cache_clear()
    app = create_app()
    loops = []

    async def install_state():
        loop = asyncio.get_running_loop()
        loops.append(loop)
        runtime_provider._key_state(
            {
                "id": 7,
                "_credential_uid": "synthetic-private-id",
                "_secret": "synthetic-key",
                "tokens_used": 0,
                "tokens_limit": 4,
            }
        )
        assert loop in runtime_provider._KEY_STATES
        return {"stored": True}

    app.add_api_route("/synthetic-runtime-state", install_state)
    try:
        with TestClient(app) as client:
            assert client.get("/synthetic-runtime-state").json() == {"stored": True}
        assert loops and loops[0] not in runtime_provider._KEY_STATES
    finally:
        get_settings.cache_clear()
