"""Срез финансового эффекта: записанная модель и отдельные сценарные допущения (ADR-0013)."""

from __future__ import annotations

import datetime as dt
from decimal import ROUND_HALF_UP, Decimal
from typing import Any, Literal

from app.api.common import fetch_all, fetch_one
from app.errors import Problem


def bounds(
    period: str, now: dt.datetime, start: dt.datetime | None, end: dt.datetime | None
) -> tuple[dt.datetime | None, dt.datetime | None]:
    if (start is None) != (end is None):
        raise Problem(422, "Укажите обе границы периода")
    if start is not None and end is not None:
        if start.utcoffset() is None or end.utcoffset() is None:
            raise Problem(422, "Границы периода должны содержать часовой пояс")
        if end <= start or end - start > dt.timedelta(days=366):
            raise Problem(422, "Период должен быть положительным и не больше 366 дней")
        return start, end
    now = now.astimezone(dt.UTC)
    midnight = now.replace(hour=0, minute=0, second=0, microsecond=0)
    if period == "day":
        return midnight, midnight + dt.timedelta(days=1)
    if period in ("week", "month"):
        return midnight - dt.timedelta(days=6 if period == "week" else 29), midnight + dt.timedelta(days=1)
    return None, None


def money(value: Any) -> float:
    return float(Decimal(str(value or 0)).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP))


# Одна строка на инцидент; EXISTS не размножает эффект при нескольких алертах.
BASE = """
select i.id as incident_id, i.public_id, i.incident_type, i.product_code,
       coalesce(p.name_ru, i.product_code, '—') as product_name,
       c.public_id as client_public_id, c.segment_code as client_segment,
       c.clv_estimate_rub::float as client_ltv_rub, i.status,
       coalesce(i.resolved_sim, i.closed_sim) as resolved_sim,
       e.breakdown, e.computed_sim,
       e.incident_id is null as missing,
       (e.incident_id is not null and e.computed_at < i.updated_at) as stale,
       coalesce(e.prevented_loss_rub, 0) as saved,
       coalesce(e.refund_amount_rub, 0) as refund,
       case when i.primary_client_id is not null and coalesce(i.outcome_class, '') <> 'churned'
            then coalesce(e.rate_rub + e.premium_addon_rub, 0) else 0 end as scenario_base,
       case when i.incident_type = 'misselling' and coalesce(i.outcome_class, '') <> 'churned'
             and exists (select 1 from compliance_alerts a where a.incident_id = i.id and a.decision = 'go')
            then 1 else 0 end as fine_cases
from incidents i
left join incident_economics e on e.incident_id = i.id and e.run_id = i.run_id
left join clients c on c.id = i.primary_client_id
left join products p on p.code = i.product_code
where i.status in ('resolved', 'closed')
  and coalesce(i.resolved_sim, i.closed_sim) is not null
"""


ProductMode = Literal["all", "include", "exclude"]


def product_filter(codes: tuple[str, ...], mode: ProductMode, column: str) -> tuple[str, list[Any]]:
    """Колонка задаётся кодом; значения продуктов всегда передаются параметром SQL."""
    if column not in ("i.product_code", "r.product_code"):
        raise ValueError("Неизвестная колонка продукта")
    if mode == "all" or (mode == "exclude" and not codes):
        return "", []
    if not codes:
        return " and false", []
    if mode == "include":
        return f" and {column} = any(%s)", [list(codes)]
    return f" and ({column} is null or not ({column} = any(%s)))", [list(codes)]


def scope(
    run_id: int | None,
    start: dt.datetime | None,
    end: dt.datetime | None,
    product_codes: tuple[str, ...] = (),
    product_mode: ProductMode = "all",
) -> tuple[str, list[Any]]:
    # Отсутствие текущего запуска не означает «все запуски».
    sql = BASE + " and i.run_id = %s"
    args: list[Any] = [run_id]
    if start is not None:
        sql += " and coalesce(i.resolved_sim, i.closed_sim) >= %s and coalesce(i.resolved_sim, i.closed_sim) < %s"
        args.extend([start, end])
    clause, values = product_filter(product_codes, product_mode, "i.product_code")
    return sql + clause, args + values


