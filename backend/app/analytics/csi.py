"""T-248: агрегаты CSI; одна read-only MVCC транзакция задаётся API caller."""

from __future__ import annotations

import re
from collections import defaultdict
from typing import Any

from app.analytics.branch_scope import branch_predicate
from app.analytics.cabinet_scope import CabinetScope
from app.analytics.csi_statistics import quartiles, spearman
from app.api.common import fetch_all, fetch_one
from app.trace.privacy import mask
from app.trace.store import Conn

WAIT_BUCKETS = ["0-5", "5-15", "15-30", "30+"]
REDIRECTS_BUCKETS = ["0", "1", "2+"]

# Значения source observation из receipt отделены от native received_sim.
# Для scoped probabilities используются только immutable cohort snapshots.
OBSERVATIONS = """
 SELECT s.id,s.public_id,s.run_id,s.received_sim,cr.csi_no,cr.branch_id,
   b.code AS branch_code,b.name_ru AS branch_name,b.region_code,b.product_line_codes,
   cr.employee_id,nullif(trim(cr.position),'') AS position,
   CASE WHEN cr.wait_min BETWEEN 0 AND 999999.99 THEN cr.wait_min END AS wait_min,
   CASE WHEN cr.service_min BETWEEN 0 AND 999999.99 THEN cr.service_min END AS service_min,
   CASE WHEN cr.redirects>=0 THEN cr.redirects END AS redirects,
   CASE WHEN s.classification->>'criticality' IN ('high','medium','low') THEN s.classification->>'criticality' END AS criticality,
   coalesce(c.product_line_code,s.product_line_code) AS product_line_code,
   CASE WHEN c.id IS NOT NULL THEN 'cohort_declared' WHEN s.product_line_code IS NOT NULL THEN 'classified' ELSE 'unknown' END AS direction_source,
   c.id AS cohort_id,m.response_at
 FROM csi_responses cr JOIN signals s ON s.id=cr.signal_id
 LEFT JOIN branches b ON b.id=cr.branch_id
 LEFT JOIN csi_cohort_members m ON m.signal_id=s.id AND m.run_id=s.run_id
 LEFT JOIN csi_cohorts c ON c.id=m.cohort_id AND c.run_id=s.run_id AND c.branch_id=cr.branch_id
 WHERE s.origin IS DISTINCT FROM 'proactive'
"""


def observation_scope(scope: CabinetScope, branch_id: int | None, region: str | None) -> tuple[str, list[Any]]:
    where, args = scope.predicate("o")
    directory, directory_args = branch_predicate(scope.lines, region, alias="o")
    where += " AND " + directory
    args.extend(directory_args)
    if branch_id is not None:
        where += " AND o.branch_id=%s"
        args.append(branch_id)
    return where, args


