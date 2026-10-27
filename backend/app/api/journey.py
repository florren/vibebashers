"""Роутер тега `journey` (OpenAPI 1.5.0). Реализация пути — T-225."""

from __future__ import annotations

from fastapi import APIRouter

from app.errors import NotImplementedYet

router = APIRouter(tags=["journey"])


@router.get("/api/journey/latest", summary="[АРХ] Последний путь «Следить»")
def journey_latest(origin: str = "any", run_id: str = "current") -> None:
    raise NotImplementedYet("T-225")


@router.get("/api/journey/{ref}", summary="[АРХ] Путь обращения")
def journey_by_ref(ref: str, run_id: str = "current") -> None:
    raise NotImplementedYet("T-225")
