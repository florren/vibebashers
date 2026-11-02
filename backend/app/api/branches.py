"""T-248: справочник ВСП, scoped read-only аналитика и история сети."""

from __future__ import annotations

from typing import Any, Literal

from fastapi import APIRouter, HTTPException, Path, Query, Request, Response

from app.analytics import branches, csi
from app.analytics.branch_scope import branch_predicate, directory_metadata
from app.analytics.cabinet_scope import actor_role, resolve_preset, resolve_scope, validate_run
from app.api.common import fetch_all, fetch_one
from app.trace.store import read_db

router = APIRouter(tags=["branches"])
FIELDS = (
    "b.id,b.code,b.name_ru,b.region_code,r.okato as region_okato,c.name_ru as city_name,b.desks,"
    "b.branch_type,b.branch_status,b.lat,b.lon,b.address_ru,b.hours_ru,b.opened_sim,b.closed_sim,b.product_line_codes"
)


def cache_directory(response: Response) -> None:
    response.headers["Cache-Control"] = "private, max-age=86400"
    response.headers["Vary"] = "X-Cx-Role, X-Cx-Product-Line"


@router.get("/api/branches", summary="[ЕТЗ] Справочник ВСП")
async def list_branches(
    request: Request,
    response: Response,
    region_code: str | None = Query(None, max_length=20),
    status: Literal["open", "closed"] | None = None,
    product_line: str | None = Query(None, max_length=80),
    limit: int = Query(50, ge=1, le=200),
    cursor: str | None = Query(None, max_length=32),
) -> Any:
    actor_role(request)
    async with read_db() as conn:
        role, visibility, lines, _ = await resolve_preset(conn, request, product_line)
        where, args = branch_predicate(lines, region_code, status=status)
        if cursor:
            where += " AND b.code>%s"
            args.append(cursor)
        rows = await fetch_all(
            conn,
            "SELECT "
            + FIELDS
            + " FROM branches b JOIN cities c ON c.id=b.city_id JOIN regions r ON r.code=b.region_code WHERE "
            + where
            + " ORDER BY b.code LIMIT %s",
            [*args, limit + 1],
        )  # noqa: S608
        directory = await directory_metadata(conn)
    cache_directory(response)
    more = len(rows) > limit
    items = rows[:limit]
    return {
        "items": items,
        "next_cursor": items[-1]["code"] if more else None,
        "scope": {"role": role, "visibility": visibility, "product_lines": lines},
        "directory": directory,
    }


@router.get("/api/branches/network", summary="[ЕТЗ] Динамика сети ВСП")
async def branch_network(
    request: Request,
    response: Response,
    region_code: str | None = Query(None, max_length=20),
    product_line: str | None = Query(None, max_length=80),
    months: int = Query(12, ge=1, le=24),
) -> Any:
    actor_role(request)
    async with read_db() as conn:
        role, visibility, lines, _ = await resolve_preset(conn, request, product_line)
        result = await branches.network(conn, lines, region_code, months)
    cache_directory(response)
    return {**result, "scope": {"role": role, "visibility": visibility, "product_lines": lines}}


@router.get("/api/branches/analytics", summary="[ЕТЗ] ВСП и сигналы")
async def branch_analytics(
    request: Request,
    run_id: str = Query("current", max_length=32),
    product_line: str | None = Query(None, max_length=80),
    region_code: str | None = Query(None, max_length=20),
    period: Literal["day", "week", "month", "quarter"] = "week",
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0, le=100000),
) -> Any:
    validate_run(run_id)
    actor_role(request)
    async with read_db() as conn:
        scope = await resolve_scope(conn, request, product_line, period, run_id, include_baseline=False)
        return await branches.analytics(conn, scope, region_code, limit, offset)


@router.get("/api/branches/{code}", summary="[ЕТЗ] Карточка ВСП")
async def branch_detail(
    request: Request,
    code: str = Path(min_length=1, max_length=32),
    run_id: str = Query("current", max_length=32),
    product_line: str | None = Query(None, max_length=80),
    period: Literal["day", "week", "month", "quarter"] = "week",
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0, le=100000),
) -> Any:
    validate_run(run_id)
    actor_role(request)
    async with read_db() as conn:
        scope = await resolve_scope(conn, request, product_line, period, run_id, include_baseline=False)
        where, args = branch_predicate(scope.lines, None)
        row = await fetch_one(
            conn,
            "SELECT "
            + FIELDS
            + " FROM branches b JOIN cities c ON c.id=b.city_id JOIN regions r ON r.code=b.region_code WHERE "
            + where
            + " AND b.code=%s",
            [*args, code],
        )  # noqa: S608
        if row is None:
            raise HTTPException(404, "ВСП не найдено в выбранном пресете")
        facts = await csi.analytics(
            conn, scope, branch_id=row["id"], region=None, limit=limit, offset=offset, scatter_limit=1
        )
        # Только явная связь CSI/geo.vsp_code; географическая близость не означает
        # обращение в конкретное отделение. Никаких ФИО сотрудников в карточке.
        signal_where, signal_args = branches.signal_scope(scope)
        signals = await fetch_all(
            conn,
            "SELECT f.public_id AS signal_ref,f.received_sim,f.channel_code,f.status FROM "
            + branches.FACTS
            + " JOIN signals s ON s.id=f.id WHERE "
            + signal_where
            + " AND (s.geo->>'vsp_code'=%s OR EXISTS(SELECT 1 FROM csi_responses cr WHERE cr.signal_id=s.id AND cr.branch_id=%s)) ORDER BY f.received_sim DESC,f.id DESC LIMIT %s OFFSET %s",
            [*signal_args, code, row["id"], limit + 1, offset],
        )  # noqa: S608
        total = await fetch_one(
            conn,
            "SELECT count(*)::int AS n FROM "
            + branches.FACTS
            + " JOIN signals s ON s.id=f.id WHERE "
            + signal_where
            + " AND (s.geo->>'vsp_code'=%s OR EXISTS(SELECT 1 FROM csi_responses cr WHERE cr.signal_id=s.id AND cr.branch_id=%s))",
            [*signal_args, code, row["id"]],
        )  # noqa: S608
        return {
            "branch": row,
            "directory": await directory_metadata(conn),
            "scope": facts["scope"],
            "csi": {"coverage": facts["coverage"], "probabilities": facts["probabilities"]},
            "signals": {
                "items": signals[:limit],
                "total": total["n"] if total else 0,
                "next_offset": offset + limit if len(signals) > limit else None,
                "basis": "explicit_branch_link",
            },
            "trace_path": f"/trace/branch/{row['id']}?run_id={run_id}",
        }
