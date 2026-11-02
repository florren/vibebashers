from types import SimpleNamespace

from starlette.requests import Request

from app.api.health import get_health
from app.config import get_settings


async def test_disabled_flag_preserves_token_without_claiming_bot_running(monkeypatch):
    settings = get_settings()
    monkeypatch.setattr(settings, "tgbot_enabled", False)
    token = "123456:" + "A" * 35
    monkeypatch.setattr(settings, "telegram_bot_token", token)

    class Result:
        def scalar_one_or_none(self):
            return False

        def all(self):
            return []

    class Session:
        async def execute(self, statement):
            return Result()

    request = Request({"type": "http", "app": SimpleNamespace(state=SimpleNamespace(llm_chain=None))})
    result = await get_health(request, Session())
    assert result["db"] is True and result["tgbot"] == "disabled"
    assert settings.telegram_bot_token == token and token not in str(result)
