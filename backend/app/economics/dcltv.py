"""Формула ТЗ 14.4: Потеря = Пострадавшие × доля детракторов × доля невозврата × (ставка dCLTV + премиальная надбавка).

Ставка выбирается по приоритету продукт → система → канал → fallback `bank_average`; коэффициент удержания — по классу исхода
(`economics_settings.retention_factors`, либо фактические доли из `v_retention_by_outcome` при `calibration_mode = simulated`
и выборке ≥ 10). Для `fee_refund` к реализованной стоимости добавляется возвращённая комиссия (ledger_entries.kind = 'refund').
"""

from __future__ import annotations

import datetime as dt
from dataclasses import dataclass
from decimal import ROUND_HALF_UP, Decimal
from typing import Any

import psycopg
from psycopg.rows import dict_row

from app.logging import get_logger
from app.sim.events import dumps

log = get_logger(__name__)

PREMIUM_SEGMENTS = ("premium", "vip", "ultra_vip")
OPEN_STATUSES = (
    "new",
    "classified",
    "routed",
    "in_progress",
    "fix_proposed",
    "fix_deployed",
    "verifying",
    "awaiting_human",
    "awaiting_client",
    "escalated",
)


@dataclass(frozen=True)
class Rate:
    code: str
    rub: float
    reason: str


def _q(v: float) -> float:
    return float(Decimal(str(v)).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP))


def pick_rate(
    rates: list[dict[str, Any]],
    *,
    product: str | None,
    system: str | None,
    channel: str | None,
    segment: str | None,
    op_type: str | None = None,
) -> Rate:
    """Чистая функция выбора ставки: продукт (+сегмент) → система (+op_type) → канал → fallback."""
    by_code = {r["code"]: r for r in rates}

    def hit(key: str, value: str | None, *, segment_bound: bool | None = None) -> dict[str, Any] | None:
        if not value:
            return None
        for r in rates:
            m = r.get("maps_to") or {}
            if value not in (m.get(key) or []):
                continue
            segs = m.get("segments")
            if segment_bound is True and not segs:
                continue
            if segment_bound is False and segs:
                continue
            if segs and segment not in segs:
                continue
            return r
        return None

    r = hit("products", product, segment_bound=True) or hit("products", product, segment_bound=False)
    if r:
        return Rate(r["code"], float(r["rate_rub"]), f"продукт {product}")
    if system and op_type:
        for cand in rates:
            m = cand.get("maps_to") or {}
            if system in (m.get("systems") or []) and op_type in (m.get("op_types") or []):
                return Rate(cand["code"], float(cand["rate_rub"]), f"система {system}, операция {op_type}")
    r = next(
        (
            c
            for c in rates
            if system
            and system in ((c.get("maps_to") or {}).get("systems") or [])
            and not (c.get("maps_to") or {}).get("op_types")
        ),
        None,
    ) or hit("systems", system)
    if r:
        return Rate(r["code"], float(r["rate_rub"]), f"система {system}")
    r = hit("channels", channel)
    if r:
        return Rate(r["code"], float(r["rate_rub"]), f"канал {channel}")
    fb = next((x for x in rates if (x.get("maps_to") or {}).get("fallback")), None) or by_code.get("bank_average")
    return Rate(
        fb["code"] if fb else "bank_average",
        float(fb["rate_rub"]) if fb else 4050.0,
        "средняя ставка по банку (fallback)",
    )


def compute(
    *,
    affected: int,
    detractor_share: float,
    no_return_share: float,
    rate: Rate,
    premium_addon: float,
    retention_factor: float,
    outcome_class: str,
    refund_rub: float = 0.0,
) -> dict[str, Any]:
    """Чистый расчёт: потенциальная, предотвращённая, реализованная потеря и formula_ru (пример ТЗ: 12 × 10 % × 50 % × (961 + 91,53) = 631,52 ₽)."""
    affected = max(1, int(affected))
    per_client = rate.rub + premium_addon
    potential = _q(affected * detractor_share * no_return_share * per_client)
    if outcome_class == "churned":
        prevented, realized = 0.0, potential
    else:
        prevented, realized = _q(potential * retention_factor), 0.0
    rate_txt = f"({rate.rub:g} + {premium_addon:g})" if premium_addon else f"{rate.rub:g}"
    formula = f"{affected} × {detractor_share * 100:g} % × {no_return_share * 100:g} % × {rate_txt} = {potential:,.2f} ₽".replace(
        ",", " "
    ).replace(".", ",")
    return {
        "affected_count": affected,
        "rate_code": rate.code,
        "rate_rub": rate.rub,
        "rate_reason": rate.reason,
        "premium_addon_rub": premium_addon,
        "detractor_share": detractor_share,
        "no_return_share": no_return_share,
        "potential_loss_rub": potential,
        "retention_factor": retention_factor,
        "prevented_loss_rub": prevented,
        "realized_loss_rub": realized,
        "refund_amount_rub": _q(refund_rub),
        "net_effect_rub": _q(prevented - refund_rub),
        "outcome_class": outcome_class,
        "formula_ru": formula,
    }


