"""Роутер тега `setup` (T-009/T-010): мастер первичной настройки — статус шагов, сводный payload, проверка LLM и Telegram-бота, генерация данных."""

from __future__ import annotations

import asyncio
import datetime as dt
import json
import os
import re
import sys
import time
import uuid
from pathlib import Path
from typing import Any, Literal

import httpx
from fastapi import APIRouter, Request, Response
from psycopg.types.json import Jsonb
from pydantic import BaseModel, Field

from app.api.common import db, fetch_one
from app.api.settings import (
    EconomicsSettings,
    _economics,
    _put_economics,
    get_setting,
    key_plain,
    load_keys,
    set_setting,
)
from app.config import get_settings
from app.errors import Problem
from app.llm.base import LLMProfile, Message
from app.llm.openai_compat import OpenAICompatProvider, suggest_replacement
from app.logging import get_logger

router = APIRouter(tags=["setup"])
log = get_logger(__name__)

STEPS = 9
ANSI_RE = re.compile(r"\x1b\[[0-9;]*m")
SECTION_STEP = {
    "llm": 1,
    "bank": 2,
    "sim": 3,
    "channels": 4,
    "policies": 5,
    "sla": 6,
    "economics": 7,
    "templates": 8,
    "generate": 9,
}
DEFAULT_PAYLOAD: dict[str, Any] = {
    "llm": {"main_profile_id": None, "fast_profile_id": None, "twin_profile_id": None},
    "bank": {
        "name": "Банк «Синапс»",
        "clients_profile": "demo",
        "regions_mode": "all",
        "region_codes": [],
        "segment_shares": {},
    },
    "sim": {
        "sim_hour_real_minutes": 0.5,
        "seed": 42,
        "intensities": {"op": 450.0, "fault": 1.0, "client_error": 30.0, "signal_noise": 6.0},
        "fault_rate": 1.0,
    },
    "channels": {
        "enabled": ["chat", "call", "email", "telegram", "social", "branch", "review_portal"],
        "mailpit": True,
        "tgbot_enabled": False,
    },
    "policies": {"confidence_threshold": 0.75, "hitl_rules": {}, "dedup_window_hours": 4},
    "ui": {"lang": "ru", "theme": "light"},
}


async def _state(conn: Any) -> dict[str, Any]:
    st = await get_setting(conn, "setup_state", {}) or {}
    done = sorted({int(x) for x in st.get("steps_done", []) if 1 <= int(x) <= STEPS})
    completed = bool(await get_setting(conn, "setup_completed", False))
    nxt = next((i for i in range(1, STEPS + 1) if i not in done), STEPS)
    return {"completed": completed, "current_step": int(st.get("current_step") or nxt), "steps_done": done}


async def _mark(conn: Any, step: int) -> None:
    st = await _state(conn)
    done = sorted(set(st["steps_done"]) | {step})
    nxt = next((i for i in range(1, STEPS + 1) if i not in done), STEPS)
    await set_setting(conn, "setup_state", {"current_step": nxt, "steps_done": done})


@router.get("/api/setup/status", summary="Статус мастера: завершён ли, текущий шаг, выполненные шаги")
async def get_setup_status() -> Any:
    async with db() as conn:
        return await _state(conn)


async def _payload(conn: Any) -> dict[str, Any]:
    saved = await get_setting(conn, "setup_payload", {}) or {}
    out = {k: {**v, **(saved.get(k) or {})} for k, v in DEFAULT_PAYLOAD.items()}
    pol = await get_setting(conn, "policies", {}) or {}
    out["policies"] = {
        "confidence_threshold": float(pol.get("confidence_threshold", out["policies"]["confidence_threshold"])),
        "dedup_window_hours": int(pol.get("dedup_window_sim_hours", out["policies"]["dedup_window_hours"])),
        "hitl_rules": {k: v for k, v in pol.items() if k not in ("confidence_threshold", "dedup_window_sim_hours")},
    }
    sim = await fetch_one(conn, "select seed, intensities, speed from sim_state where id = 1")
    if sim:
        out["sim"]["seed"] = int(sim["seed"] or out["sim"]["seed"])
        out["sim"]["intensities"] = {**out["sim"]["intensities"], **dict(sim["intensities"] or {})}
        out["sim"]["fault_rate"] = float(out["sim"]["intensities"].get("fault", 1.0))
    econ = await _economics(conn)
    econ.pop("rates", None)
    econ.pop("updated_at", None)
    out["economics"] = econ
    return out


