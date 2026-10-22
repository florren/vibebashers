"""Роутер тега `sim` (OpenAPI 1.4.0). Заглушки 501 — реализация: карточка T-031."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Request

from app.errors import NotImplementedYet

router = APIRouter(tags=["sim"])


@router.get("/api/sim/state", summary="Текущее состояние симуляции")
async def get_sim_state(request: Request) -> Any:
    raise NotImplementedYet("T-031")


@router.post("/api/sim/control", summary="Старт/Пауза/Возобновить/Стоп/Шаг/Сброс дня/Скорость")
async def post_sim_control(request: Request) -> Any:
    raise NotImplementedYet("T-031")


@router.get("/api/sim/events", summary="Лента событий симулятора (шина событий)")
async def get_sim_events(request: Request) -> Any:
    raise NotImplementedYet("T-031")


@router.get("/api/sim/runs", summary="История запусков эмуляции (ТЗ 4.6)")
async def get_sim_runs(request: Request) -> Any:
    raise NotImplementedYet("T-031")


@router.post(
    "/api/sim/runs", summary="Создать и стартовать новый запуск (свободный или сценарный) с выбранным режимом сброса"
)
async def post_sim_runs(request: Request) -> Any:
    raise NotImplementedYet("T-031")


@router.get("/api/sim/runs/current", summary="Текущий запуск с живыми счётчиками (v_run_counters)")
async def get_sim_runs_current(request: Request) -> Any:
    raise NotImplementedYet("T-031")


@router.get("/api/sim/runs/{id}", summary="Запуск: параметры, счётчики, итоговые метрики")
async def get_sim_runs_id(request: Request) -> Any:
    raise NotImplementedYet("T-031")


@router.delete("/api/sim/runs/{id}", summary="Удалить запуск вместе с данными (нельзя для baseline и текущего)")
async def delete_sim_runs_id(request: Request) -> Any:
    raise NotImplementedYet("T-031")


@router.post("/api/sim/runs/{id}/stop", summary="Завершить запуск (рассчитать summary, статус stopped)")
async def post_sim_runs_id_stop(request: Request) -> Any:
    raise NotImplementedYet("T-031")


@router.post("/api/sim/runs/{id}/resume", summary="Возобновить прерванный/приостановленный запуск с того же sim_time")
async def post_sim_runs_id_resume(request: Request) -> Any:
    raise NotImplementedYet("T-031")


@router.post(
    "/api/sim/runs/{id}/archive",
    summary="Архивировать — экспорт в runs/<id>.json и удаление строк данных, summary сохраняется",
)
async def post_sim_runs_id_archive(request: Request) -> Any:
    raise NotImplementedYet("T-031")


@router.get("/api/sim/runs/{id}/export", summary="Экспорт запуска (JSON с summary и агрегатами или CSV событий)")
async def get_sim_runs_id_export(request: Request) -> Any:
    raise NotImplementedYet("T-031")


@router.get("/api/sim/runs/compare", summary="Сравнение двух запусков по метрикам 14.1/14.4 и расходу токенов")
async def get_sim_runs_compare(request: Request) -> Any:
    raise NotImplementedYet("T-031")


@router.get(
    "/api/sim/baseline", summary="Состояние снимка базового состояния (путь, профиль, размер, контрольная сумма, дата)"
)
async def get_sim_baseline(request: Request) -> Any:
    raise NotImplementedYet("T-031")


@router.post(
    "/api/sim/baseline",
    summary="Пересоздать снимок baseline из текущего базового состояния (только когда нет активного запуска)",
)
async def post_sim_baseline(request: Request) -> Any:
    raise NotImplementedYet("T-031")


@router.post(
    "/api/sim/baseline/restore",
    summary="Откат к снимку baseline без старта нового запуска (режим обслуживания, ≤ 60 с для demo)",
)
async def post_sim_baseline_restore(request: Request) -> Any:
    raise NotImplementedYet("T-031")