def outcome_of(inc: dict[str, Any], *, gift_given: bool, regression: bool, churned: bool) -> str:
    """Класс исхода инцидента по статусу/SLA/подарку/регрессии (ТЗ 14.4)."""
    if churned:
        return "churned"
    st = inc["status"]
    if st in ("rejected", "duplicate"):
        return "rejected"
    if st not in ("resolved", "closed"):
        return "open"
    if regression:
        return "closed_with_regression"
    done = inc.get("resolved_sim") or inc.get("closed_sim")
    late = bool(inc.get("sla_breached")) or (
        done is not None and inc.get("sla_due_sim") is not None and done > inc["sla_due_sim"]
    )
    if late:
        return "closed_late"
    return "closed_in_sla_with_gift" if gift_given else "closed_in_sla"


async def load_settings(conn: psycopg.AsyncConnection[Any]) -> dict[str, Any]:
    async with conn.cursor(row_factory=dict_row) as cur:
        await cur.execute("select * from economics_settings where id = 1")
        s = await cur.fetchone()
        await cur.execute("select code, name_ru, rate_rub, maps_to from dcltv_rates order by rate_rub desc")
        rates = await cur.fetchall()
    return {"settings": s or {}, "rates": rates}


async def _retention_factor(
    conn: psycopg.AsyncConnection[Any], settings: dict[str, Any], run_id: int, outcome: str
) -> tuple[float, str]:
    manual = float((settings.get("retention_factors") or {}).get(outcome, 0) or 0)
    if settings.get("calibration_mode") == "simulated":
        async with conn.cursor(row_factory=dict_row) as cur:
            await cur.execute(
                "select retention_rate, resolved_clients from v_retention_by_outcome where run_id = %s and outcome_class = %s",
                (run_id, outcome),
            )
            row = await cur.fetchone()
        if row and row["retention_rate"] is not None and int(row["resolved_clients"]) >= 10:
            return float(row["retention_rate"]), "simulated"
    return manual, "manual"


