"""Фоновые бенчмарки с сохранением результатов и прогнозом по профилям (T-129)."""

from __future__ import annotations

from typing import Any, cast

from fastapi import APIRouter, Request
from fastapi.responses import Response
from pydantic import BaseModel, Field

from app.bench.service import BenchService
from app.errors import Problem

router = APIRouter(tags=["bench"])


class BenchStart(BaseModel):
    dataset_id: int
    llm_profile_ids: list[int] = Field(min_length=1)
    repeats: int = Field(default=1, ge=1, le=3)
    dry_run: bool = False


def service(request: Request) -> BenchService:
    return cast(BenchService, request.app.state.bench)


@router.get("/api/bench/datasets", summary="Наборы (golden, lite) с числом кейсов")
async def get_bench_datasets(request: Request) -> Any:
    return await service(request).datasets()


@router.get("/api/bench/runs", summary="Прогоны и сводные метрики (таблица сравнения)")
async def get_bench_runs(request: Request) -> Any:
    return await service(request).runs()


@router.post(
    "/api/bench/runs", summary="Запустить прогон (с прогнозом расхода токенов и проверкой лимитов)", status_code=202
)
async def post_bench_runs(request: Request, body: BenchStart) -> Any:
    return await service(request).start(body.dataset_id, body.llm_profile_ids, body.repeats, body.dry_run)


@router.get("/api/bench/runs/{id}", summary="Прогон с результатами по кейсам")
async def get_bench_runs_id(request: Request, id: int) -> Any:  # noqa: A002
    return await service(request).detail(id)


@router.delete("/api/bench/runs/{id}", summary="Отменить прогон", status_code=204)
async def delete_bench_runs_id(request: Request, id: int) -> Response:  # noqa: A002
    await service(request).cancel(id)
    return Response(status_code=204)


@router.get("/api/bench/runs/{id}/export", summary="Экспорт результатов (CSV/JSON)")
async def get_bench_runs_id_export(request: Request, id: int, format: str = "csv") -> Response:  # noqa: A002
    if format not in ("csv", "json"):
        raise Problem(422, "format: csv|json")
    body = await service(request).export(id, format)
    return Response(content=body, media_type="text/csv" if format == "csv" else "application/json")


@router.get("/api/bench/sentiment", summary="[ДТЗ FR-2.1] Последний отчёт бенчмарка sentiment_v1")
async def get_bench_sentiment(request: Request) -> Any:
    # Прогоны classify не измеряют тональность или macro-F1: не подменяем эти метрики accuracy типа.
    return {"dataset": "sentiment_v1", "size": 0, "run_at": "1970-01-01T00:00:00Z", "providers": []}