async def probabilities(conn: Conn, scope: CabinetScope, branch_id: int | None, region: str | None) -> dict[str, Any]:
    where, args = branch_predicate(scope.lines, region)
    where += " AND c.window_start<%s AND c.window_end>%s"
    args.extend((scope.now, scope.since))
    if scope.run_ids is not None:
        where += " AND c.run_id=ANY(%s)"
        args.append(scope.run_ids)
    if scope.lines is not None:
        where += " AND c.product_line_code=ANY(%s)"
        args.append(scope.lines)
    if branch_id is not None:
        where += " AND c.branch_id=%s"
        args.append(branch_id)
    row = await fetch_one(
        conn,
        f"""
      WITH candidate AS MATERIALIZED (SELECT c.* FROM v_csi_cohort_integrity c JOIN branches b ON b.id=c.branch_id WHERE {where}),
      eligible AS MATERIALIZED (SELECT * FROM candidate WHERE is_complete AND window_start>=%s AND window_end<=%s),
      cells AS MATERIALIZED (SELECT v.id,v.wait_bucket,v.redirects_bucket,v.visits,count(m.signal_id) AS complaints
        FROM eligible c JOIN csi_cohort_visits v ON v.cohort_id=c.id
        LEFT JOIN csi_cohort_members m ON m.cohort_id=v.cohort_id AND m.wait_bucket=v.wait_bucket AND m.redirects_bucket=v.redirects_bucket
        GROUP BY v.id),
      buckets AS (SELECT 'wait' AS axis,wait_bucket AS bucket,sum(visits) AS visits,sum(complaints) AS complaints FROM cells GROUP BY wait_bucket
        UNION ALL SELECT 'redirects',redirects_bucket,sum(visits),sum(complaints) FROM cells GROUP BY redirects_bucket)
      SELECT (SELECT count(*) FROM candidate) AS overlapping_cohorts,
        (SELECT count(*) FROM candidate WHERE NOT is_complete) AS incomplete_cohorts,
        (SELECT count(*) FROM candidate WHERE window_start<%s OR window_end>%s) AS partial_window_cohorts,
        (SELECT count(*) FROM eligible) AS complete_cohorts,
        (SELECT bool_and(is_synthetic) FROM eligible) AS synthetic,
        (SELECT bool_or(is_synthetic) FROM eligible) AS any_synthetic,
        (SELECT sum(member_count)::bigint FROM eligible) AS sample_complaints,
        (SELECT sum(sample_visits)::bigint FROM eligible) AS sample_visits,
        (SELECT jsonb_agg(to_jsonb(buckets)) FROM buckets) AS buckets
    """,
        [*args, scope.since, scope.now, scope.since, scope.now],
    )  # noqa: S608 — identifiers внутренние, filters параметризованы.
    assert row is not None
    groups = {(r["axis"], r["bucket"]): r for r in row.pop("buckets") or []}
    has_sample = row["complete_cohorts"] > 0
    any_synthetic = row.pop("any_synthetic")
    mixed = has_sample and row["synthetic"] is False and any_synthetic is True
    if mixed:
        row["synthetic"] = None
    result: dict[str, Any] = {
        **row,
        "time_basis": "cohort_response_at",
        "scope": "registered_complete_cohorts",
        "legacy_denominators_usable": False,
        "mixed_sources": mixed,
    }
    for axis, labels in [("wait", WAIT_BUCKETS), ("redirects", REDIRECTS_BUCKETS)]:
        values: list[dict[str, Any]] = []
        for label in labels:
            cell = groups.get((axis, label))
            visits = int(cell["visits"]) if cell else None
            complaints = int(cell["complaints"]) if cell else None
            probability = complaints / visits if visits and complaints is not None and complaints <= visits else None
            values.append({"bucket": label, "complaints": complaints, "visits": visits, "probability": probability})
        rho, n = spearman((index, value["probability"]) for index, value in enumerate(values))
        result[axis] = {"buckets": values, "spearman": rho, "n_buckets": n}
    if not has_sample:
        result["sample_complaints"] = result["sample_visits"] = result["synthetic"] = None
    return result


