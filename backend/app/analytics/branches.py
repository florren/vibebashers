"""T-248: сеть/давление/зоны закрытия — факты, без финансовых эффектов."""

from __future__ import annotations

import math
from typing import Any

from fastapi import HTTPException

from app.analytics.branch_scope import branch_predicate, directory_metadata
from app.analytics.cabinet_scope import CabinetScope
from app.api.common import fetch_all, fetch_one
from app.trace.store import Conn

# Явное cohort direction — provenance sample, а не запись классификации агента.
FACTS = (
    "v_cabinet_signal_facts f LEFT JOIN csi_cohort_members cm ON cm.signal_id=f.id AND cm.run_id=f.run_id "
    "LEFT JOIN csi_cohorts cc ON cc.id=cm.cohort_id AND cc.run_id=f.run_id"
)


def signal_scope(scope: CabinetScope) -> tuple[str, list[Any]]:
    where, args = scope.predicate("f")
    return where.replace("f.product_line_code = ANY", "coalesce(cc.product_line_code,f.product_line_code) = ANY"), args


async def network(conn: Conn, lines: list[str] | None, region: str | None, months: int) -> dict[str, Any]:
    directory = await directory_metadata(conn)
    if lines is None:
        rows = await fetch_all(
            conn,
            "SELECT month,sum(open_count)::int AS open_count,sum(closed_count)::int AS closed_count,"
            "sum(opened_in_month)::int AS opened_in_month,sum(closed_in_month)::int AS closed_in_month "
            "FROM branch_network_history WHERE month >= (SELECT max(month) FROM branch_network_history) "
            "-make_interval(months=>%s) AND (%s::text IS NULL OR region_code=%s) GROUP BY month ORDER BY month",
            (months - 1, region, region),
        )
        return {
            "items": rows,
            "synthetic": directory["synthetic"],
            "basis": "stored_global_history",
            "directory": directory,
        }
    # Агрегированный legacy history не содержит направления. Строгий subset
    # восстанавливается только из явных дат snapshot, с отдельным provenance.
    if directory["as_of_sim"] is None:
        return {
            "items": [],
            "synthetic": directory["synthetic"],
            "basis": "unavailable_snapshot_time",
            "directory": directory,
        }
    where, args = branch_predicate(lines, region)
    rows = await fetch_all(
        conn,
        f"""WITH selected AS MATERIALIZED (SELECT * FROM branches b WHERE {where}),
        months AS (SELECT generate_series((date_trunc('month',%s::timestamptz AT TIME ZONE 'Europe/Moscow') AT TIME ZONE 'Europe/Moscow')-make_interval(months=>%s),
           (date_trunc('month',%s::timestamptz AT TIME ZONE 'Europe/Moscow') AT TIME ZONE 'Europe/Moscow'),interval '1 month') AS m)
        SELECT (m AT TIME ZONE 'Europe/Moscow')::date AS month,
          CASE WHEN count(*) FILTER(WHERE b.id IS NOT NULL AND (opened_sim IS NULL OR (branch_status='closed' AND closed_sim IS NULL)))=0
            THEN count(*) FILTER(WHERE opened_sim<m+interval '1 month' AND (closed_sim IS NULL OR closed_sim>=m+interval '1 month'))::int END AS open_count,
          CASE WHEN count(*) FILTER(WHERE branch_status='closed' AND closed_sim IS NULL)=0
            THEN count(*) FILTER(WHERE closed_sim<m+interval '1 month')::int END AS closed_count,
          CASE WHEN count(*) FILTER(WHERE b.id IS NOT NULL AND opened_sim IS NULL)=0
            THEN count(*) FILTER(WHERE opened_sim>=m AND opened_sim<m+interval '1 month')::int END AS opened_in_month,
          CASE WHEN count(*) FILTER(WHERE branch_status='closed' AND closed_sim IS NULL)=0
            THEN count(*) FILTER(WHERE closed_sim>=m AND closed_sim<m+interval '1 month')::int END AS closed_in_month
        FROM months LEFT JOIN selected b ON TRUE GROUP BY m ORDER BY m""",
        [*args, directory["as_of_sim"], months - 1, directory["as_of_sim"]],
    )  # noqa: S608 — internal SQL identifiers only.
    return {
        "items": rows,
        "synthetic": directory["synthetic"],
        "basis": "scoped_directory_lifecycle",
        "directory": directory,
    }


async def deficit_threshold(conn: Conn) -> float | None:
    row = await fetch_one(conn, "SELECT value FROM settings WHERE key='csi_analytics'")
    value = row["value"] if row else None
    if value is None:
        return None
    if not isinstance(value, dict):
        raise HTTPException(409, "Некорректный settings.csi_analytics")
    threshold = value.get("deficit_signals_per_open_branch")
    if threshold is None:
        return None
    if type(threshold) not in (int, float):
        raise HTTPException(409, "Порог дефицита ВСП должен быть конечным положительным числом")
    try:
        number = float(threshold)
    except OverflowError:
        raise HTTPException(409, "Порог дефицита ВСП превышает числовой диапазон") from None
    if not math.isfinite(number) or number <= 0:
        raise HTTPException(409, "Порог дефицита ВСП должен быть конечным положительным числом")
    return number


