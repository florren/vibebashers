"""Read-only object trace (ТЗ 28)."""

from __future__ import annotations

from typing import Any, Literal

from fastapi import APIRouter, HTTPException, Path, Query

from app.contracts.enums import TraceEventKind, TracePhase
from app.trace.assembler import assemble
from app.trace.fanout import decode_cursor, normalize_scope, relation_page, validate_anchor_ref
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


@router.get("/api/trace/{kind}/{ref}/relations", summary="[АРХ] Полное постраничное раскрытие веера реальных связей")
async def trace_relations(
    direction: Literal[TracePhase.BEFORE, TracePhase.AFTER],
    event_kind: Literal[TraceEventKind.SIGNAL_CREATED, TraceEventKind.NOTIFICATION],
    kind: str = Path(min_length=1, max_length=40),
    ref: str = Path(min_length=1, max_length=200),
    run_id: str = "current",
    limit: int = Query(50, ge=1, le=100),
    cursor: str | None = None,
) -> Any:
    decoded = decode_cursor(cursor)
    validate_anchor_ref(kind, ref)
    run_id = normalize_scope(run_id)
    async with read_db() as conn:
        return await relation_page(
            conn, kind, ref, direction=direction, event_kind=event_kind, run_id=run_id, limit=limit, cursor=decoded
        )