async def compute_incident(
    conn: psycopg.AsyncConnection[Any], incident_id: int, *, sim_time: dt.datetime | None = None
) -> dict[str, Any] | None:
    """Расчёт и upsert `incident_economics` для одного инцидента; возвращает развёрнутый расчёт (IncidentEconomics + formula_ru)."""
    async with conn.cursor(row_factory=dict_row) as cur:
        await cur.execute(
            """
            select i.id, i.run_id, i.status, i.incident_type, i.product_code, i.system_code, i.mass_impact, i.fault_id, i.primary_client_id,
                   i.sla_due_sim, i.resolved_sim, i.closed_sim, i.sla_breached, i.outcome_class, i.flags,
                   c.segment_code as segment, f.affected_clients as fault_clients, f.impact_count as fault_ops,
                   (select s.channel_code from incident_signals isg join signals s on s.id = isg.signal_id where isg.incident_id = i.id order by isg.linked_sim limit 1) as channel,
                   (select count(*) from incident_signals isg where isg.incident_id = i.id) as signals_count,
                   exists (select 1 from tasks t where t.incident_id = i.id and t.kind = 'gift' and t.status in ('done','completed')) as gift_given,
                   exists (select 1 from client_states cs where cs.incident_id = i.id and cs.state = 'churned') as churned,
                   coalesce((select sum(l.amount) from ledger_entries l join agent_runs ar on ar.id = l.agent_run_id where ar.incident_id = i.id and l.kind = 'refund'), 0) as refund_rub,
                   (select sim_time from sim_state where id = 1) as now_sim
            from incidents i
            left join clients c on c.id = i.primary_client_id
            left join faults f on f.id = i.fault_id
            where i.id = %s
            """,
            (incident_id,),
        )
        inc = await cur.fetchone()
    if not inc:
        return None
    cfg = await load_settings(conn)
    s, rates = cfg["settings"], cfg["rates"]
    flags = inc.get("flags") or []
    regression = "regression" in flags or "churn_regression" in flags
    outcome = outcome_of(inc, gift_given=bool(inc["gift_given"]), regression=regression, churned=bool(inc["churned"]))
    affected = max(
        int(inc.get("fault_clients") or 0), int(inc.get("mass_impact") or 1), int(inc.get("signals_count") or 1)
    )
    if inc["incident_type"] == "misselling":
        rate = Rate("misselling_case", float(s.get("misselling_case_cost_rub") or 4050), "стоимость случая мисселлинга")
        detr, nor = 1.0, 1.0
    else:
        rate = pick_rate(
            rates,
            product=inc.get("product_code"),
            system=inc.get("system_code"),
            channel=inc.get("channel"),
            segment=inc.get("segment"),
        )
        detr, nor = float(s.get("detractor_share") or 0.1), float(s.get("no_return_share") or 0.5)
    premium = (
        next((float(r["rate_rub"]) for r in rates if r["code"] == "premium_service"), 91.53)
        if inc.get("segment") in PREMIUM_SEGMENTS
        else 0.0
    )
    factor, source = await _retention_factor(conn, s, int(inc["run_id"]), outcome)
    res = compute(
        affected=affected,
        detractor_share=detr,
        no_return_share=nor,
        rate=rate,
        premium_addon=premium,
        retention_factor=factor,
        outcome_class=outcome,
        refund_rub=float(inc.get("refund_rub") or 0),
    )
    res["retention_source"] = source
    res["computed_sim"] = sim_time or inc.get("now_sim") or dt.datetime.now(dt.UTC)
    breakdown = {k: v for k, v in res.items() if k not in ("computed_sim",)}
    await conn.execute(
        """
        insert into incident_economics (incident_id, run_id, affected_count, rate_code, rate_rub, premium_addon_rub, detractor_share, no_return_share,
                                        potential_loss_rub, retention_factor, retention_source, prevented_loss_rub, realized_loss_rub, breakdown, computed_sim, refund_amount_rub)
        values (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s::jsonb, %s, %s)
        on conflict (incident_id) do update set affected_count = excluded.affected_count, rate_code = excluded.rate_code, rate_rub = excluded.rate_rub,
            premium_addon_rub = excluded.premium_addon_rub, detractor_share = excluded.detractor_share, no_return_share = excluded.no_return_share,
            potential_loss_rub = excluded.potential_loss_rub, retention_factor = excluded.retention_factor, retention_source = excluded.retention_source,
            prevented_loss_rub = excluded.prevented_loss_rub, realized_loss_rub = excluded.realized_loss_rub, breakdown = excluded.breakdown,
            computed_sim = excluded.computed_sim, computed_at = now(), refund_amount_rub = excluded.refund_amount_rub
        """,
        (
            incident_id,
            inc["run_id"],
            res["affected_count"],
            res["rate_code"]
            if res["rate_code"] in {r["code"] for r in rates}
            else (s.get("fallback_rate_code") or "bank_average"),
            res["rate_rub"],
            res["premium_addon_rub"],
            res["detractor_share"],
            res["no_return_share"],
            res["potential_loss_rub"],
            res["retention_factor"],
            source,
            res["prevented_loss_rub"],
            res["realized_loss_rub"],
            dumps(breakdown),
            res["computed_sim"],
            res["refund_amount_rub"],
        ),
    )
    if inc.get("outcome_class") != outcome:
        await conn.execute(
            "update incidents set outcome_class = %s, updated_at = now() where id = %s", (outcome, incident_id)
        )
    return res


