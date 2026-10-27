"""Роутер тега `trace` (OpenAPI 1.5.0). Реализация сборщика — T-224."""

from __future__ import annotations

from fastapi import APIRouter

from app.errors import NotImplementedYet

router = APIRouter(tags=["trace"])


@router.get("/api/trace/{kind}/{ref}", summary="[АРХ] След объекта")
def trace_object(
    kind: str,
    ref: str,
    before_depth: int = 3,
    after_limit: int = 200,
    run_id: str = "all",
    include: str | None = None,
) -> None:
    raise NotImplementedYet("T-224")
