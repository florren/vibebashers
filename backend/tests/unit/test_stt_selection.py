"""T257: отсутствие offline STT не разрешает неявный внешний browser provider."""

from dataclasses import dataclass
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from fastapi import HTTPException

from app.api import compliance, stt
from app.errors import Problem
from app.stt import registry
from app.stt.base import ProviderInfo


@dataclass
class Provider:
    code: str
    enabled: bool

    def available(self):
        return self.enabled

    def info(self, is_default=False):
        return ProviderInfo(
            self.code,
            self.code,
            self.enabled,
            is_default=is_default,
            offline=self.code == "vosk",
            external_service=self.code == "browser",
        )


@pytest.fixture
def selection(monkeypatch):
    providers = {"vosk": Provider("vosk", False), "browser": Provider("browser", True)}
    settings = SimpleNamespace(stt_provider="none")
    monkeypatch.setattr(registry, "get_settings", lambda: settings)
    monkeypatch.setattr(registry, "providers", lambda: providers)
    return settings, providers


@pytest.mark.parametrize(
    "configured,local,expected",
    [
        ("none", False, None),
        ("none", True, "vosk"),
        ("vosk", False, None),
        ("vosk", True, "vosk"),
        ("browser", False, "browser"),
        ("browser", True, "browser"),
    ],
)
def test_only_offline_vosk_is_automatic(selection, configured, local, expected):
    settings, providers = selection
    settings.stt_provider = configured
    providers["vosk"].enabled = local
    assert registry.default_code() == expected
    assert [info.code for info in registry.list_info() if info.is_default] == ([] if expected is None else [expected])


def test_explicit_api_browser_opt_in_remains_available(selection):
    assert registry.default_code() is None
    assert registry.get("browser").code == "browser"
    with pytest.raises(LookupError):
        registry.get(None)


@pytest.mark.asyncio
async def test_no_selected_provider_rejected_before_pcm_or_file_io(selection, monkeypatch):
    request = SimpleNamespace(body=AsyncMock(side_effect=AssertionError("PCM must not be read")))
    monkeypatch.setattr(stt, "_sample_path", lambda: pytest.fail("Sample must not be opened"))
    with pytest.raises(Problem) as test_error:
        await stt.post_stt_test(stt.TestBody())
    assert test_error.value.status == 422
    with pytest.raises(Problem) as transcribe_error:
        await stt.post_stt_transcribe(request)
    assert transcribe_error.value.status == 422
    request.body.assert_not_called()


@pytest.mark.asyncio
async def test_no_selected_provider_rejected_before_compliance_writes(selection, monkeypatch):
    monkeypatch.setattr(compliance, "db", lambda: pytest.fail("No session may be written"))
    for create, body in [
        (compliance._start_mic_session, {"employee_id": 1}),
        (compliance._start_file_session, {"employee_id": 1, "demo_asset_id": 1, "diarization_mode": "manual"}),
    ]:
        with pytest.raises(HTTPException) as error:
            await create(None, body)
        assert error.value.status_code == 422


@pytest.mark.asyncio
async def test_http_default_is_closed_but_explicit_browser_remains_opt_in(selection, monkeypatch):
    from fastapi import FastAPI
    from httpx import ASGITransport, AsyncClient

    from app.errors import install_error_handlers

    monkeypatch.setattr(stt, "_sample_path", lambda: pytest.fail("Тестовое аудио не должно открываться"))
    app = FastAPI()
    install_error_handlers(app)
    app.include_router(stt.router)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        providers = (await client.get("/api/stt/providers")).json()
        assert not any(provider["is_default"] for provider in providers)
        assert next(provider for provider in providers if provider["code"] == "browser")["available"]
        for path, body in [("/api/stt/test", {}), ("/api/stt/transcribe", None)]:
            response = await client.post(path, json=body)
            assert response.status_code == 422
            assert response.headers["content-type"] == "application/problem+json"
            assert response.json()["instance"] == path
        explicit = await client.post("/api/stt/test", json={"provider": "browser"})
        assert explicit.status_code == 200
        assert explicit.json()["provider"] == "browser"
        assert explicit.json()["text"] is None