@router.put("/api/setup", summary="Сохранить разделы мастера (частично); отмечает соответствующие шаги выполненными")
async def put_setup(body: dict[str, Any]) -> Any:
    async with db() as conn:
        saved = await get_setting(conn, "setup_payload", {}) or {}
        for section, val in body.items():
            if section not in SECTION_STEP or not isinstance(val, dict):
                continue
            if section == "economics":
                await _put_economics(conn, EconomicsSettings(**val))
            elif section == "policies":
                pol = await get_setting(conn, "policies", {}) or {}
                if "confidence_threshold" in val:
                    pol["confidence_threshold"] = float(val["confidence_threshold"])
                if "dedup_window_hours" in val:
                    pol["dedup_window_sim_hours"] = int(val["dedup_window_hours"])
                pol.update({k: v for k, v in (val.get("hitl_rules") or {}).items()})
                await set_setting(conn, "policies", pol)
            else:
                saved[section] = {**(saved.get(section) or {}), **val}
                if section == "sim":
                    running = await fetch_one(conn, "select running from sim_state where id = 1")
                    if running and running["running"]:
                        raise Problem(409, "Остановите эмуляцию, чтобы менять seed и интенсивности")
                    inten = {**(val.get("intensities") or {})}
                    if "fault_rate" in val:
                        inten["fault"] = float(val["fault_rate"])
                    if inten:
                        await conn.execute(
                            "update sim_state set intensities = coalesce(intensities, '{}'::jsonb) || %s::jsonb where id = 1",
                            (json.dumps(inten),),
                        )
                    if "seed" in val:
                        await conn.execute("update sim_state set seed = %s where id = 1", (int(val["seed"]),))
                if section == "llm":
                    for role, key in (
                        ("main", "main_profile_id"),
                        ("fast", "fast_profile_id"),
                        ("twin", "twin_profile_id"),
                    ):
                        pid = val.get(key)
                        if pid:
                            await conn.execute(
                                "update llm_profiles set role = %s, is_active = true where id = %s", (role, int(pid))
                            )
            await _mark(conn, SECTION_STEP[section])
        await set_setting(conn, "setup_payload", saved)
        return await _payload(conn)


@router.get("/api/setup", include_in_schema=False)
async def get_setup() -> Any:
    async with db() as conn:
        return await _payload(conn)


@router.post("/api/setup", status_code=204, summary="Завершить мастер (setup_completed = true)")
async def post_setup() -> Response:
    async with db() as conn:
        await set_setting(conn, "setup_completed", True)
        await set_setting(conn, "setup_state", {"current_step": STEPS, "steps_done": list(range(1, STEPS + 1))})
    return Response(status_code=204)


# ---- test LLM --------------------------------------------------------------
class TestLlmBody(BaseModel):
    provider: Literal["gigachat", "openai_compatible", "mock"]
    model: str
    base_url: str | None = None
    api_key: str | None = None
    api_key_id: int | None = None


PING_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {"ok": {"type": "boolean"}, "model": {"type": "string"}},
    "required": ["ok"],
}


async def _deactivate_openrouter_model(model: str, suggested: str | None) -> None:
    """Профиль с этим model: is_active=false и extra.suggested_model. Повторно не включаем."""
    async with db() as conn:
        await conn.execute(
            "update llm_profiles set is_active = false, extra = coalesce(extra, '{}'::jsonb) || %s "
            "where provider = 'openai_compatible' and model = %s",
            (Jsonb({"suggested_model": suggested}), model),
        )


