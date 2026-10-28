"""Read-only, batched graph access. All SQL identifiers are internal allowlists."""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Any

import psycopg
from fastapi import HTTPException

from app.api.common import db, fetch_all, fetch_one, resolve_run_id
from app.search.grammar import parse
from app.trace.relations import RELATIONS, TYPES

Conn = psycopg.AsyncConnection[dict[str, Any]]


def scope(kind: str, alias: str = "t") -> str:
    if kind == "sim_run":
        return f"{alias}.id"
    if kind == "step":
        return f"(SELECT sim_run_id FROM agent_runs WHERE id={alias}.run_id)"
    if kind == "status_history":
        return f"(SELECT run_id FROM incidents WHERE id={alias}.incident_id)"
    if kind == "csi":
        return f"(SELECT run_id FROM signals WHERE id={alias}.signal_id)"
    if kind in ("agent_run", "human_decision", "followup"):
        return f"{alias}.sim_run_id"
    if kind not in ("client", "branch", "employee", "rule", "error_code"):
        return f"{alias}.run_id"
    return "NULL::bigint"


async def allowed_run(conn: Conn, run_id: str) -> int | None:
    # A missing current pointer must not silently turn into an all-runs query.
    value = await resolve_run_id(conn, run_id)
    return -1 if run_id == "current" and value is None else value


@asynccontextmanager
async def read_db() -> AsyncIterator[Conn]:
    async with db() as conn, conn.transaction():
        await conn.execute("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ, READ ONLY")
        await conn.execute("SET LOCAL statement_timeout = '3000ms'")
        yield conn


async def resolve(conn: Conn, kind: str, ref: str, run_id: str = "all") -> dict[str, Any]:
    parsed = parse(ref)
    if kind in ("tracking", "correlation"):
        kind = "signal" if kind == "tracking" else "ledger"
    if kind not in TYPES:
        raise HTTPException(422, "Неизвестный тип объекта")
    spec = TYPES[kind]
    column = (
        "tracking_token"
        if parsed["kind"] == "tracking" and kind == "signal"
        else "correlation_id"
        if parsed["kind"] == "correlation"
        else spec.key
        if ref.isdigit()
        else spec.public
    )
    rid = await allowed_run(conn, run_id)
    value: Any = parsed["normalized"] if column not in (spec.key, "tracking_token") else ref
    predicate = f"t.{column}=%s"
    if kind == "branch" and not ref.isdigit():
        predicate = "t.code=ANY(%s)"
        value = [value, str(value).removeprefix("VSP-")]
    if column == spec.key and spec.key != "code":
        value = int(ref)
    row = await fetch_one(
        conn,
        f"SELECT to_jsonb(t) AS data, {scope(kind)} AS scope_id FROM {spec.table} t WHERE {predicate} AND (%s::bigint IS NULL OR {scope(kind)} IS NULL OR {scope(kind)}=%s OR {scope(kind)} IN (SELECT id FROM sim_runs WHERE kind='baseline'))",
        (value, rid, rid),
    )
    if not row:
        raise HTTPException(404, "Объект не найден в выбранном запуске")
    return {"kind": kind, "data": row["data"], "scope_id": row["scope_id"]}


async def neighbors(
    conn: Conn, frontier: list[dict[str, Any]], direction: str, rid: int | None
) -> list[dict[str, Any]]:
    queries: list[str] = []
    args: list[Any] = []
    for a, b, predicate in RELATIONS:
        source, target = (a, b) if direction == "after" else (b, a)
        ids = [n["data"][TYPES[source].key] for n in frontier if n["kind"] == source]
        if not ids:
            continue
        alias, other = ("a", "b") if direction == "after" else ("b", "a")
        key, dstkey = TYPES[source].key, TYPES[target].key
        # Limit each relation, keeping total fanout count for grouping and truncation.
        queries.append(
            f"(SELECT '{target}' AS kind, to_jsonb({other}) AS data, {scope(target, other)} AS scope_id, '{source}:' || {alias}.{key}::text AS parent, count(*) OVER (PARTITION BY {alias}.{key}) AS total FROM {TYPES[a].table} a JOIN {TYPES[b].table} b ON {predicate} WHERE {alias}.{key}=ANY(%s) AND (%s::bigint IS NULL OR {scope(target, other)} IS NULL OR {scope(target, other)}=%s OR {scope(target, other)} IN (SELECT id FROM sim_runs WHERE kind='baseline')) ORDER BY {other}.{dstkey} LIMIT 241)"
        )
        args.extend((ids, rid, rid))
    return await fetch_all(conn, " UNION ALL ".join(queries), args) if queries else []
