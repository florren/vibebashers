"""Роутер тега `settings` (T-009/T-010): настройки стенда — таблица `settings` (key → jsonb), матрица SLA, правила маршрутизации, LLM-профили и ключи, шаблоны, подарки, экономика, психотипы, экспорт/импорт."""

from __future__ import annotations

import datetime as dt
from typing import Any, Literal

from fastapi import APIRouter, Request, Response
from psycopg.types.json import Jsonb
from pydantic import BaseModel, Field

from app.api.common import db, fetch_all, fetch_one
from app.config import get_settings
from app.errors import Problem
from app.llm import secrets as sec
from app.llm.openai_compat import OpenAICompatProvider

router = APIRouter(tags=["settings"])

SECRET_KEYS = {"llm_keys"}


async def get_setting(conn: Any, key: str, default: Any = None) -> Any:
    row = await fetch_one(conn, "select value from settings where key = %s", (key,))
    return row["value"] if row else default


async def set_setting(conn: Any, key: str, value: Any) -> None:
    await conn.execute(
        "insert into settings (key, value, updated_at) values (%s, %s, now()) on conflict (key) do update set value = excluded.value, updated_at = now()",
        (key, Jsonb(value)),
    )


def _mask_keys(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [{k: v for k, v in it.items() if k != "key_enc"} for it in items]


# ---- settings map ---------------------------------------------------------
@router.get("/api/settings", summary="Все настройки стенда (ключ → значение)")
async def get_settings_map() -> Any:
    async with db() as conn:
        rows = await fetch_all(conn, "select key, value, updated_at from settings order by key")
    out: dict[str, Any] = {}
    for r in rows:
        out[r["key"]] = _mask_keys(list(r["value"] or [])) if r["key"] in SECRET_KEYS else r["value"]
    return out


@router.patch("/api/settings", summary="Частичное обновление настроек (merge по ключам верхнего уровня)")
async def patch_settings(body: dict[str, Any]) -> Response:
    async with db() as conn:
        for k, v in body.items():
            if k in SECRET_KEYS:
                raise Problem(422, f"Ключ {k} меняется только через /api/settings/llm-keys")
            cur = await get_setting(conn, k)
            await set_setting(conn, k, {**cur, **v} if isinstance(cur, dict) and isinstance(v, dict) else v)
    return Response(status_code=200)


EXPORT_TABLES: dict[str, str] = {
    "sla_matrix": "select complexity, criticality, fix_days, report_days, take_hours from sla_matrix order by complexity, criticality",
    "routing_rules": "select id, priority, match, team_codes, notes_ru from routing_rules order by priority, id",
    "notification_templates": "select id, code, channel_code, segment_code, lang, subject, body, variables from notification_templates order by code, channel_code, segment_code",
    "gift_catalog": "select code, name_ru, name_en, segments, rule, partner_display_name from gift_catalog order by code",
    "psychotypes": "select code, name_ru, name_en, params from psychotypes order by code",
    "segment_psychotype_mix": "select segment_code, psychotype_code, share::float from segment_psychotype_mix order by 1, 2",
    "dcltv_rates": "select code, name_ru, name_en, rate_rub::float, maps_to from dcltv_rates order by code",
    "llm_profiles": "select id, code, provider, model, base_url, role, temperature::float, rpm_limit, rpd_limit, price_in_per_1m::float, price_out_per_1m::float, supports_tools, supports_stream, is_active, extra from llm_profiles order by id",
}


@router.get("/api/settings/export", summary="Экспорт всех настроек одним JSON (без секретов)")
async def get_settings_export() -> Any:
    async with db() as conn:
        out: dict[str, Any] = {
            "exported_at": dt.datetime.now(dt.UTC).isoformat(),
            "version": 1,
            "settings": {
                r["key"]: r["value"]
                for r in await fetch_all(conn, "select key, value from settings")
                if r["key"] not in SECRET_KEYS
            },
        }
        for name, sql in EXPORT_TABLES.items():
            out[name] = await fetch_all(conn, sql)
        out["economics_settings"] = await _economics(conn)
    return out


@router.post("/api/settings/import", summary="Импорт настроек из экспорта (перезаписывает одноимённые разделы)")
async def post_settings_import(body: dict[str, Any]) -> Response:
    async with db() as conn:
        for k, v in (body.get("settings") or {}).items():
            if k not in SECRET_KEYS:
                await set_setting(conn, k, v)
        if body.get("sla_matrix"):
            await _put_sla(conn, [SlaCell(**c) for c in body["sla_matrix"]])
        if body.get("routing_rules") is not None:
            await _put_routing(conn, [RoutingRule(**r) for r in body["routing_rules"]])
        if body.get("notification_templates") is not None:
            await _put_templates(conn, [NotificationTemplate(**r) for r in body["notification_templates"]])
        if body.get("gift_catalog") is not None:
            await _put_gifts(conn, [Gift(**r) for r in body["gift_catalog"]])
        if body.get("economics_settings"):
            await _put_economics(conn, EconomicsSettings(**body["economics_settings"]))
        if body.get("psychotypes") is not None or body.get("segment_psychotype_mix") is not None:
            mix: dict[str, dict[str, float]] = {}
            for r in body.get("segment_psychotype_mix") or []:
                mix.setdefault(r["segment_code"], {})[r["psychotype_code"]] = float(r["share"])
            await _put_psychotypes(
                conn,
                PsychotypeSettings(
                    psychotypes=[Psychotype(**p) for p in body.get("psychotypes") or []], segment_mix=mix or None
                ),
            )
    return Response(status_code=200)


# ---- SLA matrix -----------------------------------------------------------
class SlaCell(BaseModel):
    complexity: Literal["easy", "medium", "hard"]
    criticality: Literal["low", "medium", "high"]
    fix_days: int = Field(ge=1, le=10)
    report_days: list[int] = Field(default_factory=list)
    take_hours: int = Field(ge=0, le=240)


@router.get("/api/settings/sla-matrix", summary="Матрица SLA 3×3 (ТЗ 8.2)")
async def get_sla_matrix() -> Any:
    async with db() as conn:
        return await fetch_all(conn, EXPORT_TABLES["sla_matrix"])


async def _put_sla(conn: Any, cells: list[SlaCell]) -> None:
    keys = {(c.complexity, c.criticality) for c in cells}
    if len(cells) != 9 or len(keys) != 9:
        raise Problem(422, "Нужно ровно 9 уникальных ячеек complexity × criticality")
    for c in cells:
        if any(d > c.fix_days for d in c.report_days):
            raise Problem(422, f"report_days не могут превышать fix_days ({c.complexity}/{c.criticality})")
        await conn.execute(
            "insert into sla_matrix (complexity, criticality, fix_days, report_days, take_hours) values (%s, %s, %s, %s, %s) on conflict (complexity, criticality) do update set fix_days = excluded.fix_days, report_days = excluded.report_days, take_hours = excluded.take_hours",
            (c.complexity, c.criticality, c.fix_days, c.report_days, c.take_hours),
        )


@router.put("/api/settings/sla-matrix", summary="Заменить матрицу SLA (ровно 9 ячеек)")
async def put_sla_matrix(body: list[SlaCell]) -> Response:
    async with db() as conn:
        await _put_sla(conn, body)
    return Response(status_code=200)


# ---- routing rules --------------------------------------------------------
class RoutingRule(BaseModel):
    id: int | None = None
    priority: int = 100
    match: dict[str, Any]
    team_codes: list[str] = Field(min_length=1)
    notes_ru: str | None = None


@router.get("/api/settings/routing-rules", summary="Правила маршрутизации (ТЗ 8.4)")
async def get_routing_rules() -> Any:
    async with db() as conn:
        return await fetch_all(conn, EXPORT_TABLES["routing_rules"])


async def _put_routing(conn: Any, rules: list[RoutingRule]) -> None:
    teams = {r["code"] for r in await fetch_all(conn, "select code from teams")}
    for r in rules:
        bad = set(r.team_codes) - teams
        if bad:
            raise Problem(422, f"Неизвестные команды: {', '.join(sorted(bad))}")
    await conn.execute("delete from routing_rules")
    for r in rules:
        await conn.execute(
            "insert into routing_rules (priority, match, team_codes, notes_ru) values (%s, %s, %s, %s)",
            (r.priority, Jsonb(r.match), r.team_codes, r.notes_ru),
        )


@router.put("/api/settings/routing-rules", summary="Заменить правила маршрутизации")
async def put_routing_rules(body: list[RoutingRule]) -> Response:
    async with db() as conn:
        await _put_routing(conn, body)
    return Response(status_code=200)


# ---- LLM profiles ---------------------------------------------------------
class LlmProfile(BaseModel):
    id: int | None = None
    code: str = Field(min_length=2, max_length=64)
    provider: Literal["gigachat", "openai_compatible", "mock"]
    model: str
    base_url: str | None = None
    role: Literal["main", "fast", "twin", "bench_only"] = "main"
    temperature: float = 0.0
    rpm_limit: int | None = None
    rpd_limit: int | None = None
    price_in_per_1m: float = 0.0
    price_out_per_1m: float = 0.0
    supports_tools: bool = True
    supports_stream: bool = True
    is_active: bool = True
    extra: dict[str, Any] = Field(default_factory=dict)


@router.get("/api/settings/llm-profiles", summary="LLM-профили (main / fast / twin / bench_only)")
async def get_llm_profiles() -> Any:
    async with db() as conn:
        return await fetch_all(conn, EXPORT_TABLES["llm_profiles"])


@router.post("/api/settings/llm-profiles", status_code=201, summary="Добавить LLM-профиль")
async def post_llm_profiles(body: LlmProfile) -> Response:
    async with db() as conn:
        if await fetch_one(conn, "select 1 from llm_profiles where code = %s", (body.code,)):
            raise Problem(409, f"Профиль {body.code} уже есть")
        await conn.execute(
            "insert into llm_profiles (code, provider, model, base_url, role, temperature, rpm_limit, rpd_limit, price_in_per_1m, price_out_per_1m, supports_tools, supports_stream, is_active, extra) values (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)",
            (
                body.code,
                body.provider,
                body.model,
                body.base_url,
                body.role,
                body.temperature,
                body.rpm_limit,
                body.rpd_limit,
                body.price_in_per_1m,
                body.price_out_per_1m,
                body.supports_tools,
                body.supports_stream,
                body.is_active,
                Jsonb(body.extra),
            ),
        )
    return Response(status_code=201)


@router.patch("/api/settings/llm-profiles/{id}", summary="Изменить LLM-профиль")
async def patch_llm_profiles_id(id: int, body: LlmProfile, request: Request) -> Response:  # noqa: A002
    async with db() as conn:
        if not await fetch_one(conn, "select 1 from llm_profiles where id = %s", (id,)):
            raise Problem(404, "Профиль не найден")
        saved = await get_setting(conn, "setup_payload", {}) or {}
        if id in ((saved.get("llm") or {}).values()) and not body.is_active:
            raise Problem(422, "Сначала выберите другой профиль для активной роли")
        await conn.execute(
            "update llm_profiles set code = %s, provider = %s, model = %s, base_url = %s, role = %s, temperature = %s, rpm_limit = %s, rpd_limit = %s, price_in_per_1m = %s, price_out_per_1m = %s, supports_tools = %s, supports_stream = %s, is_active = %s, extra = %s where id = %s",
            (
                body.code,
                body.provider,
                body.model,
                body.base_url,
                body.role,
                body.temperature,
                body.rpm_limit,
                body.rpd_limit,
                body.price_in_per_1m,
                body.price_out_per_1m,
                body.supports_tools,
                body.supports_stream,
                body.is_active,
                Jsonb(body.extra),
                id,
            ),
        )
    from app.llm.roles import refresh

    await refresh(request.app, required=True)
    return Response(status_code=200)


@router.delete(
    "/api/settings/llm-profiles/{id}", status_code=204, summary="Удалить LLM-профиль (если на него нет запусков)"
)
async def delete_llm_profiles_id(id: int, request: Request) -> Response:  # noqa: A002
    async with db() as conn:
        saved = await get_setting(conn, "setup_payload", {}) or {}
        if id in ((saved.get("llm") or {}).values()):
            raise Problem(422, "Сначала выберите другой профиль для активной роли")
        used = await fetch_one(conn, "select count(*) as n from agent_runs where llm_profile_id = %s", (id,))
        if int((used or {}).get("n") or 0):
            raise Problem(409, "На профиль ссылаются запуски агента — деактивируйте его вместо удаления")
        await conn.execute("delete from llm_profiles where id = %s", (id,))
    from app.llm.roles import refresh

    await refresh(request.app, required=True)
    return Response(status_code=204)


# ---- LLM keys (settings.llm_keys, зашифрованы) ---------------------------
class LlmKeyBody(BaseModel):
    provider: Literal["gigachat", "openai_compatible", "mock"]
    label: str = Field(min_length=1, max_length=80)
    key: str = Field(min_length=4)
    tokens_limit: int | None = None
    rpd_limit: int | None = None


async def load_keys(conn: Any) -> list[dict[str, Any]]:
    return list(await get_setting(conn, "llm_keys", []) or [])


def key_plain(item: dict[str, Any]) -> str:
    return sec.decrypt(str(item["key_enc"]), get_settings().app_secret)


def _chain_has_openai(chain: str) -> bool:
    names = {part.strip() for part in chain.split(",") if part.strip()}
    return bool(names & {"openai_compat", "openai_compatible", "openrouter"})


async def _refresh_openai_balances(items: list[dict[str, Any]]) -> bool:
    """balance_usd и rpd_limit из GET /key. Ошибка оставляет сохранённые числа и пишет last_error."""
    s = get_settings()
    if s.is_test or not _chain_has_openai(s.llm_chain):
        return False
    changed = False
    for item in items:
        if item.get("provider") != "openai_compatible" or not item.get("key_enc"):
            continue
        try:
            secret = key_plain(item)
        except Exception as exc:
            item["last_error"] = str(exc)[:300]
            changed = True
            continue
        prov = OpenAICompatProvider(
            secret,
            s.openrouter_base_url,
            budget_usd=s.openrouter_budget_usd,
            http_referer=f"http://localhost:{s.app_port}",
        )
        try:
            info = await prov.fetch_key()
        except Exception as exc:
            item["last_error"] = str(exc)[:300]
            changed = True
        else:
            item["balance_usd"] = info.get("balance_usd")
            item["rpd_limit"] = info.get("rpd_limit")
            item["last_error"] = None
            changed = True
        finally:
            await prov.aclose()
    return changed


def public_openrouter_env_key(
    items: list[dict[str, Any]],
    info: dict[str, Any] | None,
    *,
    key_hint: str,
    last_error: str | None,
) -> list[dict[str, Any]]:
    """Карточка OPENROUTER_API_KEY без секрета. Тот же key_hint у openai_compatible — без второго элемента."""
    if any(item.get("provider") == "openai_compatible" and item.get("key_hint") == key_hint for item in items):
        return list(items)
    used = {int(item["id"]) for item in items if item.get("id") is not None}
    # Отрицательный id не записывается в settings.llm_keys, поэтому DELETE остаётся 404.
    synthetic = -1
    while synthetic in used:
        synthetic -= 1
    public: dict[str, Any] = {
        "id": synthetic,
        "provider": "openai_compatible",
        "label": "openrouter_env",
        "tokens_used": 0,
        "tokens_limit": None,
        "requests_today": 0,
        "rpd_limit": None if info is None else info.get("rpd_limit"),
        "balance_usd": None if info is None else info.get("balance_usd"),
        "is_active": True,
        "last_error": last_error,
    }
    return [*items, public]


async def _with_openrouter_env_key(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Дописывает ключ из .env в ответ. GET /key — тот же затвор, что у обновления сохранённых балансов."""
    s = get_settings()
    secret = s.openrouter_api_key
    if not secret:
        return items
    hint = sec.hint(secret)
    info: dict[str, Any] | None = None
    last_error: str | None = None
    already = any(item.get("provider") == "openai_compatible" and item.get("key_hint") == hint for item in items)
    if not already and not s.is_test and _chain_has_openai(s.llm_chain):
        prov = OpenAICompatProvider(
            secret,
            s.openrouter_base_url,
            budget_usd=s.openrouter_budget_usd,
            http_referer=f"http://localhost:{s.app_port}",
        )
        try:
            info = await prov.fetch_key()
        except Exception as exc:
            last_error = str(exc)[:300]
        finally:
            await prov.aclose()
    return public_openrouter_env_key(items, info, key_hint=hint, last_error=last_error)


@router.get("/api/settings/llm-keys", summary="API-ключи (значения не возвращаются, только хвост)")
async def get_llm_keys() -> Any:
    async with db() as conn:
        items = await load_keys(conn)
        if await _refresh_openai_balances(items):
            await set_setting(conn, "llm_keys", items)
        masked = _mask_keys(items)
    return await _with_openrouter_env_key(masked)


@router.post("/api/settings/llm-keys", status_code=201, summary="Сохранить API-ключ (шифруется APP_SECRET)")
async def post_llm_keys(body: LlmKeyBody) -> Any:
    async with db() as conn:
        items = await load_keys(conn)
        item = {
            "id": (max((int(i["id"]) for i in items), default=0) + 1),
            "provider": body.provider,
            "label": body.label,
            "key_hint": sec.hint(body.key),
            "key_enc": sec.encrypt(body.key, get_settings().app_secret),
            "tokens_used": 0,
            "tokens_limit": body.tokens_limit,
            "requests_today": 0,
            "rpd_limit": body.rpd_limit,
            "balance_usd": None,
            "is_active": True,
            "last_error": None,
            "created_at": dt.datetime.now(dt.UTC).isoformat(),
        }
        items.append(item)
        await set_setting(conn, "llm_keys", items)
    return _mask_keys([item])[0]


@router.delete("/api/settings/llm-keys/{id}", status_code=204, summary="Удалить API-ключ")
async def delete_llm_keys_id(id: int) -> Response:  # noqa: A002
    async with db() as conn:
        items = await load_keys(conn)
        rest = [i for i in items if int(i["id"]) != id]
        if len(rest) == len(items):
            raise Problem(404, "Ключ не найден")
        await set_setting(conn, "llm_keys", rest)
    return Response(status_code=204)


# ---- templates ------------------------------------------------------------
class NotificationTemplate(BaseModel):
    id: int | None = None
    code: str
    channel_code: str
    segment_code: str | None = None
    lang: str = "ru"
    subject: str | None = None
    body: str
    variables: list[str] = Field(default_factory=list)


@router.get("/api/settings/templates", summary="Шаблоны уведомлений (канал × сегмент × язык)")
async def get_templates() -> Any:
    async with db() as conn:
        return await fetch_all(conn, EXPORT_TABLES["notification_templates"])


async def _put_templates(conn: Any, items: list[NotificationTemplate]) -> None:
    await conn.execute("delete from notification_templates")
    for t in items:
        await conn.execute(
            "insert into notification_templates (code, channel_code, segment_code, lang, subject, body, variables) values (%s, %s, %s, %s, %s, %s, %s)",
            (t.code, t.channel_code, t.segment_code, t.lang, t.subject, t.body, t.variables),
        )


@router.put("/api/settings/templates", summary="Заменить шаблоны уведомлений")
async def put_templates(body: list[NotificationTemplate]) -> Response:
    async with db() as conn:
        await _put_templates(conn, body)
    return Response(status_code=200)


# ---- gifts ----------------------------------------------------------------
class Gift(BaseModel):
    code: str
    name_ru: str
    name_en: str
    segments: list[str]
    rule: dict[str, Any]
    partner_display_name: str | None = None


@router.get("/api/settings/gifts", summary="Каталог подарков по сегментам (ТЗ 10.2)")
async def get_gifts() -> Any:
    async with db() as conn:
        return await fetch_all(conn, EXPORT_TABLES["gift_catalog"])


async def _put_gifts(conn: Any, items: list[Gift]) -> None:
    for g in items:
        await conn.execute(
            "insert into gift_catalog (code, name_ru, name_en, segments, rule, partner_display_name) values (%s, %s, %s, %s, %s, %s) on conflict (code) do update set name_ru = excluded.name_ru, name_en = excluded.name_en, segments = excluded.segments, rule = excluded.rule, partner_display_name = excluded.partner_display_name",
            (g.code, g.name_ru, g.name_en, g.segments, Jsonb(g.rule), g.partner_display_name),
        )
    codes = [g.code for g in items]
    await conn.execute("delete from gift_catalog where not (code = any(%s))", (codes,))


@router.put("/api/settings/gifts", summary="Заменить каталог подарков")
async def put_gifts(body: list[Gift]) -> Response:
    async with db() as conn:
        await _put_gifts(conn, body)
    return Response(status_code=200)


# ---- economics ------------------------------------------------------------
class EconomicsSettings(BaseModel):
    detractor_share: float = Field(0.1, ge=0, le=1)
    no_return_share: float = Field(0.5, ge=0, le=1)
    retention_factors: dict[str, float] = Field(default_factory=dict)
    calibration_mode: Literal["manual", "simulated"] = "manual"
    misselling_case_cost_rub: float | None = None
    map_zone_thresholds: dict[str, Any] | None = None
    fallback_rate_code: str | None = None
    rates: list[dict[str, Any]] | None = None


async def _economics(conn: Any) -> dict[str, Any]:
    row = (
        await fetch_one(
            conn,
            "select detractor_share::float, no_return_share::float, retention_factors, calibration_mode, fallback_rate_code, misselling_case_cost_rub::float, map_zone_thresholds, updated_at from economics_settings where id = 1",
        )
        or {}
    )
    row["rates"] = await fetch_all(conn, EXPORT_TABLES["dcltv_rates"])
    return row


@router.get("/api/settings/economics", summary="Настройки экономики dCLTV (ТЗ 14.4) и ставки")
async def get_economics() -> Any:
    async with db() as conn:
        return await _economics(conn)


async def _put_economics(conn: Any, e: EconomicsSettings) -> None:
    await conn.execute(
        "insert into economics_settings (id, detractor_share, no_return_share, retention_factors, calibration_mode, fallback_rate_code, misselling_case_cost_rub, map_zone_thresholds, updated_at) values (1, %s, %s, %s, %s, %s, %s, %s, now()) "
        "on conflict (id) do update set detractor_share = excluded.detractor_share, no_return_share = excluded.no_return_share, retention_factors = excluded.retention_factors, calibration_mode = excluded.calibration_mode, "
        "fallback_rate_code = coalesce(excluded.fallback_rate_code, economics_settings.fallback_rate_code), misselling_case_cost_rub = coalesce(excluded.misselling_case_cost_rub, economics_settings.misselling_case_cost_rub), "
        "map_zone_thresholds = coalesce(excluded.map_zone_thresholds, economics_settings.map_zone_thresholds), updated_at = now()",
        (
            e.detractor_share,
            e.no_return_share,
            Jsonb(e.retention_factors),
            e.calibration_mode,
            e.fallback_rate_code,
            e.misselling_case_cost_rub,
            Jsonb(e.map_zone_thresholds) if e.map_zone_thresholds is not None else None,
        ),
    )
    for r in e.rates or []:
        await conn.execute(
            "insert into dcltv_rates (code, name_ru, name_en, rate_rub, maps_to) values (%s, %s, %s, %s, %s) on conflict (code) do update set name_ru = excluded.name_ru, name_en = excluded.name_en, rate_rub = excluded.rate_rub, maps_to = excluded.maps_to",
            (
                r["code"],
                r.get("name_ru") or r["code"],
                r.get("name_en") or r["code"],
                float(r["rate_rub"]),
                Jsonb(r.get("maps_to") or {}),
            ),
        )
    await conn.execute("update incident_economics set computed_at = '1970-01-01' where true")


@router.put("/api/settings/economics", summary="Сохранить экономику (все инциденты пересчитаются лениво)")
async def put_economics(body: EconomicsSettings) -> Response:
    async with db() as conn:
        await _put_economics(conn, body)
    return Response(status_code=200)


# ---- psychotypes ----------------------------------------------------------
class Psychotype(BaseModel):
    code: str
    name_ru: str
    name_en: str
    params: dict[str, Any]


class PsychotypeSettings(BaseModel):
    psychotypes: list[Psychotype] = Field(default_factory=list)
    segment_mix: dict[str, dict[str, float]] | None = None


@router.get("/api/settings/psychotypes", summary="Психотипы цифровых двойников и их доли по сегментам (ТЗ 4.5)")
async def get_psychotypes() -> Any:
    async with db() as conn:
        pts = await fetch_all(conn, EXPORT_TABLES["psychotypes"])
        mix_rows = await fetch_all(conn, EXPORT_TABLES["segment_psychotype_mix"])
    mix: dict[str, dict[str, float]] = {}
    for r in mix_rows:
        mix.setdefault(r["segment_code"], {})[r["psychotype_code"]] = float(r["share"])
    return {"psychotypes": pts, "segment_mix": mix}


async def _put_psychotypes(conn: Any, body: PsychotypeSettings) -> None:
    for p in body.psychotypes:
        await conn.execute(
            "insert into psychotypes (code, name_ru, name_en, params) values (%s, %s, %s, %s) on conflict (code) do update set name_ru = excluded.name_ru, name_en = excluded.name_en, params = excluded.params",
            (p.code, p.name_ru, p.name_en, Jsonb(p.params)),
        )
    if body.segment_mix is not None:
        codes = {r["code"] for r in await fetch_all(conn, "select code from psychotypes")}
        for seg, shares in body.segment_mix.items():
            if abs(sum(shares.values()) - 1.0) > 0.01:
                raise Problem(
                    422, f"Сумма долей психотипов по сегменту {seg} должна быть 1 (сейчас {sum(shares.values()):.2f})"
                )
            if set(shares) - codes:
                raise Problem(422, f"Неизвестные психотипы: {', '.join(sorted(set(shares) - codes))}")
            await conn.execute("delete from segment_psychotype_mix where segment_code = %s", (seg,))
            for code, share in shares.items():
                await conn.execute(
                    "insert into segment_psychotype_mix (segment_code, psychotype_code, share) values (%s, %s, %s)",
                    (seg, code, share),
                )


@router.put("/api/settings/psychotypes", summary="Сохранить психотипы и доли по сегментам")
async def put_psychotypes(body: PsychotypeSettings) -> Response:
    async with db() as conn:
        await _put_psychotypes(conn, body)
    return Response(status_code=200)


# ---- refs (справочники для фронта) ----------------------------------------
@router.get(
    "/api/refs/{name}",
    summary="Справочник по имени (regions, cities, segments, products, systems, teams, channels, error_codes, signal_types)",
)
async def get_refs_name(request: Request, name: str, region_code: str | None = None) -> Any:
    """Справочники для фронта (T-009, минимум для L4): без пагинации, только whitelisted таблицы."""
    if name not in _REF_TABLES:
        raise Problem(404, "Не найдено", f"справочник {name!r} не найден")
    sql, order = _REF_TABLES[name]
    args: list[Any] = []
    if name == "cities" and region_code:
        sql += " WHERE region_code = %s"
        args.append(region_code)
    async with db() as conn:
        return await fetch_all(conn, f"{sql} ORDER BY {order}", args)


_REF_TABLES: dict[str, tuple[str, str]] = {
    "regions": ("SELECT code, name_ru, name_en, district_code, population FROM regions", "name_ru"),
    "cities": ("SELECT id, region_code, name_ru, population, lat, lon, is_capital FROM cities", "population DESC"),
    "segments": (
        "SELECT code, name_ru, name_en, first_response_min, priority_multiplier, tone, hitl_required, personal_manager "
        "FROM segments",
        "priority_multiplier DESC",
    ),
    "products": ("SELECT code, name_ru, name_en FROM products", "name_ru"),
    "systems": ("SELECT code, name_ru, name_en, layer FROM systems", "name_ru"),
    "teams": ("SELECT code, name_ru, name_en, speed_profile, lead_display_name FROM teams", "name_ru"),
    "channels": ("SELECT code, name_ru, name_en, subtypes, identifies_client, is_public FROM channels", "name_ru"),
    "error_codes": (
        "SELECT code, system_code, product_code, title_ru, default_complexity, default_criticality, client_visible "
        "FROM error_codes",
        "code",
    ),
    "signal_types": ("SELECT * FROM signal_types", "1"),
    "federal_districts": ("SELECT * FROM federal_districts", "1"),
}
