"""Редактор `.env` для мастера настройки (T-009): чтение с маскированием секретов, запись в файл на месте (bind-mount в Docker),
горячее применение — переменные процесса, кэш Settings, цепочка LLM агента."""

from __future__ import annotations

import os
import re
from pathlib import Path
from typing import Any

import structlog
from fastapi import APIRouter, Request
from pydantic import BaseModel, Field

from app.config import Settings, get_settings
from app.errors import Problem

log = structlog.get_logger()
router = APIRouter(tags=["settings"])

# key → (описание, секрет, нужен ли перезапуск процесса)
ENV_SPEC: dict[str, tuple[str, bool, bool]] = {
    "APP_LANG": ("Язык интерфейса уведомлений (ru | en)", False, False),
    "PROFILE": ("Профиль клиентской базы: lite | demo | stress (нужен перезапуск и генерация)", False, True),
    "SIM_SEED": ("Seed генератора эмуляции", False, True),
    "LLM_PROVIDER": ("Основной провайдер по умолчанию: gigachat | openai_compat | replay | mock", False, False),
    "LLM_CHAIN": ("Порядок failover через запятую: gigachat,openai_compat,replay,mock", False, False),
    "LLM_RECORD": ("true — записывать кассеты replay", False, False),
    "GIGACHAT_AUTH_KEY_1": ("Authorization key GigaChat (основной)", True, False),
    "GIGACHAT_AUTH_KEY_2": ("Authorization key GigaChat (резервный, ротация)", True, False),
    "GIGACHAT_SCOPE": ("GIGACHAT_API_PERS | GIGACHAT_API_B2B | GIGACHAT_API_CORP", False, False),
    "GIGACHAT_MODEL": ("Модель GigaChat по умолчанию", False, False),
    "GIGACHAT_CA_BUNDLE_FILE": ("Путь к PEM bundle (пусто — встроенная цепочка НУЦ)", False, False),
    "GIGACHAT_VERIFY_SSL": ("Проверять сертификат (true — нужен CA Минцифры)", False, False),
    "OPENROUTER_API_KEY": ("Ключ OpenRouter / OpenAI-совместимого API", True, False),
    "OPENROUTER_BASE_URL": ("Базовый URL OpenAI-совместимого API", False, False),
    "LOCAL_LLM_BASE_URL": (
        "Локальная модель (Ollama / vLLM / LM Studio), например http://host.docker.internal:11434/v1",
        False,
        False,
    ),
    "CASSETTES_DIR": ("Каталог кассет replay", False, False),
    "TELEGRAM_BOT_TOKEN": ("Токен Telegram-бота", True, False),
    "MAILPIT_ENABLED": ("Отправлять e-mail в Mailpit (true | false)", False, False),
    "STT_PROVIDER": ("Распознавание речи: vosk | browser | none", False, False),
    "STT_MODEL_PATH": ("Каталог модели Vosk", False, False),
    "COMPLIANCE_ALERT_THRESHOLD": ("Срабатываний мисселинга за встречу до алерта", False, False),
    "LOG_JSONL": ("Писать JSONL-журнал (true | false)", False, False),
    "LOG_JSONL_LEVEL": ("debug | info | warning", False, False),
}
_LINE = re.compile(r"^\s*(?:export\s+)?([A-Z][A-Z0-9_]*)\s*=\s*(.*?)\s*$")


def env_path(settings: Settings | None = None) -> Path:
    s = settings or get_settings()
    if s.env_file:
        return Path(s.env_file)
    for cand in (Path(".env"), Path("../.env")):
        if cand.exists():
            return cand.resolve()
    return (Path("../.env") if Path("../docker-compose.yml").exists() else Path(".env")).resolve()


def _strip_value(raw: str) -> str:
    v = raw.strip()
    if v[:1] in ("'", '"') and v.endswith(v[0]) and len(v) >= 2:
        return v[1:-1]
    # отрезаем inline-комментарий «  # ...»
    return re.split(r"\s+#", v, maxsplit=1)[0].strip()


def read_env_file(path: Path) -> dict[str, str]:
    out: dict[str, str] = {}
    if not path.exists():
        return out
    for line in path.read_text(encoding="utf-8").splitlines():
        m = _LINE.match(line)
        if m and not line.lstrip().startswith("#"):
            out[m.group(1)] = _strip_value(m.group(2))
    return out


def _hint(v: str) -> str:
    return ("…" + v[-4:]) if len(v) > 8 else "••••"


