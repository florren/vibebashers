"""Настройки приложения (переменные окружения, .env). Все секреты — только отсюда."""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from typing import Literal

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict

Profile = Literal["lite", "demo", "stress"]
LlmProvider = Literal["gigachat", "openai_compat", "replay", "mock"]


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=(".env", "../.env"), env_file_encoding="utf-8", extra="ignore")

    app_env: Literal["dev", "test", "prod"] = "dev"
    app_secret: str = "change-me"
    app_lang: Literal["ru", "en"] = "ru"
    app_port: int = 8000
    frontend_dist: str | None = Field(
        default=None, description="Каталог собранного фронта; по умолчанию ../frontend/dist"
    )
    cors_origins: list[str] = Field(default_factory=lambda: ["http://localhost:5173", "http://localhost:8080"])

    database_url: str = "postgresql+psycopg://cx:cx@localhost:5432/cx_pulse"
    database_url_test: str | None = None

    profile: Profile = "lite"
    sim_seed: int = 42

    # LLM
    llm_provider: LlmProvider = "mock"
    llm_chain: str = "gigachat,replay,mock"  # порядок failover; переопределяется профилем из БД
    llm_record: bool = False
    gigachat_auth_key_1: str | None = None
    gigachat_auth_key_2: str | None = None
    gigachat_scope: str = "GIGACHAT_API_PERS"
    gigachat_base_url: str = "https://gigachat.devices.sberbank.ru/api/v1"
    gigachat_oauth_url: str = "https://ngw.devices.sberbank.ru:9443/api/v2/oauth"
    gigachat_model: str = "GigaChat-2-Max"
    gigachat_verify_ssl: bool = (
        False  # сертификат Минцифры; в demo-профиле проверка отключена, в prod — включить и подложить CA
    )
    openrouter_api_key: str | None = None
    openrouter_base_url: str = "https://openrouter.ai/api/v1"
    local_llm_base_url: str | None = None
    cassettes_dir: str = "../data/cassettes"

    # интеграции
    telegram_bot_token: str | None = None
    mailpit_enabled: bool = False
    compliance_alert_threshold: int = 3  # N подтверждённых срабатываний за встречу → алерт руководителю (ДТЗ FR-2.4)
    stt_provider: Literal["vosk", "browser", "none"] = "none"

    # наблюдаемость (docs/REPORTS.md)
    log_dir: str = "var/log"  # относительно backend/; JSONL-журнал app.jsonl, ротация 20 МБ ×3
    log_jsonl: bool = True
    log_jsonl_level: Literal["debug", "info", "warning"] = "info"

    @property
    def log_path(self) -> Path:
        base = Path(self.log_dir)
        if not base.is_absolute():
            base = Path(__file__).resolve().parents[1] / base
        return base / "app.jsonl"

    @property
    def is_test(self) -> bool:
        return self.app_env == "test"


@lru_cache
def get_settings() -> Settings:
    return Settings()
