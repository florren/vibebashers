"""T-241: сортируемая лента без свободных meta, контактов и source_url."""

from __future__ import annotations

import re
from typing import Any

from app.analytics.cabinet_scope import CabinetScope
from app.api.common import fetch_all, fetch_one
from app.corpus.reviews import project_platform
from app.trace.privacy import mask
from app.trace.store import Conn

SORTS = {
    "date": "f.received_sim",
    "level": "CASE f.criticality WHEN 'high' THEN 3 WHEN 'medium' THEN 2 WHEN 'low' THEN 1 ELSE 0 END",
    "region": "f.region_code",
}


async def signals(
    conn: Conn,
    scope: CabinetScope,
    *,
    region: str | None,
    status: str | None,
    channel: str | None,
    red_words: bool | None,
    sort: str,
    direction: str,
    limit: int,
    offset: int,
) -> dict[str, Any]:
    where, args = scope.predicate("f")
    for column, value in [("region_code", region), ("status", status), ("channel_code", channel)]:
        if value is not None:
            where += f" AND f.{column}=%s"
            args.append(value)
    if red_words is True:
        where += " AND ('red_word'=ANY(f.flags))"
    elif red_words is None and scope.role == "compliance_officer":
        # Preset объединяет только существующие классы. False явно снимает
        # presentation filter; это не ограничение полномочий пользователя.
        where += " AND ('red_word'=ANY(f.flags) OR f.signal_type='legal_regulatory' OR f.id IN (SELECT x.signal_id FROM incident_signals x JOIN incidents i ON i.id=x.incident_id JOIN signals s ON s.id=x.signal_id AND s.run_id=i.run_id WHERE i.incident_type='misselling'))"
    total = await fetch_one(conn, f"SELECT count(*) AS total FROM v_cabinet_signal_facts f WHERE {where}", args)  # noqa: S608
    order = (
        SORTS[sort]
        + " "
        + ("ASC" if direction == "asc" else "DESC")
        + " NULLS LAST,f.id "
        + ("ASC" if direction == "asc" else "DESC")
    )
    # При stale stats selected может оцениваться как одна строка: materialized
    # edges исключают декартово run-соединение. Индексируемый JSONB map заменяет
    # повторный nested scan агрегированных связей на каждый сигнал при той же ошибке оценки.
    rows = await fetch_all(
        conn,
        f"""
      WITH selected AS MATERIALIZED (SELECT f.* FROM v_cabinet_signal_facts f WHERE {where}
        ORDER BY {order} LIMIT %s OFFSET %s), selected_edges AS MATERIALIZED (
        SELECT x.signal_id,x.incident_id,f.run_id FROM selected f
        JOIN incident_signals x ON x.signal_id=f.id
      ), linked AS MATERIALIZED (
        SELECT x.signal_id,min(i.sla_due_sim) FILTER(WHERE i.status NOT IN ('closed','resolved','rejected','duplicate')) AS sla_due_sim,
          jsonb_agg(jsonb_build_object('id',i.id,'public_id',i.public_id,'status',i.status) ORDER BY i.id) AS incidents
        FROM selected_edges x JOIN incidents i ON i.id=x.incident_id AND i.run_id=x.run_id GROUP BY x.signal_id
      ), link_map AS MATERIALIZED (
        SELECT jsonb_object_agg(signal_id,jsonb_build_object('sla_due_sim',sla_due_sim,'incidents',incidents)) AS by_signal FROM linked
      )
      SELECT f.*,s.classification->>'problem_summary' AS problem_summary,
        coalesce(s.classification->>'summary_ru',s.text) AS summary,
        (m.by_signal->f.id::text->>'sla_due_sim')::timestamptz AS sla_due_sim,m.by_signal->f.id::text->'incidents' AS incidents
      FROM selected f JOIN signals s ON s.id=f.id CROSS JOIN link_map m ORDER BY {order}
    """,
        [*args, limit, offset],
    )  # noqa: S608 — сортировка из закрытого allowlist, значения только params.
    for row in rows:
        summary = row.pop("problem_summary") or row.pop("summary")
        row.pop("summary", None)
        row["summary"] = mask(" ".join(re.split(r"(?<=[.!?])\s+", str(summary or ""))[:2]), 500)
        row["red_words"] = [mask(x, 100) for x in row["red_words"]]
        row["source_platform"] = project_platform(row.pop("source_platform"))
        row["incidents"] = row["incidents"] or []
    count = int((total or {})["total"])
    return {"items": rows, "total": count, "next_offset": offset + len(rows) if offset + len(rows) < count else None}
