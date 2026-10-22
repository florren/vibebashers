"""Отчёты о качестве (docs/REPORTS.md): /api/reports/quality (json|md), /api/reports/http, /api/reports/log."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Query
from fastapi.responses import PlainTextResponse, Response

from app.api.common import db, resolve_run_id
from app.config import get_settings
from app.observability import http as http_obs
from app.observability.jsonl import read_tail
from app.observability.quality import build_quality_report, render_markdown

router = APIRouter(tags=["engine"])


@router.get(
    "/api/reports/quality",
    response_model=None,
    summary="Отчёт о качестве — что сломалось, что работает не так, что доработать",
)
async def get_quality_report(
    run_id: str | None = None, format: str = Query("json", pattern="^(json|md)$")
) -> Response | dict[str, Any]:
    async with db() as conn:
        rid = await resolve_run_id(conn, run_id or "all")
        rep = await build_quality_report(conn, rid)
    if format == "md":
        return PlainTextResponse(render_markdown(rep), media_type="text/markdown; charset=utf-8")
    return rep


@router.get("/api/reports/http", summary="HTTP-метрики процесса: маршруты, 5xx/501/4xx, медленные, последние ошибки")
async def get_http_stats() -> dict[str, Any]:
    return http_obs.stats.snapshot()


@router.get("/api/reports/log", summary="Хвост JSONL-журнала приложения")
async def get_log_tail(
    limit: int = Query(200, ge=1, le=2000), level: str = "warning", event: str | None = None
) -> list[dict[str, Any]]:
    return read_tail(get_settings().log_path, limit=limit, min_level=level, event=event)