def _quote(v: str) -> str:
    return v if re.fullmatch(r"[A-Za-z0-9_./:,+\-@=]*", v) else '"' + v.replace('"', '\\"') + '"'


def write_env_file(path: Path, updates: dict[str, str | None]) -> None:
    """Правит файл на месте: сохраняет порядок и комментарии, заменяет значения, добавляет новые ключи в конец, None — очищает (KEY=)."""
    lines = (
        path.read_text(encoding="utf-8").splitlines()
        if path.exists()
        else ["# CX Pulse Control — .env (создан мастером настройки)"]
    )
    seen: set[str] = set()
    out: list[str] = []
    for line in lines:
        m = _LINE.match(line)
        key = m.group(1) if m and not line.lstrip().startswith("#") else None
        if key in updates and key not in seen:
            seen.add(key)
            val = updates[key]
            comment = ""
            cm = re.search(r"\s+(#.*)$", m.group(2)) if m else None
            if cm and not (m and m.group(2).strip()[:1] in ("'", '"')):
                comment = " " * max(1, 33 - len(key) - 1 - len(_quote(val or ""))) + cm.group(1)
            out.append(f"{key}={_quote(val or '')}{comment}")
        else:
            out.append(line)
    for key, val in updates.items():
        if key not in seen:
            out.append(f"{key}={_quote(val or '')}")
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as fh:  # перезапись на месте — bind-mount файла в Docker остаётся валидным
        fh.write("\n".join(out) + "\n")


class EnvVar(BaseModel):
    key: str
    value: str | None = Field(None, description="Значение (у секретов — null)")
    hint: str | None = Field(None, description="Хвост секрета, если задан")
    is_secret: bool
    is_set: bool
    source: str = Field(description="file | process | default")
    requires_restart: bool
    description: str


class EnvUpdate(BaseModel):
    values: dict[str, str | None] = Field(description="KEY → значение; null или пустая строка очищают ключ")
    apply: bool = Field(True, description="Горячо применить: переменные процесса, кэш настроек, цепочка LLM агента")


class EnvResult(BaseModel):
    path: str
    written: list[str]
    applied: bool
    restart_required: list[str]
    llm_chain: list[str]
    llm_profile: str | None
    warnings: list[str]


def _list(settings: Settings) -> list[EnvVar]:
    path = env_path(settings)
    in_file = read_env_file(path)
    out: list[EnvVar] = []
    for key, (desc, secret, restart) in ENV_SPEC.items():
        file_v = in_file.get(key)
        proc_v = os.environ.get(key)
        if file_v is not None:
            v, src = file_v, "file"
        elif proc_v is not None:
            v, src = proc_v, "process"
        else:
            attr = key.lower()
            d = getattr(settings, attr, None)
            v, src = ("" if d is None else str(d).lower() if isinstance(d, bool) else str(d)), "default"
        is_set = bool(v)
        out.append(
            EnvVar(
                key=key,
                value=None if secret else v,
                hint=_hint(v) if (secret and is_set) else None,
                is_secret=secret,
                is_set=is_set,
                source=src,
                requires_restart=restart,
                description=desc,
            )
        )
    return out


@router.get("/api/settings/env", summary="Переменные .env (секреты маскируются), путь файла")
async def get_env() -> dict[str, Any]:
    s = get_settings()
    path = env_path(s)
    chain = None
    return {
        "path": str(path),
        "exists": path.exists(),
        "writable": os.access(path if path.exists() else path.parent, os.W_OK),
        "items": [x.model_dump() for x in _list(s)],
        "llm_chain": chain,
    }


