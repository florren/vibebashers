"""Роутер тега `metrics` (OpenAPI 1.4.0). Заглушки 501 — реализация: карточка T-093."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Request

from app.errors import NotImplementedYet

router = APIRouter(tags=["metrics"])


@router.get("/api/metrics/dashboard", summary="KPI рабочего места (ТЗ 14.1) — по умолчанию в рамках текущего запуска")
async def get_metrics_dashboard(request: Request) -> Any:
    raise NotImplementedYet("T-093")


@router.get(
    "/api/metrics/economics",
    summary="Экономика dCLTV — потенциальные, предотвращённые, под риском, реализованные (ТЗ 14.4)",
)
async def get_metrics_economics(request: Request) -> Any:
    raise NotImplementedYet("T-093")


@router.get(
    "/api/metrics/economics/fact", summary="Калькулятор «Факт по симуляции» (ТЗ 14.5) — по умолчанию текущий запуск"
)
async def get_metrics_economics_fact(request: Request) -> Any:
    raise NotImplementedYet("T-093")


@router.get("/api/metrics/economics/fact/export", summary="Экспорт факта (CSV/XLSX)")
async def get_metrics_economics_fact_export(request: Request) -> Any:
    raise NotImplementedYet("T-093")


@router.post(
    "/api/metrics/economics/calibrate", summary="«Подставить факт в калькулятор» — переключить calibration_mode"
)
async def post_metrics_economics_calibrate(request: Request) -> Any:
    raise NotImplementedYet("T-093")


@router.get("/api/notifications", summary="Центр уведомлений (все исходящие сообщения)")
async def get_notifications(request: Request) -> Any:
    raise NotImplementedYet("T-093")


@router.get(
    "/api/metrics/economics/live",
    summary="[ДТЗ FR-5.4] Живой тикер финансового эффекта: CLV под риском, предотвращённые и потенциальные потери текущего запуска (тот же payload — WS metrics/economics_live)",
)
async def get_metrics_economics_live(request: Request) -> Any:
    raise NotImplementedYet("T-093")
