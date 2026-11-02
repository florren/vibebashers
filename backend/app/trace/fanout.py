"""Постраничные реальные связи trace: bounded keyset, без записей и вызовов LLM."""

from __future__ import annotations

import base64
import binascii
import json
from dataclasses import dataclass
from typing import Any

from fastapi import HTTPException

from app.api.common import fetch_all, fetch_one
from app.contracts.enums import TraceEventKind, TracePhase
from app.trace.projections import node_key, project, reference
from app.trace.relations import RELATIONS, TYPES
from app.trace.store import Conn, allowed_run, resolve, scope

MAX_CURSOR_BYTES = 1024
MAX_PK = 2**63 - 1
FAN_TYPES = {TraceEventKind.SIGNAL_CREATED: "signal", TraceEventKind.NOTIFICATION: "notification"}
DIRECTIONS = {TracePhase.BEFORE, TracePhase.AFTER}


@dataclass(frozen=True)
class Cursor:
    context: dict[str, Any]
    last: int
    upper: int


def invalid_cursor() -> HTTPException:
    return HTTPException(422, "Некорректный cursor или его контекст")


def normalize_scope(run_id: str) -> str:
    if run_id in ("", "current"):
        return "current"
    if run_id == "all":
        return "all"
    try:
        if len(run_id) > 32:
            raise ValueError
        value = int(run_id)
        if not 1 <= value <= MAX_PK:
            raise ValueError
    except ValueError:
        raise HTTPException(422, "run_id: current | all | положительный bigint") from None
    return str(value)


def validate_anchor_ref(kind: str, ref: str) -> None:
    # isdigit() включает символы вроде ², которые общий legacy parser передаёт
    # в int(), вызывая ValueError. Десятичные Unicode-цифры остаются допустимыми.
    if not ref.strip() or len(ref) > 200:
        raise HTTPException(422, "Некорректный ref")
    if ref.isdigit():
        if not ref.isdecimal():
            raise HTTPException(422, "Некорректный числовой ref")
        canonical = {"tracking": "signal", "correlation": "ledger"}.get(kind, kind)
        spec = TYPES.get(canonical)
        if spec is not None and spec.key != "code" and not 1 <= int(ref) <= MAX_PK:
            raise HTTPException(422, "Числовой ref должен быть положительным bigint")


def decode_cursor(token: str | None) -> Cursor | None:
    if token is None:
        return None
    try:
        encoded = token.encode("ascii")
        if not encoded or len(encoded) > MAX_CURSOR_BYTES:
            raise ValueError
        raw = base64.b64decode(encoded + b"=" * (-len(encoded) % 4), altchars=b"-_", validate=True)
        value = json.loads(raw)
        if not isinstance(value, dict) or set(value) != {"v", "context", "last", "upper"}:
            raise ValueError
        if type(value["v"]) is not int or value["v"] != 1:
            raise ValueError
        context = value["context"]
        if not isinstance(context, dict) or set(context) != {
            "kind",
            "ref",
            "event_id",
            "direction",
            "event_kind",
            "run",
        }:
            raise ValueError
        for key in ("kind", "ref", "event_id", "direction", "event_kind"):
            if not isinstance(context[key], str) or not context[key] or len(context[key]) > 512:
                raise ValueError
        if context["direction"] not in DIRECTIONS or context["event_kind"] not in FAN_TYPES:
            raise ValueError
        if context["run"] is not None and (type(context["run"]) is not int or not -1 <= context["run"] <= MAX_PK):
            raise ValueError
        if any(type(value[key]) is not int for key in ("last", "upper")):
            raise ValueError
        if not 0 <= value["last"] <= value["upper"] <= MAX_PK:
            raise ValueError
        return Cursor(context, value["last"], value["upper"])
    except (ValueError, TypeError, UnicodeError, binascii.Error, RecursionError):
        raise invalid_cursor() from None


def encode_cursor(context: dict[str, Any], last: int, upper: int) -> str:
    raw = json.dumps(
        {"v": 1, "context": context, "last": last, "upper": upper}, sort_keys=True, separators=(",", ":")
    ).encode()
    token = base64.urlsafe_b64encode(raw).decode().rstrip("=")
    if len(token) > MAX_CURSOR_BYTES:
        raise invalid_cursor()
    return token


