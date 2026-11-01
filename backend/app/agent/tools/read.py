"""Инструменты чтения контекста (T-057): компактные результаты (≤ 4 КБ), маскирование, окно 72 сим-часа по умолчанию."""

from __future__ import annotations

import datetime as dt
import re
from typing import Any

from app.agent.matching import ClientView, match_clients, nicknames_from_handles, norm_nick, norm_phone
from app.agent.tools import abs as abs_tools
from app.agent.tools.base import ToolContext, tool

WINDOW_H = 72


@tool("get_client_profile")
async def get_client_profile(ctx: ToolContext, client_id: int) -> dict[str, Any] | None:
    row = await ctx.fetchone(
        "select c.id, c.display_name, c.segment_code, c.psychotype_code, c.region_code, ci.name_ru, c.social_handles, c.consents, c.contacts, c.churn_risk, s.first_response_min, s.tone, s.hitl_required, s.personal_manager, "
        "(select state from client_states where client_id = c.id and is_current order by id desc limit 1) "
        "from clients c join cities ci on ci.id = c.city_id join segments s on s.code = c.segment_code where c.id = %s",
        (client_id,),
    )
    if not row:
        return None
    return {
        "client_id": row[0],
        "name": row[1],
        "segment": row[2],
        "psychotype": row[3],
        "region_code": row[4],
        "city": row[5],
        "social_handles": row[6] or {},
        "consents": row[7] or {},
        "contacts": {k: v for k, v in (row[8] or {}).items() if k in ("telegram", "email_masked", "phone_masked")},
        "churn_risk": row[9],
        "first_response_min": row[10],
        "tone": row[11],
        "hitl_required": row[12],
        "personal_manager": row[13],
        "state": row[14] or "calm",
    }


@tool("get_client_products")
async def get_client_products(ctx: ToolContext, client_id: int) -> list[dict[str, Any]]:
    rows = await ctx.fetchall(
        "select cp.product_code, p.name_ru, cp.status, cp.card_last4, cp.opened_sim, cp.terms from client_products cp join products p on p.code = cp.product_code where cp.client_id = %s order by cp.opened_sim desc limit 8",
        (client_id,),
    )
    return [
        {
            "product": r[0],
            "name": r[1],
            "status": r[2],
            "card_last4": r[3],
            "opened_sim": r[4],
            "params": {
                k: v for k, v in (r[5] or {}).items() if k in ("rate", "promo_code", "limit_rub", "tariff_code")
            },
        }
        for r in rows
    ]


@tool("get_recent_operations")
async def get_recent_operations(
    ctx: ToolContext, client_id: int, hours: int = WINDOW_H, limit: int = 12
) -> list[dict[str, Any]]:
    since = ctx.sim_time - dt.timedelta(hours=hours)
    rows = await ctx.fetchall(
        "select id, product_code, op_type, method, amount_rub, fee_amount, status, error_code, system_path, started_sim, merchant, fault_id from operations where client_id = %s and started_sim between %s and %s order by started_sim desc limit %s",
        (client_id, since, ctx.sim_time + dt.timedelta(hours=1), limit),
    )
    return [
        {
            "operation_id": r[0],
            "product": r[1],
            "op_type": r[2],
            "method": r[3],
            "amount_rub": float(r[4]) if r[4] is not None else None,
            "fee_amount": float(r[5] or 0),
            "status": r[6],
            "error_code": r[7],
            "system_path": list(r[8] or []),
            "started_sim": r[9],
            "merchant": r[10],
            "fault_id": r[11],
        }
        for r in rows
    ]


@tool("get_system_logs")
async def get_system_logs(ctx: ToolContext, systems: list[str], hours: int = 2, limit: int = 10) -> dict[str, Any]:
    """Активные сбои и логи по системам в окне ±hours от sim_time."""
    since, until = ctx.sim_time - dt.timedelta(hours=hours), ctx.sim_time + dt.timedelta(hours=hours)
    faults = await ctx.fetchall(
        "select id, system_code, error_code, started_sim, resolved_sim, impact_count, affected_clients from faults where run_id = %s and system_code = any(%s) and started_sim <= %s and (resolved_sim is null or resolved_sim >= %s) order by started_sim desc limit %s",
        (ctx.run_id, systems or [], until, since, limit),
    )
    logs = await ctx.fetchall(
        "select system_code, level, error_code, message, logged_sim from system_logs where run_id = %s and system_code = any(%s) and logged_sim between %s and %s and level in ('ERROR','FATAL') order by logged_sim desc limit %s",
        (ctx.run_id, systems or [], since, until, limit),
    )
    return {
        "active_faults": [
            {
                "fault_id": f[0],
                "system": f[1],
                "error_code": f[2],
                "started_sim": f[3],
                "resolved_sim": f[4],
                "impact_count": f[5],
                "affected_clients": f[6],
            }
            for f in faults
        ],
        "logs": [
            {"system": r[0], "level": r[1], "error_code": r[2], "message": (r[3] or "")[:160], "logged_sim": r[4]}
            for r in logs
        ],
    }


