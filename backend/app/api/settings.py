"""Роутер тега `settings` (OpenAPI 1.4.0). Заглушки 501 — реализация: карточка T-009."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Request

from app.api.common import db, fetch_all
from app.errors import NotImplementedYet, Problem

router = APIRouter(tags=["settings"])


@router.get("/api/settings", summary="Все настройки (ключ → значение)")
async def get_settings(request: Request) -> Any:
    raise NotImplementedYet("T-009")


@router.patch("/api/settings", summary="Изменить настройки (частично)")
async def patch_settings(request: Request) -> Any:
    raise NotImplementedYet("T-009")


@router.get(
    "/api/settings/export",
    summary="Экспорт конфигурации (JSON) — настройки, SLA, маршрутизация, шаблоны, профили LLM без ключей",
)
async def get_settings_export(request: Request) -> Any:
    raise NotImplementedYet("T-009")


@router.post("/api/settings/import", summary="Импорт конфигурации")
async def post_settings_import(request: Request) -> Any:
    raise NotImplementedYet("T-009")


@router.get("/api/settings/sla-matrix", summary="Матрица SLA")
async def get_settings_sla_matrix(request: Request) -> Any:
    raise NotImplementedYet("T-009")


@router.put("/api/settings/sla-matrix", summary="Заменить матрицу SLA (9 ячеек)")
async def put_settings_sla_matrix(request: Request) -> Any:
    raise NotImplementedYet("T-009")


@router.get("/api/settings/routing-rules", summary="Правила маршрутизации")
async def get_settings_routing_rules(request: Request) -> Any:
    raise NotImplementedYet("T-009")


@router.put("/api/settings/routing-rules", summary="Заменить правила")
async def put_settings_routing_rules(request: Request) -> Any:
    raise NotImplementedYet("T-009")


@router.get("/api/settings/llm-profiles", summary="Профили LLM")
async def get_settings_llm_profiles(request: Request) -> Any:
    raise NotImplementedYet("T-009")


@router.post("/api/settings/llm-profiles", summary="Добавить профиль")
async def post_settings_llm_profiles(request: Request) -> Any:
    raise NotImplementedYet("T-009")


@router.patch("/api/settings/llm-profiles/{id}", summary="Изменить профиль (в т. ч. роль main/fast/twin, активность)")
async def patch_settings_llm_profiles_id(request: Request) -> Any:
    raise NotImplementedYet("T-009")


@router.delete("/api/settings/llm-profiles/{id}", summary="Удалить профиль")
async def delete_settings_llm_profiles_id(request: Request) -> Any:
    raise NotImplementedYet("T-009")


@router.get("/api/settings/llm-keys", summary="Ключи LLM (без значения ключа) с остатками токенов/лимитов")
async def get_settings_llm_keys(request: Request) -> Any:
    raise NotImplementedYet("T-009")


@router.post("/api/settings/llm-keys", summary="Добавить ключ")
async def post_settings_llm_keys(request: Request) -> Any:
    raise NotImplementedYet("T-009")


@router.delete("/api/settings/llm-keys/{id}", summary="Удалить ключ")
async def delete_settings_llm_keys_id(request: Request) -> Any:
    raise NotImplementedYet("T-009")


@router.get("/api/settings/templates", summary="Шаблоны уведомлений")
async def get_settings_templates(request: Request) -> Any:
    raise NotImplementedYet("T-009")


@router.put("/api/settings/templates", summary="Заменить набор шаблонов")
async def put_settings_templates(request: Request) -> Any:
    raise NotImplementedYet("T-009")


@router.get("/api/settings/gifts", summary="Справочник подарков")
async def get_settings_gifts(request: Request) -> Any:
    raise NotImplementedYet("T-009")


@router.put("/api/settings/gifts", summary="Заменить справочник подарков")
async def put_settings_gifts(request: Request) -> Any:
    raise NotImplementedYet("T-009")


@router.get("/api/settings/economics", summary="Параметры экономики и таблица ставок dCLTV")
async def get_settings_economics(request: Request) -> Any:
    raise NotImplementedYet("T-009")


@router.put("/api/settings/economics", summary="Изменить параметры экономики/ставки")
async def put_settings_economics(request: Request) -> Any:
    raise NotImplementedYet("T-009")


@router.get("/api/settings/psychotypes", summary="Психотипы и доли по сегментам (ТЗ 4.5)")
async def get_settings_psychotypes(request: Request) -> Any:
    raise NotImplementedYet("T-009")


@router.put("/api/settings/psychotypes", summary="Изменить параметры психотипов и доли")
async def put_settings_psychotypes(request: Request) -> Any:
    raise NotImplementedYet("T-009")


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