def related_query(anchor: dict[str, Any], target: str, direction: str, rid: int | None) -> tuple[str, list[Any]]:
    """Только внутренние allowlists SQL; cursor/ref никогда не становятся идентификаторами."""
    queries: list[str] = []
    args: list[Any] = []
    source = anchor["kind"]
    for a, b, predicate in RELATIONS:
        src, dst = (a, b) if direction == TracePhase.AFTER else (b, a)
        if src != source or dst != target:
            continue
        alias, other = ("a", "b") if direction == TracePhase.AFTER else ("b", "a")
        queries.append(
            f"SELECT {other}.id FROM {TYPES[a].table} a JOIN {TYPES[b].table} b ON {predicate} "
            f"WHERE {alias}.{TYPES[source].key}=%s AND (%s::bigint IS NULL OR {scope(target, other)} IS NULL "
            f"OR {scope(target, other)}=%s OR {scope(target, other)} IN (SELECT id FROM sim_runs WHERE kind='baseline'))"
        )
        args.extend((anchor["data"][TYPES[source].key], rid, rid))
    # UNION удаляет один объект, достигнутый несколькими настоящими связями.
    return " UNION ".join(queries), args


async def relation_page(
    conn: Conn,
    kind: str,
    ref: str,
    *,
    direction: TracePhase,
    event_kind: TraceEventKind,
    run_id: str,
    limit: int,
    cursor: Cursor | None,
) -> dict[str, Any]:
    if direction not in DIRECTIONS or event_kind not in FAN_TYPES or not 1 <= limit <= 100:
        raise HTTPException(422, "Допустимы before/after, signal_created/notification и limit от 1 до 100")
    run_id = normalize_scope(run_id)
    validate_anchor_ref(kind, ref)
    anchor = await resolve(conn, kind, ref, run_id)
    rid = await allowed_run(conn, run_id)
    metadata = {"kind": anchor["kind"], "ref": reference(anchor), "event_id": "EVT-" + node_key(anchor)}
    context = {**metadata, "direction": str(direction), "event_kind": str(event_kind), "run": rid}
    if cursor is not None and cursor.context != context:
        raise invalid_cursor()
    target = FAN_TYPES[event_kind]
    related, args = related_query(anchor, target, direction, rid)
    result: dict[str, Any] = {
        "anchor": metadata,
        "direction": str(direction),
        "event_kind": str(event_kind),
        "total": 0,
        "items": [],
        "edges": [],
        "next_cursor": None,
    }
    if not related:
        return result
    fence = cursor.upper if cursor else None
    count = await fetch_one(
        conn,
        f"WITH related AS ({related}) SELECT count(*) AS total,coalesce(max(id),0) AS upper FROM related WHERE (%s::bigint IS NULL OR id<=%s)",
        [*args, fence, fence],
    )
    assert count is not None
    result["total"] = int(count["total"])
    upper = cursor.upper if cursor else int(count["upper"])
    last = cursor.last if cursor else None
    rows = await fetch_all(
        conn,
        f"WITH related AS ({related}) SELECT to_jsonb(c) AS data,{scope(target, 'c')} AS scope_id FROM related r JOIN {TYPES[target].table} c ON c.id=r.id WHERE c.id<=%s AND (%s::bigint IS NULL OR c.id>%s) ORDER BY c.id LIMIT %s",
        [*args, upper, last, last, limit + 1],
    )
    page = rows[:limit]
    for row in page:
        node = {"kind": target, "data": row["data"], "scope_id": row["scope_id"]}
        event = project(node, str(direction))
        result["items"].append(event)
        start, end = (
            (event["id"], metadata["event_id"])
            if direction == TracePhase.BEFORE
            else (metadata["event_id"], event["id"])
        )
        result["edges"].append({"from": start, "to": end, "relation_ru": "Привело к событию"})
    if len(rows) > limit:
        result["next_cursor"] = encode_cursor(context, int(page[-1]["data"]["id"]), upper)
    return result
