"""Роутер тега `csi` (OpenAPI 1.5.0). Реализация — T-246/T-247."""

from __future__ import annotations

from fastapi import APIRouter, Header

from app.errors import NotImplementedYet

router = APIRouter(tags=["csi"])


@router.get("/api/csi/analytics", summary="[ЕТЗ] Аналитика CSI")
def csi_analytics(
    branch_id: int | None = None,
    run_id: str = "current",
    x_cx_role: str | None = Header(default=None, alias="X-Cx-Role"),
) -> None:
    raise NotImplementedYet("T-247")
