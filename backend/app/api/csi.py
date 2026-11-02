"""T-248: CSI analytics, только чтение с явным scope и coverage."""

from __future__ import annotations

from typing import Any, Literal

from fastapi import APIRouter, Query, Request

from app.analytics.cabinet_scope import actor_role, resolve_scope, validate_run
from app.analytics.csi import analytics
from app.trace.store import read_db

router = APIRouter(tags=["csi"])


@router.get("/api/csi/analytics", summary="[ЕТЗ] Аналитика CSI")
async def csi_analytics(
    request: Request,
    branch_id: int | None = Query(None, ge=1, le=2147483647),
    run_id: str = Query("current", max_length=32),
    product_line: str | None = Query(None, max_length=80),
    region_code: str | None = Query(None, max_length=20),
    period: Literal["day", "week", "month", "quarter"] = "week",
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0, le=100000),
    scatter_limit: int = Query(1000, ge=1, le=5000),
) -> Any:
    validate_run(run_id)
    actor_role(request)
    async with read_db() as conn:
        scope = await resolve_scope(conn, request, product_line, period, run_id, include_baseline=False)
        return await analytics(
            conn,
            scope,
            branch_id=branch_id,
            region=region_code,
            limit=limit,
            offset=offset,
            scatter_limit=scatter_limit,
        )
