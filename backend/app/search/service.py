"""Universal search, parameterized and run-scoped (ТЗ 28.2)."""

from __future__ import annotations

from collections import Counter
from time import perf_counter
from typing import Any
from urllib.parse import quote

from app.api.common import fetch_all
from app.search.grammar import PREFIXES, parse
from app.trace.privacy import mask
from app.trace.relations import TYPES
from app.trace.store import Conn, allowed_run, scope

SEARCH_KINDS = (*PREFIXES.values(), "rule", "error_code")


async def search_objects(conn: Conn, q: str, run_id: str = "current", limit: int = 50) -> dict[str, Any]:
    start = perf_counter()
    parsed = parse(q)
    mode, kind, normalized = parsed["mode"], parsed["kind"], str(parsed["normalized"])
    rid = await allowed_run(conn, "all" if mode == "id" and run_id == "current" else run_id)
    queries, args = [], []
    for k in SEARCH_KINDS:
        spec = TYPES[k]
        textcol = {"signal": "text", "incident": "title", "post": "text"}.get(k)
        expression = f"t.{textcol}" if textcol else f"t.{spec.public}::text"
        rank = "0::real"
        snippet = "NULL::text"
        if mode == "text":
            if not textcol:
                continue
            predicate = f"(to_tsvector('russian', {expression}) @@ plainto_tsquery('russian', %s) OR {expression} %% %s OR {expression} ILIKE %s)"
            values: list[Any] = [normalized, normalized, "%" + normalized.replace("%", "\\%").replace("_", "\\_") + "%"]
            rank = f"ts_rank(to_tsvector('russian', {expression}), plainto_tsquery('russian', %s)) + similarity({expression}, %s)"
            # SELECT placeholders occur before WHERE placeholders.
            snippet = f"ts_headline('russian', {expression}, plainto_tsquery('russian', %s), 'StartSel=[, StopSel=], MaxWords=25, MinWords=10')"
            prefix_args: list[Any] = [normalized, normalized, normalized]
        else:
            prefix_args = []
            values = [normalized]
            if kind == "number":
                if spec.key != "id" and k != "csi":
                    continue
                predicate = f"t.{spec.key}=%s"
                values = [int(normalized)]
                if k == "branch":
                    predicate = "t.code=ANY(%s)"
                    values = [[f"{int(normalized):04d}", f"VSP-{int(normalized):04d}"]]
            elif kind == "tracking":
                if k != "signal":
                    continue
                predicate = "t.tracking_token=%s"
            elif kind == "correlation":
                if k != "ledger":
                    continue
                predicate = "t.correlation_id=%s::uuid"
            elif mode == "hints":
                if k != "client":
                    continue
                if normalized.startswith("@"):
                    predicate = "EXISTS (SELECT 1 FROM jsonb_path_query(t.social_handles, '$.** ? (@.type() == \"string\")') h(value) WHERE lower(h.value #>> '{}')=lower(%s))"
                elif normalized.startswith("*"):
                    predicate = "EXISTS (SELECT 1 FROM client_products p WHERE p.client_id=t.id AND p.card_last4=%s)"
                    values = [normalized.replace("*", "").strip()]
                else:
                    predicate = "replace(t.contacts->>'phone_masked', ' ', '')=replace(%s, ' ', '')"
            else:
                if k != kind:
                    continue
                predicate = f"t.{spec.public}=%s"
                if k == "branch":
                    predicate = "t.code=ANY(%s)"
                    values = [[normalized, normalized.removeprefix("VSP-")]]
        queries.append(
            f"(SELECT '{k}' AS kind, t.{spec.public}::text AS ref, {expression} AS title, to_jsonb(t)->>'status' AS status, {scope(k)} AS scope_id, {rank} AS rank, {snippet} AS snippet FROM {spec.table} t WHERE {predicate} AND (%s::bigint IS NULL OR {scope(k)} IS NULL OR {scope(k)}=%s OR {scope(k)} IN (SELECT id FROM sim_runs WHERE kind='baseline')) ORDER BY rank DESC, t.{spec.key} LIMIT %s)"
        )
        args.extend([*prefix_args, *values, rid, rid, limit])
    rows = (
        await fetch_all(
            conn,
            "SELECT * FROM ("
            + " UNION ALL ".join(queries)
            + ") hits ORDER BY rank DESC, CASE kind WHEN 'signal' THEN 0 WHEN 'incident' THEN 1 WHEN 'client' THEN 2 ELSE 3 END, ref LIMIT %s",
            [*args, limit],
        )
        if queries
        else []
    )
    if mode == "hints" and rows:
        client_ids = [int(row["ref"].removeprefix("CL-")) for row in rows]
        signals = await fetch_all(
            conn,
            "SELECT 'signal' AS kind, s.public_id AS ref, s.text AS title, s.status, s.run_id AS scope_id, NULL::text AS snippet FROM signals s WHERE s.client_id=ANY(%s) AND (%s::bigint IS NULL OR s.run_id=%s OR s.run_id IN (SELECT id FROM sim_runs WHERE kind='baseline')) ORDER BY s.received_at DESC, s.id DESC LIMIT %s",
            (client_ids, rid, rid, max(0, limit - len(rows))),
        )
        rows.extend(signals)
    for row in rows:
        if row["kind"] == "branch" and not row["ref"].startswith("VSP-"):
            row["ref"] = "VSP-" + row["ref"]
    hits = [
        {
            "kind": r["kind"],
            "ref": r["ref"],
            "title_ru": mask(r["title"], 200),
            "run_id": f"SR-{r['scope_id']:04d}" if r["scope_id"] else "baseline",
            "status": r["status"],
            "snippet_ru": mask(r["snippet"], 300) if mode == "text" else None,
            "trace_href": f"/trace/{r['kind']}/{quote(r['ref'], safe='')}",
        }
        for r in rows
    ]
    # Tracking tokens and customer hints must not be echoed in responses or browser history.
    safe_parsed = {**parsed, "normalized": mask(normalized), "ref": None if kind == "tracking" else parsed["ref"]}
    if kind == "tracking":
        safe_parsed["normalized"] = "[токен скрыт]"
    return {
        "query": "[токен скрыт]" if kind == "tracking" else mask(q),
        "parsed": safe_parsed,
        "hits": hits,
        "counts_by_kind": dict(Counter(h["kind"] for h in hits)),
        "took_ms": round((perf_counter() - start) * 1000),
    }