async def analytics(
    conn: Conn,
    scope: CabinetScope,
    *,
    branch_id: int | None,
    region: str | None,
    limit: int = 50,
    offset: int = 0,
    scatter_limit: int = 1000,
) -> dict[str, Any]:
    where, args = observation_scope(scope, branch_id, region)
    selected = f"WITH observations AS ({OBSERVATIONS}), selected AS MATERIALIZED (SELECT o.* FROM observations o WHERE {where})"
    row = await fetch_one(
        conn,
        selected
        + """,
      positions AS (SELECT position,count(*) AS complaints,count(DISTINCT employee_id) AS known_employees,
        count(*) FILTER(WHERE employee_id IS NULL) AS anonymous_complaints FROM selected GROUP BY position),
      heat AS (SELECT region_code,count(*) AS complaints FROM selected GROUP BY region_code),
      top AS (SELECT branch_id,branch_code,branch_name,region_code,count(*) AS complaints,avg(wait_min) AS average_wait_min
        FROM selected WHERE branch_id IS NOT NULL GROUP BY branch_id,branch_code,branch_name,region_code ORDER BY complaints DESC,branch_code LIMIT 10)
      SELECT count(*) AS complaints,count(*) FILTER(WHERE branch_id IS NOT NULL) AS branch_known,
        count(*) FILTER(WHERE product_line_code IS NOT NULL) AS direction_known,
        count(*) FILTER(WHERE employee_id IS NOT NULL) AS employee_known,
        count(*) FILTER(WHERE cohort_id IS NOT NULL) AS cohort_bound,
        count(*) FILTER(WHERE wait_min IS NOT NULL AND service_min IS NOT NULL) AS scatter_total,
        (SELECT jsonb_agg(to_jsonb(positions) ORDER BY complaints DESC,position NULLS LAST) FROM positions) AS positions,
        (SELECT jsonb_agg(to_jsonb(heat) ORDER BY complaints DESC,region_code NULLS LAST) FROM heat) AS heatmap,
        (SELECT jsonb_agg(to_jsonb(top) ORDER BY complaints DESC,branch_code) FROM top) AS top_branches
      FROM selected
    """,
        args,
    )  # noqa: S608
    assert row is not None
    table = await fetch_all(
        conn,
        selected
        + """
      SELECT x.public_id AS signal_ref,x.csi_no,x.received_sim,x.response_at,x.branch_id,x.branch_code,x.region_code,
        x.product_line_code,x.direction_source,x.position,x.wait_min,x.service_min,x.redirects,x.criticality,cr.complaint_ru
      FROM selected x JOIN csi_responses cr ON cr.signal_id=x.id ORDER BY x.received_sim DESC,x.id DESC LIMIT %s OFFSET %s
    """,
        [*args, limit, offset],
    )  # noqa: S608
    scatter = await fetch_all(
        conn,
        selected
        + """
      SELECT public_id AS signal_ref,wait_min,service_min,criticality,branch_code
      FROM selected WHERE wait_min IS NOT NULL AND service_min IS NOT NULL ORDER BY received_sim DESC,id DESC LIMIT %s
    """,
        [*args, scatter_limit],
    )  # noqa: S608
    directory, directory_args = branch_predicate(scope.lines, region)
    if branch_id is not None:
        directory += " AND b.id=%s"
        directory_args.append(branch_id)
    staff = await fetch_all(
        conn,
        selected
        + f"""
      SELECT e.position_since_sim,(e.id,e.branch_id) IN(SELECT employee_id,branch_id FROM selected WHERE employee_id IS NOT NULL AND branch_id IS NOT NULL) AS has_complaint
      FROM employees e JOIN branches b ON b.id=e.branch_id WHERE e.is_active AND {directory}
    """,
        [*args, *directory_args],
    )  # noqa: S608
    series: dict[bool, list[int | None]] = defaultdict(list)
    for employee in staff:
        since = employee["position_since_sim"]
        tenure = (scope.now - since).days if since is not None and since <= scope.now else None
        series[employee["has_complaint"]].append(tenure)
    tenure_groups = []
    for has_complaint, code in [(True, "with_complaints"), (False, "without_complaints")]:
        sample = series[has_complaint]
        n, qs = quartiles(sample)
        tenure_groups.append(
            {
                "group": code,
                "employees": len(sample),
                "known_tenure": n,
                "minimum": min((value for value in sample if value is not None), default=None),
                "maximum": max((value for value in sample if value is not None), default=None),
                "q1": qs[0] if qs else None,
                "median": qs[1] if qs else None,
                "q3": qs[2] if qs else None,
            }
        )
    for item in [*table, *scatter]:
        for key in ("wait_min", "service_min"):
            item[key] = float(item[key]) if item[key] is not None else None
    for item in table:
        item["summary"] = mask(item.pop("complaint_ru"), 500)
        item["position"] = mask(item["position"], 120) if item["position"] is not None else None
        if not re.fullmatch(r"CSI-\d{3,6}", item["csi_no"]):
            item["csi_no"] = None
    positions = row.pop("positions") or []
    for position in positions:
        position["position"] = mask(position["position"], 120) if position["position"] is not None else None
    heatmap, top = row.pop("heatmap") or [], row.pop("top_branches") or []
    for branch in top:
        branch["branch_name"] = mask(branch["branch_name"], 200)
    total = row["complaints"]
    return {
        "scope": {
            "role": scope.role,
            "visibility": scope.visibility,
            "product_lines": scope.lines,
            "run_ids": scope.run_ids,
            "period": scope.period,
            "since_sim": scope.since,
            "sim_time": scope.now,
            "branch_id": branch_id,
            "region_code": region,
        },
        "coverage": {**row, "uncohorted": total - row["cohort_bound"], "time_basis": "native_received_sim"},
        "complaints": {
            "items": table,
            "total": total,
            "next_offset": offset + len(table) if offset + len(table) < total else None,
        },
        "scatter": {
            "items": scatter,
            "total": row["scatter_total"],
            "shown": len(scatter),
            "has_more": len(scatter) < row["scatter_total"],
        },
        "positions": positions,
        "tenure": {
            "groups": tenure_groups,
            "unit": "days",
            "as_of_sim": scope.now,
            "population": "current_active_branch_roster",
        },
        "heatmap": heatmap,
        "top_branches": top,
        "probabilities": await probabilities(conn, scope, branch_id, region),
    }