@router.post("/api/setup/test-llm", summary="Проверить подключение к LLM-профилю (кнопка «Проверить подключение»)")
async def post_setup_test_llm(body: TestLlmBody) -> Any:
    s = get_settings()
    key = body.api_key
    async with db() as conn:
        if not key and body.api_key_id:
            item = next((k for k in await load_keys(conn) if int(k["id"]) == body.api_key_id), None)
            if not item:
                raise Problem(404, "Ключ не найден")
            key = key_plain(item)
        if not key and body.provider != "mock":
            stored = [k for k in await load_keys(conn) if k["provider"] == body.provider and k.get("is_active", True)]
            if stored:
                key = key_plain(stored[0])
    if not key and body.provider == "gigachat":
        key = s.gigachat_auth_key_1 or s.gigachat_auth_key_2
    if not key and body.provider == "openai_compatible":
        key = s.openrouter_api_key
    profile = LLMProfile(code="setup_test", provider=body.provider, model=body.model, base_url=body.base_url)
    msgs: list[Message] = [
        {"role": "system", "content": "Ответь JSON по схеме. Поле ok = true, model = твоё имя модели."},
        {"role": "user", "content": "ping"},
    ]
    t0 = time.perf_counter()
    quota: dict[str, Any] = {}
    prov: Any = None
    try:
        if body.provider == "mock":
            from app.llm.mock import MockProvider

            obj, _usage, _raw = await MockProvider().complete_structured(msgs, PING_SCHEMA, profile, timeout_s=5)
            return {
                "ok": True,
                "latency_ms": int((time.perf_counter() - t0) * 1000),
                "model_reported": "mock-rules-v1",
                "supports_tools": True,
                "supports_stream": True,
                "quota": {},
            }
        if not key:
            return {
                "ok": False,
                "latency_ms": 0,
                "error": "Нет API-ключа: передайте api_key, сохраните ключ в /api/settings/llm-keys или задайте .env",
            }
        if body.provider == "gigachat":
            from app.llm.gigachat import GigaChatProvider
            from app.llm.keys import ApiKey, KeyPool

            prov = GigaChatProvider(
                KeyPool([ApiKey(label="setup_test", secret=key, provider="gigachat")]),
                oauth_url=s.gigachat_oauth_url,
                base_url=body.base_url or s.gigachat_base_url,
                scope=s.gigachat_scope,
                verify_ssl=s.gigachat_verify_ssl,
            )
        else:
            base = (body.base_url or s.openrouter_base_url).rstrip("/")
            prov = OpenAICompatProvider(
                key,
                base,
                budget_usd=s.openrouter_budget_usd,
                http_referer=f"http://localhost:{s.app_port}",
            )
            if "openrouter.ai" in base:
                try:
                    info = await prov.fetch_key()
                except Exception as exc:
                    log.warning("setup_openrouter_key_failed", error=str(exc)[:200])
                    info = None
                if info is not None:
                    quota = {
                        "limit": info.get("limit"),
                        "usage": info.get("usage"),
                        "limit_remaining": info.get("limit_remaining"),
                        "is_free_tier": info.get("is_free_tier"),
                    }
                try:
                    available: list[str] | None = await prov.list_models()
                except Exception as exc:
                    log.warning("setup_openrouter_models_failed", error=str(exc)[:200])
                    available = None
                if available is not None and body.model not in available:
                    suggested = suggest_replacement(available)
                    await _deactivate_openrouter_model(body.model, suggested)
                    return {
                        "ok": False,
                        "latency_ms": int((time.perf_counter() - t0) * 1000),
                        "error": (f"Модель {body.model} недоступна на OpenRouter. Предлагаемая замена: {suggested}."),
                        "quota": {**quota, "model": body.model, "suggested_model": suggested},
                    }
        obj, usage, raw = await asyncio.wait_for(
            prov.complete_structured(msgs, PING_SCHEMA, profile, timeout_s=25), timeout=30
        )
        return {
            "ok": True,
            "latency_ms": int((time.perf_counter() - t0) * 1000),
            "model_reported": str(obj.get("model") or body.model),
            "supports_tools": body.provider != "gigachat" or "Lite" not in body.model,
            "supports_stream": True,
            "quota": {**quota, "tokens": usage.total_tokens},
        }
    except Exception as exc:  # noqa: BLE001 — любая ошибка провайдера показывается пользователю
        log.warning("setup_test_llm_failed", provider=body.provider, error=str(exc)[:300])
        return {
            "ok": False,
            "latency_ms": int((time.perf_counter() - t0) * 1000),
            "error": str(exc)[:500],
            "quota": quota,
        }
    finally:
        if isinstance(prov, OpenAICompatProvider):
            await prov.aclose()


class TgBody(BaseModel):
    token: str | None = Field(None, description="Пусто — берётся TELEGRAM_BOT_TOKEN из .env")


