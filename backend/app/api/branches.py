"""Роутер тега `branches` (OpenAPI 1.5.0). Реализация — T-245."""

from __future__ import annotations

from fastapi import APIRouter

from app.errors import NotImplementedYet

router = APIRouter(tags=["branches"])


@router.get("/api/branches", summary="[ЕТЗ] Справочник ВСП")
def list_branches(
    region_code: str | None = None,
    status: str | None = None,
    limit: int = 50,
    cursor: str | None = None,
) -> None:
    raise NotImplementedYet("T-245")


@router.get("/api/branches/network", summary="[ЕТЗ] Динамика сети ВСП")
def branch_network(region_code: str | None = None, months: int = 12) -> None:
    raise NotImplementedYet("T-245")