async def recompute(
    conn: psycopg.AsyncConnection[Any], *, run_id: int | None = None, only_stale: bool = True, limit: int = 500
) -> int:
    """Пересчёт экономики: открытые/изменённые инциденты без расчёта или с расчётом старее `updated_at`."""
    where = ["true"]
    args: list[Any] = []
    if run_id is not None:
        where.append("i.run_id = %s")
        args.append(run_id)
    if only_stale:
        where.append(
            "(e.incident_id is null or e.computed_at < i.updated_at or (i.status = any(%s) and e.computed_at < now() - interval '60 seconds'))"
        )
        args.append(list(OPEN_STATUSES))
    async with conn.cursor(row_factory=dict_row) as cur:
        await cur.execute(
            f"select i.id from incidents i left join incident_economics e on e.incident_id = i.id where {' and '.join(where)} order by i.id desc limit %s",
            (*args, limit),
        )
        rows = await cur.fetchall()
    n = 0
    for row in rows:
        iid = int(row["id"])
        try:
            await compute_incident(conn, iid)
            n += 1
        except Exception as exc:  # noqa: BLE001 — один инцидент не должен ломать пересчёт
            log.warning("economics_compute_failed", incident_id=iid, error=str(exc)[:200])
    return n


async def summary(
    conn: psycopg.AsyncConnection[Any], *, run_id: int | None, group_by: str = "product", window: str = "run"
) -> dict[str, Any]:
    """EconomicsSummary: суммы потерь по инцидентам запуска (или всем) с группировкой product|region|segment|team|type."""
    await recompute(conn, run_id=run_id)
    col = {
        "product": "coalesce(i.product_code, '—')",
        "region": "coalesce(i.region_code, '—')",
        "segment": "coalesce(c.segment_code, '—')",
        "team": "i.team_code",
        "type": "i.incident_type",
    }.get(group_by, "coalesce(i.product_code, '—')")
    args: list[Any] = []
    where = "true"
    if run_id is not None:
        where = "i.run_id = %s"
        args.append(run_id)
    async with conn.cursor(row_factory=dict_row) as cur:
        await cur.execute(
            f"""
            select {col} as key, count(*) as incidents,
                   coalesce(sum(e.potential_loss_rub), 0)::float as potential_loss_rub,
                   coalesce(sum(e.prevented_loss_rub), 0)::float as prevented_loss_rub,
                   coalesce(sum(e.realized_loss_rub), 0)::float as realized_loss_rub,
                   coalesce(sum(e.potential_loss_rub) filter (where i.status = any(%s)), 0)::float as at_risk_open_rub,
                   coalesce(sum(e.refund_amount_rub), 0)::float as refund_rub
            from incidents i left join incident_economics e on e.incident_id = i.id left join clients c on c.id = i.primary_client_id
            where {where} group by 1 order by 3 desc
            """,
            (list(OPEN_STATUSES), *args),
        )
        groups = await cur.fetchall()
        await cur.execute("select calibration_mode from economics_settings where id = 1")
        mode = await cur.fetchone()
    labels: dict[str, str] = {}
    if group_by in ("product", "region", "segment", "team"):
        table = {"product": "products", "region": "regions", "segment": "segments", "team": "teams"}[group_by]
        async with conn.cursor(row_factory=dict_row) as cur:
            await cur.execute(f"select code, name_ru from {table}")  # noqa: S608 — имя таблицы из белого списка
            labels = {str(r["code"]): str(r["name_ru"]) for r in await cur.fetchall()}
    return {
        "window": window,
        "potential_loss_rub": _q(sum(g["potential_loss_rub"] for g in groups)),
        "prevented_loss_rub": _q(sum(g["prevented_loss_rub"] for g in groups)),
        "at_risk_open_rub": _q(sum(g["at_risk_open_rub"] for g in groups)),
        "realized_loss_rub": _q(sum(g["realized_loss_rub"] for g in groups)),
        "refund_rub": _q(sum(g["refund_rub"] for g in groups)),
        "calibration_mode": (mode or {}).get("calibration_mode", "manual"),
        "group_by": group_by,
        "groups": [
            {
                "key": g["key"],
                "label_ru": labels.get(g["key"], g["key"]),
                "potential_loss_rub": _q(g["potential_loss_rub"]),
                "prevented_loss_rub": _q(g["prevented_loss_rub"]),
                "realized_loss_rub": _q(g["realized_loss_rub"]),
                "at_risk_open_rub": _q(g["at_risk_open_rub"]),
                "incidents": int(g["incidents"]),
            }
            for g in groups
        ],
    }
