"""T-009: редактор .env мастера настройки — чтение с маской, запись на месте с сохранением комментариев, горячее применение цепочки LLM."""

from __future__ import annotations

import os
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.api.envfile import read_env_file, write_env_file
from app.config import get_settings
from app.main import create_app


def test_write_env_file_keeps_comments_and_order(tmp_path: Path) -> None:
    p = tmp_path / ".env"
    p.write_text(
        "# заголовок\nLLM_PROVIDER=mock                # комментарий\nLLM_CHAIN=gigachat,replay,mock\nOPENROUTER_API_KEY=\n",
        encoding="utf-8",
    )
    write_env_file(
        p,
        {"LLM_PROVIDER": "gigachat", "OPENROUTER_API_KEY": "sk-or-abc def", "TELEGRAM_BOT_TOKEN": None, "NEW_KEY": "x"},
    )
    text = p.read_text(encoding="utf-8")
    lines = text.splitlines()
    assert lines[0] == "# заголовок"
    assert lines[1].startswith("LLM_PROVIDER=gigachat") and lines[1].rstrip().endswith("# комментарий")
    assert lines[2] == "LLM_CHAIN=gigachat,replay,mock"
    assert 'OPENROUTER_API_KEY="sk-or-abc def"' in lines[3]
    assert "TELEGRAM_BOT_TOKEN=" in text and "NEW_KEY=x" in text
    vals = read_env_file(p)
    assert (
        vals["LLM_PROVIDER"] == "gigachat"
        and vals["OPENROUTER_API_KEY"] == "sk-or-abc def"
        and vals["TELEGRAM_BOT_TOKEN"] == ""
    )


@pytest.mark.integration
def test_env_api_roundtrip(seeded: str, tmp_path: Path) -> None:
    env_file = tmp_path / ".env"
    env_file.write_text("LLM_PROVIDER=mock\nLLM_CHAIN=mock\n", encoding="utf-8")
    saved = {
        k: os.environ.get(k)
        for k in ("DATABASE_URL", "APP_ENV", "ENV_FILE", "OPENROUTER_API_KEY", "LLM_CHAIN", "TELEGRAM_BOT_TOKEN")
    }
    os.environ.update({"DATABASE_URL": seeded, "APP_ENV": "test", "ENV_FILE": str(env_file)})
    os.environ.pop("OPENROUTER_API_KEY", None)
    get_settings.cache_clear()
    try:
        with TestClient(create_app()) as c:
            st = c.get("/api/settings/env").json()
            assert st["path"] == str(env_file) and st["writable"] is True
            items = {x["key"]: x for x in st["items"]}
            assert items["LLM_CHAIN"]["value"] == "mock" and items["LLM_CHAIN"]["source"] == "file"
            assert (
                items["OPENROUTER_API_KEY"]["is_secret"]
                and items["OPENROUTER_API_KEY"]["value"] is None
                and not items["OPENROUTER_API_KEY"]["is_set"]
            )

            r = c.put(
                "/api/settings/env",
                json={
                    "values": {
                        "OPENROUTER_API_KEY": "sk-or-v1-0123456789abcdef",
                        "LLM_CHAIN": "openai_compat,mock",
                        "TELEGRAM_BOT_TOKEN": "123:abc",
                        "SIM_SEED": "7",
                    }
                },
            )
            assert r.status_code == 200, r.text
            d = r.json()
            assert set(d["written"]) == {"OPENROUTER_API_KEY", "LLM_CHAIN", "TELEGRAM_BOT_TOKEN", "SIM_SEED"}
            assert (
                d["applied"] is True
                and d["llm_chain"] == ["openai_compatible", "mock"]
                and d["restart_required"] == ["SIM_SEED"]
            )
            assert (
                os.environ["OPENROUTER_API_KEY"] == "sk-or-v1-0123456789abcdef"
                and get_settings().telegram_bot_token == "123:abc"
            )

            st = c.get("/api/settings/env").json()
            items = {x["key"]: x for x in st["items"]}
            assert (
                items["OPENROUTER_API_KEY"]["is_set"]
                and items["OPENROUTER_API_KEY"]["hint"] == "…cdef"
                and items["OPENROUTER_API_KEY"]["value"] is None
            )
            # маска вместо значения — не трогаем; то же значение — не пишем
            r = c.put(
                "/api/settings/env", json={"values": {"OPENROUTER_API_KEY": "…cdef", "LLM_CHAIN": "openai_compat,mock"}}
            )
            assert r.status_code == 200 and r.json()["written"] == [] and r.json()["applied"] is False
            assert read_env_file(env_file)["OPENROUTER_API_KEY"] == "sk-or-v1-0123456789abcdef"

            assert c.put("/api/settings/env", json={"values": {"LLM_CHAIN": "foo"}}).status_code == 422
            assert c.put("/api/settings/env", json={"values": {"DATABASE_URL": "x"}}).status_code == 422
            assert c.put("/api/settings/env", json={"values": {"MAILPIT_ENABLED": "yes"}}).status_code == 422

            # очистка ключа → цепочка снова только mock
            r = c.put("/api/settings/env", json={"values": {"OPENROUTER_API_KEY": None}})
            assert r.status_code == 200 and r.json()["llm_chain"] == ["mock"] and "OPENROUTER_API_KEY" not in os.environ
    finally:
        for k, v in saved.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v
        get_settings.cache_clear()