@router.post("/api/setup/test-tgbot", summary="Проверить токен Telegram-бота (getMe)")
async def post_setup_test_tgbot(body: TgBody) -> Any:
    token = (body.token or "").strip() or (get_settings().telegram_bot_token or "")
    if not token:
        return {"ok": False, "error": "Токен не задан: введите его или запишите TELEGRAM_BOT_TOKEN в .env"}
    try:
        async with httpx.AsyncClient(timeout=8) as cl:
            r = await cl.get(f"https://api.telegram.org/bot{token}/getMe")
        d = r.json()
        if r.status_code == 200 and d.get("ok"):
            return {"ok": True, "username": d["result"].get("username")}
        return {"ok": False, "error": str(d.get("description") or f"HTTP {r.status_code}")}
    except Exception as exc:  # noqa: BLE001
        return {"ok": False, "error": str(exc)[:300]}


# ---- data generation job ---------------------------------------------------
class GenerateBody(BaseModel):
    profile: Literal["lite", "demo", "stress"] = "demo"
    seed: int = 42
    reset_history: bool = False
    clients: int | None = Field(None, ge=10, le=200_000)


def _job(request: Request) -> dict[str, Any]:
    job = getattr(request.app.state, "setup_job", None)
    if job is None:
        job = {"job_id": None, "status": "idle", "progress": 0.0, "log": [], "coverage": None, "task": None}
        request.app.state.setup_job = job
    return job


async def _run_generate(job: dict[str, Any], body: GenerateBody) -> None:
    root = Path(__file__).resolve().parents[3]
    args = [
        sys.executable,
        str(root / "scripts" / "seed" / "run.py"),
        "--profile",
        body.profile,
        "--seed",
        str(body.seed),
    ]
    if body.reset_history:
        args.append("--reset-history")
    if body.clients:
        args += ["--clients", str(body.clients)]
    env = {**os.environ, "DATABASE_URL": get_settings().database_url, "PYTHONPATH": str(root)}
    job["log"].append(f"$ {' '.join(a for a in args[1:])}")
    stages = ("refs", "clients_done", "operations", "signals", "coverage", "seed_done")
    try:
        proc = await asyncio.create_subprocess_exec(
            *args, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.STDOUT, env=env, cwd=str(root)
        )
        assert proc.stdout is not None
        while True:
            line = await proc.stdout.readline()
            if not line:
                break
            text = ANSI_RE.sub("", line.decode(errors="replace")).rstrip()
            if text:
                job["log"].append(text[:400])
                job["log"] = job["log"][-200:]
                for i, st in enumerate(stages):
                    if st in text:
                        job["progress"] = max(job["progress"], (i + 1) / (len(stages) + 1))
        rc = await proc.wait()
        async with db() as conn:
            job["coverage"] = await get_setting(conn, "coverage")
            if rc == 0:
                await _mark(conn, 9)
        job["status"] = "done" if rc == 0 else "failed"
        job["progress"] = 1.0
        job["log"].append(f"exit code {rc}")
    except Exception as exc:  # noqa: BLE001
        job["status"] = "failed"
        job["log"].append(f"ошибка: {exc}")
    finally:
        job["finished_at"] = dt.datetime.now(dt.UTC).isoformat()


@router.post(
    "/api/setup/generate", status_code=202, summary="Запустить генерацию данных (профиль lite/demo/stress, seed)"
)
async def post_setup_generate(request: Request, body: GenerateBody) -> Any:
    job = _job(request)
    if job["status"] == "running":
        raise Problem(409, "Генерация уже идёт")
    async with db() as conn:
        running = await fetch_one(conn, "select running from sim_state where id = 1")
        if running and running["running"]:
            raise Problem(409, "Остановите эмуляцию перед генерацией данных")
    job.update(
        {
            "job_id": uuid.uuid4().hex[:12],
            "status": "running",
            "progress": 0.02,
            "log": [],
            "coverage": None,
            "started_at": dt.datetime.now(dt.UTC).isoformat(),
        }
    )
    job["task"] = asyncio.create_task(_run_generate(job, body))
    return {"job_id": job["job_id"]}


@router.get("/api/setup/generate", summary="Статус генерации: прогресс, лог, матрица покрытия")
async def get_setup_generate(request: Request) -> Any:
    job = _job(request)
    cov = job.get("coverage")
    if cov is None and job["status"] != "running":
        async with db() as conn:
            cov = await get_setting(conn, "coverage")
    return {k: v for k, v in {**job, "coverage": cov}.items() if k != "task"}
