"""Read-only journey API (ТЗ 27)."""

from __future__ import annotations

from typing import Any, Literal

from fastapi import APIRouter

from app.trace.journey import journey, latest
from app.trace.store import read_db

router = APIRouter(tags=["journey"])


@router.get("/api/journey/latest", summary="[АРХ] Последний путь «Следить»")
async def journey_latest(origin: Literal["jury", "feed", "sim", "any"] = "any", run_id: str = "current") -> Any:
    async with read_db() as conn:
        return await latest(conn, origin, run_id)


@router.get("/api/journey/{ref}", summary="[АРХ] Путь обращения")
async def journey_by_ref(ref: str, run_id: str = "current", presenter: bool = False) -> Any:
    async with read_db() as conn:
        return await journey(conn, ref, run_id, presenter)
