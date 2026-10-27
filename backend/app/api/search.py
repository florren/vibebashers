"""Роутер тега `search` (OpenAPI 1.5.0). Реализация — T-230."""

from __future__ import annotations

from fastapi import APIRouter, Query

from app.errors import NotImplementedYet

router = APIRouter(tags=["search"])


@router.get("/api/search", summary="[АРХ] Универсальный поиск")
def search(
    q: str = Query(..., min_length=1),
    run_id: str = "current",
    limit: int = 50,
) -> None:
    raise NotImplementedYet("T-230")
