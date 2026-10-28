"""Universal read-only search (ТЗ 28.2)."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Query

from app.search.service import search_objects
from app.trace.store import read_db

router = APIRouter(tags=["search"])


@router.get("/api/search", summary="[АРХ] Универсальный поиск")
async def search(
    q: str = Query(..., min_length=1, max_length=500), run_id: str = "current", limit: int = Query(50, ge=1, le=50)
) -> Any:
    async with read_db() as conn:
        return await search_objects(conn, q, run_id, limit)