async def total(
    conn: Any,
    *,
    run_id: int | None,
    period: str,
    start: dt.datetime | None,
    end: dt.datetime | None,
    probability: float,
    fine: float,
    offset: int,
    limit: int,
    product_codes: tuple[str, ...] = (),
    product_mode: ProductMode = "all",
) -> dict[str, Any]:
    sql, args = scope(run_id, start, end, product_codes, product_mode)
    # Округление каждого кейса совпадает с детализацией; чистый эффект допускает отрицательные значения.
    cte = (
        "with cases as ("
        + sql
        + """), valued as (
       select *, round(scenario_base * %s::numeric / 100, 2) as scenario_saved,
                 fine_cases * %s::numeric as scenario_fine from cases)
    """
    )
    params = [*args, probability, fine]
    agg = await fetch_one(
        conn,
        cte
        + """
      select count(*)::int as incidents_resolved,
             count(*) filter (where missing)::int as missing_calculations,
             count(*) filter (where stale)::int as stale_calculations,
             coalesce(sum(saved), 0) as total_saved_rub, coalesce(sum(refund), 0) as refund_rub,
             coalesce(sum(saved - refund), 0) as net_effect_rub,
             coalesce(sum(scenario_saved), 0) as scenario_saved_rub,
             coalesce(sum(scenario_saved - refund), 0) as scenario_net_rub,
             coalesce(sum(scenario_fine), 0) as scenario_fine_rub,
             coalesce(sum(scenario_saved + scenario_fine - refund), 0) as scenario_with_fine_net_rub,
             coalesce(sum(fine_cases), 0)::int as fine_cases
      from valued
    """,
        params,
    )
    assert agg is not None
    top = await fetch_one(
        conn,
        cte + "select product_name from valued group by product_name order by sum(saved) desc, product_name limit 1",
        params,
    )
    # Часовые бакеты для Live/дня, дневные для истории; никаких ORM-циклов по всему запуску.
    bucket = "hour" if period in ("live", "day") and start is None else "day"
    if period == "day":
        bucket = "hour"
    series = await fetch_all(
        conn,
        cte
        + """, grouped as (
          select date_trunc(%s, resolved_sim, 'UTC') as time, sum(saved) as saved_rub,
                 sum(saved - refund) as net_rub from valued group by 1)
          select time, sum(saved_rub) over (order by time) as saved_rub,
                 sum(net_rub) over (order by time) as net_rub from grouped order by time
        """,
        [*params, bucket],
    )
    items = await fetch_all(
        conn,
        cte
        + """
      select incident_id, public_id, incident_type, product_code, product_name, client_public_id,
             client_segment, client_ltv_rub, status, resolved_sim, missing, stale,
             saved as saved_rub, refund as refund_rub, saved - refund as net_rub,
             scenario_saved as scenario_saved_rub, scenario_fine as scenario_fine_rub
      from valued order by resolved_sim desc, incident_id desc limit %s offset %s
    """,
        [*params, limit, offset],
    )
    for k in list(agg):
        if k.endswith("_rub"):
            agg[k] = money(agg[k])
    return {
        **agg,
        "run_id": run_id,
        "period": period,
        "start_date": start,
        "end_date": end,
        "probability_percent": probability,
        "fine_per_case_rub": fine,
        "top_product_saved": top["product_name"] if top else None,
        "series": series,
        "items": items,
        "offset": offset,
        "next_offset": offset + limit if offset + limit < agg["incidents_resolved"] else None,
    }


async def detail(
    conn: Any, incident_id: str, run_id: int | None, probability: float = 100, fine: float = 50000
) -> dict[str, Any]:
    row = await fetch_one(
        conn, BASE + " and i.run_id = %s and (i.public_id = %s or i.id::text = %s)", (run_id, incident_id, incident_id)
    )
    if row is None:
        raise Problem(404, "Решённый инцидент в выбранном запуске не найден")
    calculation = dict(row["breakdown"] or {})
    if row["computed_sim"] is not None:
        calculation["computed_sim"] = row["computed_sim"]
    scenario = Decimal(str(money(row["scenario_base"] * Decimal(str(probability)) / 100)))
    scenario_fine = Decimal(str(fine)) if row["fine_cases"] else Decimal(0)
    return {
        **row,
        "run_id": run_id,
        "saved_rub": row["saved"],
        "refund_rub": row["refund"],
        "net_rub": row["saved"] - row["refund"],
        "calculation": calculation,
        "scenario_base_rub": row["scenario_base"],
        "fine_eligible": bool(row["fine_cases"]),
        "scenario_saved_rub": money(scenario),
        "scenario_net_rub": money(scenario - row["refund"]),
        "scenario_fine_rub": money(scenario_fine),
        "scenario_with_fine_net_rub": money(scenario + scenario_fine - row["refund"]),
    }