@tool("find_related_incidents")
async def find_related_incidents(
    ctx: ToolContext,
    client_id: int | None,
    error_code: str | None,
    system: str | None,
    product: str | None,
    region_code: str | None,
    hours: int = 4,
) -> list[dict[str, Any]]:
    """Открытые инциденты: по error_code/системе/продукту/региону в окне hours сим-часов + открытые инциденты клиента (любое время)."""
    since = ctx.sim_time - dt.timedelta(hours=hours)
    rows = await ctx.fetchall(
        "with p as (select %s::bigint as client_id, %s::text as error_code, %s::text as system, %s::text as product, %s::text as region_code, %s::timestamptz as since) "
        "select i.id, i.public_id, i.title, i.incident_type, i.error_code, i.system_code, i.product_code, i.team_code, i.status, i.mass_impact, i.created_sim, i.primary_client_id, "
        "(p.error_code is not null and i.error_code = p.error_code) as same_error, "
        "(select left(s.text,600) from incident_signals x join signals s on s.id=x.signal_id where x.incident_id=i.id order by s.id limit 1) "
        "from incidents i, p where i.run_id = %s and i.status not in ('closed','rejected','duplicate') and ("
        "  (p.client_id is not null and i.primary_client_id = p.client_id) or "
        "  (i.created_sim >= p.since and ((p.error_code is not null and i.error_code = p.error_code) or (p.system is not null and i.system_code = p.system and i.product_code = p.product) or (p.region_code is not null and i.region_code = p.region_code and i.product_code = p.product and i.mass_impact >= 3)))"
        ") order by same_error desc, i.created_sim desc limit 8",
        (client_id, error_code, system, product, region_code, since, ctx.run_id),
    )
    return [
        {
            "incident_id": r[0],
            "public_id": r[1],
            "title": r[2],
            "incident_type": r[3],
            "error_code": r[4],
            "system": r[5],
            "product": r[6],
            "team": r[7],
            "status": r[8],
            "mass_impact": r[9],
            "created_sim": r[10],
            "is_clients": r[11] == client_id,
            "same_error": bool(r[12]),
            "source_text": r[13],
        }
        for r in rows
    ]


_WORD = re.compile(r"[а-яёa-z]{5,}", re.I)


@tool("search_similar_signals")
async def search_similar_signals(
    ctx: ToolContext,
    text: str,
    client_id: int | None,
    hours: int = 48,
    limit: int = 6,
    exclude_signal_id: int | None = None,
) -> dict[str, Any]:
    """Похожие сигналы за hours сим-часов (пересечение ключевых слов; pg_trgm/pgvector — опционально, T-057 п. 3) + история клиента за 14/7 дней."""
    since = ctx.sim_time - dt.timedelta(hours=hours)
    words = sorted({w.lower() for w in _WORD.findall(text)}, key=len, reverse=True)[:6]
    similar: list[dict[str, Any]] = []
    if words:
        pattern = "%(" + "|".join(re.escape(w) for w in words) + ")%"
        rows = await ctx.fetchall(
            "select s.id, s.channel_code, left(s.text, 140), s.received_sim, s.client_id, s.status, (s.classification->>'signal_type') from signals s where s.run_id = %s and s.received_sim between %s and %s and s.id is distinct from %s::bigint and s.text ~* %s order by s.received_sim desc limit %s",
            (ctx.run_id, since, ctx.sim_time, exclude_signal_id, pattern.strip("%"), limit),
        )
        similar = [
            {
                "signal_id": r[0],
                "channel": r[1],
                "text": r[2],
                "received_sim": r[3],
                "same_client": r[4] == client_id,
                "status": r[5],
                "signal_type": r[6],
            }
            for r in rows
        ]
    hist: dict[str, Any] = {"signals_14d": 0, "signals_7d": 0, "same_type_14d": 0, "last_types": []}
    if client_id:
        rows = await ctx.fetchall(
            "select received_sim, classification->>'signal_type' from signals where client_id = %s and id is distinct from %s::bigint and received_sim between %s and %s order by received_sim desc limit 20",
            (client_id, exclude_signal_id, ctx.sim_time - dt.timedelta(days=14), ctx.sim_time),
        )
        hist["signals_14d"] = len(rows)
        hist["signals_7d"] = sum(1 for r in rows if r[0] >= ctx.sim_time - dt.timedelta(days=7))
        hist["last_types"] = [r[1] for r in rows[:5] if r[1]]
    return {"similar": similar, "client_history": hist, "keywords": words}


_NICK_SQL = """
select c.id from clients c
where (
    jsonb_typeof(c.social_handles) = 'object' and exists (
        select 1 from jsonb_each_text(c.social_handles) e
        where lower(replace(e.value, '@', '')) = %s
    )
) or (
    jsonb_typeof(c.social_handles) = 'array' and exists (
        select 1 from jsonb_array_elements(c.social_handles) el
        where lower(replace(coalesce(el->>'handle', ''), '@', '')) = %s
    )
)
"""

