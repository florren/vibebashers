"""Роутер тега `bench` (OpenAPI 1.4.0). Заглушки 501 — реализация: карточка T-129."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Request

from app.errors import NotImplementedYet

router = APIRouter(tags=["bench"])


@router.get("/api/bench/datasets", summary="Наборы (golden, lite) с числом кейсов")
async def get_bench_datasets(request: Request) -> Any:
    raise NotImplementedYet("T-129")


@router.get("/api/bench/runs", summary="Прогоны и сводные метрики (таблица сравнения)")
async def get_bench_runs(request: Request) -> Any:
    raise NotImplementedYet("T-129")


@router.post("/api/bench/runs", summary="Запустить прогон (с прогнозом расхода токенов и проверкой лимитов)")
async def post_bench_runs(request: Request) -> Any:
    raise NotImplementedYet("T-129")


@router.get("/api/bench/runs/{id}", summary="Прогон с результатами по кейсам")
async def get_bench_runs_id(request: Request) -> Any:
    raise NotImplementedYet("T-129")


@router.delete("/api/bench/runs/{id}", summary="Отменить прогон")
async def delete_bench_runs_id(request: Request) -> Any:
    raise NotImplementedYet("T-129")


@router.get("/api/bench/runs/{id}/export", summary="Экспорт результатов (CSV/JSON)")
async def get_bench_runs_id_export(request: Request) -> Any:
    raise NotImplementedYet("T-129")


@router.get(
    "/api/bench/sentiment",
    summary="[ДТЗ FR-2.1] Последний отчёт бенчмарка sentiment_v1: accuracy по провайдерам, матрица ошибок, согласованность с порогами negativity",
)
async def get_bench_sentiment(request: Request) -> Any:
    raise NotImplementedYet("T-129")