async def apply_runtime(app: Any, updates: dict[str, str | None]) -> tuple[Settings, list[str], str | None, list[str]]:
    """Переменные процесса → сброс кэша Settings → новая цепочка LLM и профиль → подмена в приложении и агенте."""
    from app.llm.failover import build_chain, default_profile
    from app.llm.gigachat import GigaChatProvider

    previous_chain = getattr(app.state, "llm_chain", None)
    for k, v in updates.items():
        if v:
            os.environ[k] = v
        else:
            os.environ.pop(k, None)
    get_settings.cache_clear()
    s = get_settings()
    warnings: list[str] = []
    chain: Any
    profile: Any
    try:
        chain = build_chain(s)
        profile = default_profile(s)
    except Exception as exc:  # цепочка не собралась — старая остаётся
        warnings.append(f"цепочка LLM не пересобрана: {str(exc)[:160]}")
        chain = getattr(app.state, "llm_chain", None)
        profile = getattr(app.state, "llm_profile", None)
    if chain is not None:
        app.state.llm_chain = chain
        app.state.llm_profile = profile
        agent = getattr(app.state, "agent", None)
        if agent is not None:
            agent.chain, agent.profile = chain, profile
    from app.llm.roles import refresh

    await refresh(app, s)
    if chain is not previous_chain:
        for provider in getattr(previous_chain, "providers", []):
            if isinstance(provider, GigaChatProvider):
                await provider.stop_auth_refresh()
        if not s.is_test:
            for provider in getattr(chain, "providers", []):
                if isinstance(provider, GigaChatProvider):
                    await provider.prepare(list(chain.role_profiles.values()))
    profile = app.state.llm_profile
    names = list(getattr(chain, "names", []) or [])
    if names == ["mock"] and any(k in updates for k in ("GIGACHAT_AUTH_KEY_1", "OPENROUTER_API_KEY", "LLM_CHAIN")):
        warnings.append("в цепочке остался только mock: проверьте ключи и LLM_CHAIN")
    return s, names, getattr(profile, "code", None), warnings


@router.put("/api/settings/env", summary="Записать переменные в .env и применить без перезапуска (LLM, каналы, STT)")
async def put_env(body: EnvUpdate, request: Request) -> EnvResult:
    unknown = [k for k in body.values if k not in ENV_SPEC]
    if unknown:
        raise Problem(
            422, "Недопустимые ключи", detail=f"Разрешены только {', '.join(ENV_SPEC)}; получены {', '.join(unknown)}"
        )
    s = get_settings()
    path = env_path(s)
    current = read_env_file(path)
    updates: dict[str, str | None] = {}
    for k, v in body.values.items():
        v = (v or "").strip() or None
        secret = ENV_SPEC[k][1]
        if secret and v and v == _hint(current.get(k) or os.environ.get(k) or ""):
            continue  # прислали маску — не трогаем
        if k == "LLM_CHAIN" and v:
            bad = [
                x
                for x in v.split(",")
                if x.strip() not in ("gigachat", "openai_compat", "openai_compatible", "openrouter", "replay", "mock")
            ]
            if bad:
                raise Problem(422, "LLM_CHAIN: неизвестные провайдеры", detail=", ".join(bad))
        if k == "LLM_PROVIDER" and v and v not in ("gigachat", "openai_compat", "openai_compatible", "replay", "mock"):
            raise Problem(422, "LLM_PROVIDER: допустимы gigachat | openai_compat | replay | mock")
        if k == "STT_PROVIDER" and v and v not in ("vosk", "browser", "none"):
            raise Problem(422, "STT_PROVIDER: допустимы vosk | browser | none")
        if k == "GIGACHAT_VERIFY_SSL" and v and v.lower() != "true":
            raise Problem(422, "Проверка TLS GigaChat обязательна; настройте CA bundle")
        if (
            k in ("MAILPIT_ENABLED", "LLM_RECORD", "GIGACHAT_VERIFY_SSL", "LOG_JSONL")
            and v
            and v.lower() not in ("true", "false")
        ):
            raise Problem(422, f"{k}: true | false")
        if k in ("SIM_SEED", "COMPLIANCE_ALERT_THRESHOLD") and v and not v.isdigit():
            raise Problem(422, f"{k}: целое число")
        if k == "GIGACHAT_CA_BUNDLE_FILE":
            from app.llm.tls import context

            try:
                context(v)
            except (OSError, ValueError) as exc:
                raise Problem(422, "Не удалось загрузить CA bundle", detail=type(exc).__name__) from exc
        if current.get(k, "") == (v or "") and k in current:
            continue
        updates[k] = v
    if updates:
        try:
            write_env_file(path, updates)
        except OSError as exc:
            raise Problem(500, "Не удалось записать .env", detail=f"{path}: {exc}") from exc
    applied = False
    names: list[str] = list(getattr(getattr(request.app.state, "llm_chain", None), "names", []) or [])
    profile: str | None = None
    warnings: list[str] = []
    if body.apply and updates:
        _, names, profile, warnings = await apply_runtime(request.app, updates)
        applied = True
    restart = [k for k in updates if ENV_SPEC[k][2]]
    log.info("env_updated", path=str(path), keys=sorted(updates), applied=applied, chain=names)
    return EnvResult(
        path=str(path),
        written=sorted(updates),
        applied=applied,
        restart_required=restart,
        llm_chain=names,
        llm_profile=profile,
        warnings=warnings,
    )