_LOAD_SQL = """
select c.id, c.social_handles, c.contacts->>'phone_masked', ci.name_ru,
       coalesce(array_agg(distinct cp.product_code) filter (where cp.product_code is not null), '{}'),
       coalesce(array_agg(distinct cp.card_last4) filter (where cp.card_last4 is not null), '{}')
from clients c
join cities ci on ci.id = c.city_id
left join client_products cp on cp.client_id = c.id
where c.id = any(%s)
group by c.id, ci.name_ru, c.social_handles, c.contacts
"""


@tool("match_client_by_hints")
async def match_client_by_hints(ctx: ToolContext, contacts_hint: dict[str, Any]) -> dict[str, Any]:
    """Кандидаты Mock CRM по нику, last4 и маскированному телефону (ТЗ 21.3)."""
    hint = contacts_hint or {}
    nick = norm_nick(hint.get("nickname") if isinstance(hint.get("nickname"), str) else None)
    last4 = str(hint.get("masked_card_last4") or "")
    phone = norm_phone(hint.get("masked_phone") if isinstance(hint.get("masked_phone"), str) else None)
    ids: set[int] = set()
    if nick:
        ids.update(int(row[0]) for row in await ctx.fetchall(_NICK_SQL, (nick, nick)))
    if len(last4) == 4 and last4.isdigit():
        rows = await ctx.fetchall(
            "select distinct client_id from client_products where card_last4 = %s",
            (last4,),
        )
        ids.update(int(row[0]) for row in rows)
    if phone:
        rows = await ctx.fetchall(
            "select id from clients where replace(contacts->>'phone_masked', ' ', '') = %s",
            (phone,),
        )
        ids.update(int(row[0]) for row in rows)
    clients: list[ClientView] = []
    if ids:
        for row in await ctx.fetchall(_LOAD_SQL, (list(ids),)):
            clients.append(
                ClientView(
                    client_id=int(row[0]),
                    nicknames=nicknames_from_handles(row[1]),
                    phone=row[2],
                    city=row[3],
                    products=set(row[4] or []),
                    last4=set(row[5] or []),
                )
            )
    return match_clients(clients, hint)


@tool("verify_service_delivered")
async def verify_service_delivered(ctx: ToolContext, incident_id: int) -> dict[str, Any]:
    """Проверка факта устранения: только чтение, без записи в БД."""
    evidence: list[str] = []
    row = await ctx.fetchone(
        "select status, incident_type, error_code, fault_id, primary_client_id from incidents where id = %s",
        (incident_id,),
    )
    if not row:
        return {"delivered": False, "evidence": ["инцидент не найден"]}
    status, inc_type, error_code, fault_id, client_id = (
        str(row[0]),
        str(row[1] or ""),
        row[2],
        row[3],
        row[4],
    )
    if status in ("fix_deployed", "verifying", "resolved", "closed"):
        evidence.append(f"статус инцидента: {status}")

    delivered = False
    if inc_type == "fee_refund" and client_id:
        refund = await ctx.fetchone(
            "select l.id, l.amount from ledger_entries l join accounts a on a.id = l.account_id "
            "where a.client_id = %s and l.kind = 'refund' order by l.posted_sim desc limit 1",
            (int(client_id),),
        )
        if refund:
            bal = await abs_tools.get_account_balance(ctx, int(client_id))
            evidence.append(f"проводка refund #{int(refund[0])}, {float(refund[1]):.2f} ₽")
            if bal.get("balance") is not None:
                evidence.append(f"баланс счёта {bal.get('balance')} ₽")
            delivered = True
    elif fault_id:
        frow = await ctx.fetchone("select resolved_sim from faults where id = %s", (int(fault_id),))
        if frow and frow[0]:
            evidence.append(f"сбой #{int(fault_id)} устранён")
            delivered = True
        elif status in ("resolved", "closed"):
            delivered = True
    else:
        since_row = await ctx.fetchone(
            "select changed_sim from incident_status_history where incident_id = %s and to_status = 'fix_deployed' "
            "order by id desc limit 1",
            (incident_id,),
        )
        since = since_row[0] if since_row else None
        if client_id and error_code and since:
            op = await ctx.fetchone(
                "select id from operations where client_id = %s and error_code = %s and status = 'success' "
                "and started_sim >= %s limit 1",
                (int(client_id), str(error_code), since),
            )
            if op:
                evidence.append(f"успешная операция #{int(op[0])} после релиза")
                delivered = True
        if status in ("resolved", "closed"):
            delivered = True
            if "инцидент закрыт" not in " ".join(evidence):
                evidence.append("инцидент закрыт командой")

    return {"delivered": delivered, "evidence": evidence}
