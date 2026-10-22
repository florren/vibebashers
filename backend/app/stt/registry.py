"""Реестр STT-провайдеров: vosk (по умолчанию при наличии модели), browser; salutespeech / openai_compatible_audio — заявлены как недоступные."""

from __future__ import annotations

from functools import lru_cache
from typing import Any

from app.config import get_settings
from app.stt.base import ProviderInfo
from app.stt.browser import BrowserProvider
from app.stt.vosk_provider import VoskProvider


@lru_cache
def _vosk(model_path: str | None) -> VoskProvider:
    return VoskProvider(model_path)


def providers() -> dict[str, Any]:
    s = get_settings()
    return {"vosk": _vosk(s.stt_model_path), "browser": BrowserProvider()}


def default_code() -> str:
    s = get_settings()
    reg = providers()
    if s.stt_provider in reg and reg[s.stt_provider].available():
        return s.stt_provider
    if reg["vosk"].available():
        return "vosk"
    return "browser"


def list_info() -> list[ProviderInfo]:
    d = default_code()
    out = [p.info(is_default=(code == d)) for code, p in providers().items()]
    out.append(
        ProviderInfo(
            "salutespeech",
            "SaluteSpeech (gRPC, юрлица)",
            False,
            False,
            False,
            True,
            2,
            None,
            True,
            "Нужны учётные данные юрлица; в демо выключен",
        )
    )
    out.append(
        ProviderInfo(
            "openai_compatible_audio",
            "OpenAI-совместимый аудио-сервер",
            False,
            False,
            False,
            False,
            1,
            None,
            True,
            "Псевдо-поток чанками; не для демо",
        )
    )
    return out


def get(code: str | None) -> Any:
    reg = providers()
    c = code or default_code()
    p = reg.get(c)
    if p is None or not p.available():
        raise LookupError(c)
    return p
