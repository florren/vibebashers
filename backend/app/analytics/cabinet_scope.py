"""T-241: пресеты представления, не авторизация; строгие границы чтения."""

from __future__ import annotations

import datetime as dt
import re
from dataclasses import dataclass
from typing import Any

from fastapi import HTTPException, Request
from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint
from starlette.responses import Response

from app.api.common import fetch_all, fetch_one
from app.trace.store import Conn

ROLES = {
    "cx_operator": ("Оператор CX", "CX operator"),
    "cx_lead": ("Руководитель CX", "CX lead"),
    "product_manager": ("Менеджер продукта", "Product manager"),
    "product_head": ("Руководитель продуктового блока", "Product head"),
    "compliance_officer": ("Комплаенс-офицер", "Compliance officer"),
    "bank_head": ("Руководитель банка", "Bank head"),
    "admin": ("Администратор", "Administrator"),
}
PERIODS = {"day": 1, "week": 7, "month": 30, "quarter": 90}


class CabinetPresetMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next: RequestResponseEndpoint) -> Response:
        # Валидация выполняется handler до DB; middleware только передаёт preset.
        request.state.cx_role = request.headers.get("X-Cx-Role", "cx_lead")
        request.state.cx_product_line = request.headers.get("X-Cx-Product-Line")
        return await call_next(request)


def actor_role(request: Request) -> str:
    role = getattr(request.state, "cx_role", request.headers.get("X-Cx-Role", "cx_lead"))
    if role not in ROLES:
        raise HTTPException(422, "X-Cx-Role: неизвестный пресет роли")
    return str(role)


def validate_run(value: str) -> None:
    if value in ("all", "current"):
        return
    if not re.fullmatch(r"[1-9][0-9]{0,18}", value) or int(value) > 9223372036854775807:
        raise HTTPException(422, "run_id: current | all | positive bigint")


@dataclass(frozen=True)
class CabinetScope:
    role: str
    visibility: str
    lines: list[str] | None
    available_lines: list[dict[str, Any]]
    run_ids: list[int] | None
    now: dt.datetime
    since: dt.datetime
    period: str

    def predicate(
        self, alias: str, *, since: dt.datetime | None = None, time_column: str = "received_sim"
    ) -> tuple[str, list[Any]]:
        # alias/time_column задаются только внутренними литералами вызовов.
        parts = [f"{alias}.{time_column} >= %s", f"{alias}.{time_column} <= %s"]
        args: list[Any] = [since or self.since, self.now]
        if self.run_ids is not None:
            parts.append(f"{alias}.run_id = ANY(%s)")
            args.append(self.run_ids)
        if self.lines is not None:
            parts.append(f"{alias}.product_line_code = ANY(%s)")
            args.append(self.lines)
        return " AND ".join(parts), args


async def resolve_preset(
    conn: Conn, request: Request, product_line: str | None = None
) -> tuple[str, str, list[str] | None, list[dict[str, Any]]]:
    """Общий presentation preset кабинета/CSI/справочника, без выдуманных часов."""
    role = actor_role(request)
    rows = await fetch_all(
        conn,
        "select key,value from settings where key IN ('cabinet','cabinet.visibility','cabinet.product_head_lines')",
    )
    settings = {r["key"]: r["value"] for r in rows}
    cabinet = settings.get("cabinet") or {}
    if not isinstance(cabinet, dict):
        raise HTTPException(409, "Некорректный settings.cabinet")
    visibility = settings.get("cabinet.visibility", cabinet.get("visibility", "soft"))
    if visibility not in ("soft", "strict"):
        raise HTTPException(409, "Некорректный settings.cabinet.visibility")
    catalog = await fetch_all(
        conn,
        "select code,name_ru,name_en,rate_code,owner_team_code,owner_is_proxy,product_codes from product_lines order by sort_order,code",
    )
    codes = {p["code"] for p in catalog}
    bound = getattr(request.state, "cx_product_line", request.headers.get("X-Cx-Product-Line"))
    if product_line not in (None, "all") and product_line not in codes:
        raise HTTPException(422, "Неизвестное продуктовое направление")
    if bound is not None and bound not in codes:
        raise HTTPException(422, "X-Cx-Product-Line: неизвестное направление")
    allowed: list[str] | None = None
    if role == "product_manager":
        if bound is None:
            raise HTTPException(
                403 if visibility == "strict" else 422, "Выберите направление менеджера в X-Cx-Product-Line"
            )
        allowed = [bound]
    elif role == "product_head":
        allowed = settings.get("cabinet.product_head_lines", cabinet.get("product_head_lines", []))
        if not isinstance(allowed, list) or any(not isinstance(x, str) or x not in codes for x in allowed):
            raise HTTPException(409, "Некорректный settings.cabinet.product_head_lines")
    selected: list[str] | None
    if visibility == "strict" and allowed is not None:
        if product_line == "all" or (product_line is not None and product_line not in allowed):
            raise HTTPException(403, "Строгий пресет: направление вне выбранного продуктового контура")
        selected = [product_line] if product_line else allowed
        catalog = [p for p in catalog if p["code"] in allowed]
    else:
        selected = None if product_line == "all" else [product_line] if product_line else allowed
    return role, visibility, selected, catalog


async def resolve_scope(
    conn: Conn, request: Request, product_line: str | None, period: str, run_id: str, *, include_baseline: bool = True
) -> CabinetScope:
    validate_run(run_id)
    if period not in PERIODS:
        raise HTTPException(422, "period: day | week | month | quarter")
    role, visibility, selected, catalog = await resolve_preset(conn, request, product_line)
    clock = await fetch_one(conn, "select sim_time,current_run_id from sim_state where id=1")
    if not clock:
        raise HTTPException(409, "Симуляционное время не инициализировано")
    run_ids = None
    if run_id != "all":
        baseline = await fetch_all(conn, "select id from sim_runs where kind='baseline'") if include_baseline else []
        current = clock["current_run_id"] if run_id == "current" else int(run_id)
        run_ids = sorted({int(r["id"]) for r in baseline} | ({int(current)} if current else set()))
    now = clock["sim_time"]
    return CabinetScope(
        role, visibility, selected, catalog, run_ids, now, now - dt.timedelta(days=PERIODS[period]), period
    )