async def analytics(conn: Conn, scope: CabinetScope, region: str | None, limit: int, offset: int) -> dict[str, Any]:
    directory_where, directory_args = branch_predicate(scope.lines, region)
    signals_where, signals_args = signal_scope(scope)
    if region is not None:
        signals_where += " AND f.region_code=%s"
        signals_args.append(region)
    threshold = await deficit_threshold(conn)
    pressure = await fetch_all(
        conn,
        f"""WITH directory AS (SELECT b.region_code,count(*)::int AS branches,
           count(*) FILTER(WHERE branch_status='open')::int AS open_branches,
           count(*) FILTER(WHERE branch_status='closed')::int AS closed_branches,
           count(*) FILTER(WHERE branch_status IS NULL)::int AS unknown_status_branches
           FROM branches b WHERE {directory_where} GROUP BY b.region_code),
        signals AS (SELECT f.region_code,count(*)::int AS signals FROM {FACTS} WHERE {signals_where} GROUP BY f.region_code)
        SELECT coalesce(d.region_code,s.region_code) AS region_code,coalesce(branches,0) AS branches,
           coalesce(open_branches,0) AS open_branches,coalesce(closed_branches,0) AS closed_branches,coalesce(unknown_status_branches,0) AS unknown_status_branches,
           coalesce(signals,0) AS signals FROM directory d FULL JOIN signals s ON s.region_code=d.region_code
        ORDER BY coalesce(signals,0) DESC,coalesce(d.region_code,s.region_code) NULLS LAST""",
        [*directory_args, *signals_args],
    )  # noqa: S608
    for row in pressure:
        ratio = (
            row["signals"] / row["open_branches"]
            if row["open_branches"] and not row["unknown_status_branches"]
            else None
        )
        row["signals_per_open_branch"] = ratio
        row["deficit"] = ratio > threshold if ratio is not None and threshold is not None else None
    # Регион И город — точное совпадение; неоднозначное/отсутствующее geo не
    # дополняется догадкой. Один сигнал может относиться к нескольким closed ВСП
    # в одном городе: это per-branch таблица, её строки не суммируются в unique total.
    closed_sql = f"""WITH selected AS MATERIALIZED (
        SELECT f.*,coalesce(s.geo->>'city_id',c.city_id::text) AS city_id
        FROM {FACTS} JOIN signals s ON s.id=f.id LEFT JOIN clients c ON c.id=s.client_id WHERE {signals_where}),
      closed AS MATERIALIZED (SELECT b.* FROM branches b WHERE {directory_where}
        AND b.branch_status='closed' AND b.closed_sim<=%s AND b.closed_sim+interval '90 days'>%s),
      zones AS (SELECT b.id AS branch_id,b.code AS branch_code,b.region_code,b.city_id,b.closed_sim,
        count(s.id)::int AS signals,min(s.received_sim) AS first_signal_sim,max(s.received_sim) AS last_signal_sim
        FROM closed b LEFT JOIN selected s ON s.region_code=b.region_code AND s.city_id=b.city_id::text
          AND s.received_sim>=b.closed_sim AND s.received_sim<b.closed_sim+interval '90 days'
        GROUP BY b.id,b.code,b.region_code,b.city_id,b.closed_sim)
      SELECT *,count(*) OVER()::int AS total FROM zones ORDER BY signals DESC,branch_code LIMIT %s OFFSET %s"""
    zones = await fetch_all(conn, closed_sql, [*signals_args, *directory_args, scope.now, scope.since, limit, offset])  # noqa: S608
    # Отдельный bounded count сохраняет total и при offset за концом списка.
    count = await fetch_one(
        conn,
        f"SELECT count(*)::int AS n FROM branches b WHERE {directory_where} AND b.branch_status='closed' AND b.closed_sim<=%s AND b.closed_sim+interval '90 days'>%s",
        [*directory_args, scope.now, scope.since],
    )  # noqa: S608
    total = count["n"] if count else 0
    for row in zones:
        row.pop("total")
    return {
        "scope": {
            "run_ids": scope.run_ids,
            "product_lines": scope.lines,
            "period": scope.period,
            "since_sim": scope.since,
            "sim_time": scope.now,
            "region_code": region,
            "role": scope.role,
            "visibility": scope.visibility,
        },
        "pressure": pressure,
        "deficit_threshold": threshold,
        "deficit_basis": "signals_per_open_branch_strictly_above_configured_threshold",
        "network": await network(conn, scope.lines, region, 12),
        "closure_zones": {
            "items": zones,
            "total": total,
            "next_offset": offset + len(zones) if offset + len(zones) < total else None,
            "window_days": 90,
            "basis": "same_region_and_city_after_closure",
        },
        "directory": await directory_metadata(conn),
    }
