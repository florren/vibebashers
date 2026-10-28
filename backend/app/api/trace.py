"""Read-only object trace (ТЗ 28)."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException, Query

from app.trace.assembler import assemble
from app.trace.projections import node_key
from app.trace.store import read_db

router = APIRouter(tags=["trace"])


@router.get("/api/trace/{kind}/{ref}", summary="[АРХ] След объекта")
async def trace_object(
    kind: str,
    ref: str,
    before_depth: int = Query(3, ge=0, le=3),
    after_limit: int = Query(200, ge=1, le=200),
    run_id: str = "all",
    include: str | None = None,
) -> Any:
    if include not in (None, "key", "detail"):
        raise HTTPException(422, "include: key | detail")
    async with read_db() as conn:
        result, nodes = await assemble(
            conn, kind, ref, run_id=run_id, before_depth=before_depth, after_limit=after_limit
        )
    if include == "key":
        for phase in ("before", "after"):
            result[phase] = [event for event in result[phase] if event["importance"] == "key"]
        visible = {"EVT-" + node_key(nodes[0]), *(e["id"] for phase in ("before", "after") for e in result[phase])}
        result["edges"] = [edge for edge in result["edges"] if edge["from"] in visible and edge["to"] in visible]
    return result
