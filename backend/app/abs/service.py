"""Mock-АБС: счета, проводки, инвариант баланса, идемпотентные возвраты, события abs.* (ТЗ 3.4, 21.4).

Баланс счёта = Σ credit + Σ refund − Σ debit − Σ fee − Σ reversal; все изменения — через `post_entry` в одной транзакции
с вызывающей стороной. Идемпотентность — по `correlation_id` (повторный вызов возвращает ту же проводку, `duplicate=True`).
"""

from __future__ import annotations

import datetime as dt
import uuid
from decimal import Decimal
from typing import Any

import psycopg

from app.logging import get_logger
from app.sim.events import EventBus

log = get_logger(__name__)

SIGN: dict[str, int] = {"credit": 1, "refund": 1, "debit": -1, "fee": -1, "reversal": -1}
# операции, по которым деньги реально двигались, хотя статус failed (ошибка — в комиссии/дубле, а не в платеже)
MONEY_MOVED_ERRORS = ("PROC-QR-FEE-CHARGED", "PROC-DOUBLE-DEBIT")


class AbsError(ValueError):
    """Отказ Mock-АБС без побочных эффектов (нет проводки комиссии, уже возвращено, сумма больше комиссии…)."""


def _col(row: Any, i: int, key: str) -> Any:
    return row[key] if isinstance(row, dict) else row[i]


async def ensure_account(conn: psycopg.AsyncConnection[Any], client_id: int) -> dict[str, Any]:
    """Основной счёт клиента (создаётся при первом обращении, стартовый баланс 0)."""
    row = await (
        await conn.execute(
            "select id, balance from accounts where client_id = %s and status = 'active' order by id limit 1",
            (client_id,),
        )
    ).fetchone()
    if row:
        return {"account_id": int(_col(row, 0, "id")), "balance": float(_col(row, 1, "balance"))}
    row = await (
        await conn.execute(
            "insert into accounts (client_id, product_id, number_masked, currency, balance, status) "
            "values (%s, (select id from client_products where client_id = %s order by id limit 1), %s, 'RUB', 0, 'active') returning id",
            (client_id, client_id, f"40817•••• {client_id % 10000:04d}"),
        )
    ).fetchone()
    return {"account_id": int(_col(row, 0, "id")), "balance": 0.0}


async def post_entry(
    conn: psycopg.AsyncConnection[Any],
    *,
    run_id: int,
    client_id: int,
    kind: str,
    amount: float,
    correlation_id: uuid.UUID,
    posted_sim: dt.datetime,
    operation_id: int | None = None,
    counterpart: str | None = None,
    refund_of_entry_id: int | None = None,
    rule_id: str | None = None,
    agent_run_id: int | None = None,
    created_by: str = "sim",
    emit: bool = True,
) -> dict[str, Any]:
    """Проводка + баланс в одной транзакции; идемпотентно по correlation_id; событие abs.* (fee_charged / refund_posted / balance_changed)."""
    if kind not in SIGN:
        raise AbsError(f"неизвестный вид проводки {kind}")
    if amount <= 0:
        raise AbsError("сумма проводки должна быть положительной")
    dup = await (
        await conn.execute(
            "select l.id, l.account_id, a.balance from ledger_entries l join accounts a on a.id = l.account_id where l.correlation_id = %s",
            (correlation_id,),
        )
    ).fetchone()
    if dup:
        return {
            "entry_id": int(_col(dup, 0, "id")),
            "account_id": int(_col(dup, 1, "account_id")),
            "balance_after": float(_col(dup, 2, "balance")),
            "duplicate": True,
        }
    acc = await ensure_account(conn, client_id)
    row = await (
        await conn.execute(
            "insert into ledger_entries (run_id, account_id, operation_id, kind, amount, counterpart, posted_at, posted_sim, correlation_id, refund_of_entry_id, rule_id, agent_run_id, created_by) "
            "values (%s, %s, %s, %s, %s, %s, now(), %s, %s, %s, %s, %s, %s) returning id",
            (
                run_id,
                acc["account_id"],
                operation_id,
                kind,
                Decimal(str(round(amount, 2))),
                counterpart,
                posted_sim,
                correlation_id,
                refund_of_entry_id,
                rule_id,
                agent_run_id,
                created_by,
            ),
        )
    ).fetchone()
    entry_id = int(_col(row, 0, "id"))
    bal = await (
        await conn.execute(
            "update accounts set balance = balance + %s, updated_at = now() where id = %s returning balance",
            (Decimal(str(round(SIGN[kind] * amount, 2))), acc["account_id"]),
        )
    ).fetchone()
    balance_after = float(_col(bal, 0, "balance"))
    if emit:
        event_type = {"fee": "abs.fee_charged", "refund": "abs.refund_posted"}.get(kind, "abs.balance_changed")
        await EventBus(conn, strict=False).emit(
            run_id,
            event_type,
            {
                "account_id": acc["account_id"],
                "client_id": client_id,
                "entry_id": entry_id,
                "operation_id": operation_id,
                "kind": kind,
                "amount_rub": round(amount, 2),
                "balance_after_rub": balance_after,
                "refund_of_entry_id": refund_of_entry_id,
                "rule_code": rule_id,
                "agent_run_id": agent_run_id,
                "created_by": created_by,
                "posted_sim": posted_sim.isoformat(),
            },
            posted_sim,
            correlation_id=correlation_id,
        )
    return {"entry_id": entry_id, "account_id": acc["account_id"], "balance_after": balance_after, "duplicate": False}


async def post_operation(
    conn: psycopg.AsyncConnection[Any],
    *,
    run_id: int,
    operation_id: int,
    client_id: int,
    amount_rub: float | None,
    fee_amount: float | None,
    status: str,
    error_code: str | None,
    merchant: str | None,
    posted_sim: dt.datetime,
    emit: bool = True,
) -> dict[str, Any]:
    """Проводки по одной операции в момент её появления (генератор, сценарий): debit — если деньги двигались, fee — если комиссия > 0.

    Идемпотентно (correlation_id выводится из operation_id). Событие abs.fee_charged — только для комиссии (виджет АБС в демо).
    """
    out: dict[str, Any] = {}
    moved = status == "success" or (error_code in MONEY_MOVED_ERRORS)
    if amount_rub and amount_rub > 0 and moved:
        out["debit"] = await post_entry(
            conn,
            run_id=run_id,
            client_id=client_id,
            kind="debit",
            amount=float(amount_rub),
            correlation_id=uuid.uuid5(uuid.NAMESPACE_URL, f"op:{operation_id}:debit"),
            posted_sim=posted_sim,
            operation_id=operation_id,
            counterpart=merchant,
            emit=False,
        )
    if fee_amount and fee_amount > 0 and (status == "success" or error_code == "PROC-QR-FEE-CHARGED"):
        out["fee"] = await post_entry(
            conn,
            run_id=run_id,
            client_id=client_id,
            kind="fee",
            amount=float(fee_amount),
            correlation_id=uuid.uuid5(uuid.NAMESPACE_URL, f"op:{operation_id}:fee"),
            posted_sim=posted_sim,
            operation_id=operation_id,
            counterpart="комиссия банка",
            emit=emit,
        )
    return out


async def ensure_operation_posted(conn: psycopg.AsyncConnection[Any], operation_id: int) -> dict[str, Any]:
    """Догоняющие проводки по операции, если её создали мимо генератора (сценарий, API)."""
    row = await (
        await conn.execute(
            "select run_id, client_id, amount_rub, fee_amount, status, error_code, merchant, coalesce(finished_sim, started_sim) as posted_sim from operations where id = %s",
            (operation_id,),
        )
    ).fetchone()
    if not row:
        return {}
    return await post_operation(
        conn,
        run_id=int(_col(row, 0, "run_id")),
        operation_id=operation_id,
        client_id=int(_col(row, 1, "client_id")),
        amount_rub=float(_col(row, 2, "amount_rub") or 0),
        fee_amount=float(_col(row, 3, "fee_amount") or 0),
        status=str(_col(row, 4, "status")),
        error_code=_col(row, 5, "error_code"),
        merchant=_col(row, 6, "merchant"),
        posted_sim=_col(row, 7, "posted_sim"),
        emit=False,
    )


async def backfill_ledger(conn: psycopg.AsyncConnection[Any], run_id: int | None = None) -> dict[str, int]:
    """Проводки для операций, у которых их ещё нет (сид/старт): debit по успешным и «деньги списаны» операциям, fee по комиссиям.

    Набор-ориентированно, без событий (история); баланс пересчитывается из проводок. Идемпотентно.
    """
    scope = "and o.run_id = %s" if run_id is not None else ""
    args: tuple[Any, ...] = (run_id,) if run_id is not None else ()
    await conn.execute(
        "insert into accounts (client_id, product_id, number_masked, currency, balance, status) "
        "select c.id, (select id from client_products cp where cp.client_id = c.id order by id limit 1), "
        "'40817•••• ' || lpad((c.id % 10000)::text, 4, '0'), 'RUB', 0, 'active' from clients c "
        "where not exists (select 1 from accounts a where a.client_id = c.id)"
    )
    cur = await conn.execute(
        f"""
        insert into ledger_entries (run_id, account_id, operation_id, kind, amount, counterpart, posted_at, posted_sim, correlation_id, created_by)
        select o.run_id, a.id, o.id, 'debit', o.amount_rub, o.merchant, now(), coalesce(o.finished_sim, o.started_sim), gen_random_uuid(), 'sim'
        from operations o join accounts a on a.id = (select min(id) from accounts x where x.client_id = o.client_id and x.status = 'active')
        where o.amount_rub > 0 and (o.status = 'success' or o.error_code = any(%s)) {scope}
          and not exists (select 1 from ledger_entries l where l.operation_id = o.id and l.kind = 'debit')
        """,
        (list(MONEY_MOVED_ERRORS), *args),
    )
    debits = cur.rowcount
    cur = await conn.execute(
        f"""
        insert into ledger_entries (run_id, account_id, operation_id, kind, amount, counterpart, posted_at, posted_sim, correlation_id, created_by)
        select o.run_id, a.id, o.id, 'fee', o.fee_amount, 'комиссия банка', now(), coalesce(o.finished_sim, o.started_sim), gen_random_uuid(), 'sim'
        from operations o join accounts a on a.id = (select min(id) from accounts x where x.client_id = o.client_id and x.status = 'active')
        where o.fee_amount > 0 and (o.status = 'success' or o.error_code = 'PROC-QR-FEE-CHARGED') {scope}
          and not exists (select 1 from ledger_entries l where l.operation_id = o.id and l.kind = 'fee')
        """,
        args,
    )
    fees = cur.rowcount
    # стартовый остаток одной credit-проводкой: сохраняет баланс из сида (balance_seed = credit − debit − fee) и делает инвариант истинным
    cur = await conn.execute(
        """
        insert into ledger_entries (run_id, account_id, operation_id, kind, amount, counterpart, posted_at, posted_sim, correlation_id, created_by)
        select (select coalesce(max(id), 1) from sim_runs), a.id, null, 'credit',
               greatest(a.balance, 0) + coalesce(s.spent, 0), 'начальный остаток', now(),
               coalesce(s.first_sim, (select sim_time from sim_state where id = 1), now()) - interval '1 day', gen_random_uuid(), 'sim'
        from accounts a
        left join lateral (select sum(amount) filter (where kind in ('debit','fee')) as spent, min(posted_sim) as first_sim
                           from ledger_entries l where l.account_id = a.id) s on true
        where not exists (select 1 from ledger_entries l where l.account_id = a.id and l.operation_id is null)
          and (a.balance > 0 or coalesce(s.spent, 0) > 0)
        """
    )
    credits = cur.rowcount
    # отрицательный остаток из сида (кредитная карта/овердрафт) — одной debit-проводкой «задолженность»
    cur = await conn.execute(
        """
        insert into ledger_entries (run_id, account_id, operation_id, kind, amount, counterpart, posted_at, posted_sim, correlation_id, created_by)
        select (select coalesce(max(id), 1) from sim_runs), a.id, null, 'debit', -a.balance, 'задолженность (начальный остаток)', now(),
               coalesce((select sim_time from sim_state where id = 1), now()) - interval '1 day', gen_random_uuid(), 'sim'
        from accounts a where a.balance < 0 and not exists (select 1 from ledger_entries l where l.account_id = a.id and l.operation_id is null)
        """
    )
    credits += cur.rowcount
    if debits or fees or credits:
        await recompute_balances(conn)
    return {"debits": debits, "fees": fees, "credits": credits}


async def recompute_balances(conn: psycopg.AsyncConnection[Any]) -> None:
    await conn.execute(
        """
        update accounts a set balance = coalesce(s.bal, 0), updated_at = now()
        from (select account_id,
                     sum(case when kind in ('credit','refund') then amount else -amount end) as bal
              from ledger_entries group by account_id) s
        where s.account_id = a.id and a.balance <> coalesce(s.bal, 0)
        """
    )


async def check_invariant(conn: psycopg.AsyncConnection[Any]) -> list[dict[str, Any]]:
    """Счета, где balance ≠ Σ проводок (должно быть пусто)."""
    rows = await (
        await conn.execute(
            """
            select a.id, a.balance, coalesce(s.bal, 0) as expected
            from accounts a left join (select account_id, sum(case when kind in ('credit','refund') then amount else -amount end) as bal
                                       from ledger_entries group by account_id) s on s.account_id = a.id
            where a.balance <> coalesce(s.bal, 0)
            """
        )
    ).fetchall()
    return [
        {
            "account_id": _col(r, 0, "id"),
            "balance": float(_col(r, 1, "balance")),
            "expected": float(_col(r, 2, "expected")),
        }
        for r in rows
    ]


async def rule_confirmed(conn: psycopg.AsyncConnection[Any], operation_id: int, rule_id: str | None) -> bool:
    row = await (
        await conn.execute(
            "select 1 from rule_evaluations where result = 'matched' and (%s::text is null or rule_code = %s) "
            "and evidence->'operation_ids' @> to_jsonb(array[%s::bigint]) limit 1",
            (rule_id, rule_id, operation_id),
        )
    ).fetchone()
    return row is not None


async def refund_fee(
    conn: psycopg.AsyncConnection[Any],
    *,
    run_id: int,
    operation_id: int,
    amount_rub: float | None,
    rule_id: str | None,
    reason: str,
    posted_sim: dt.datetime,
    correlation_id: uuid.UUID | None = None,
    agent_run_id: int | None = None,
    created_by: str = "agent",
    require_rule: bool = True,
) -> dict[str, Any]:
    """Возврат ошибочной комиссии по операции: проверка правила (для агента), наличие fee-проводки, отсутствие повторного возврата, сумма ≤ комиссии."""
    fee = await (
        await conn.execute(
            "select l.id, l.amount, a.client_id from ledger_entries l join accounts a on a.id = l.account_id "
            "where l.operation_id = %s and l.kind = 'fee' order by l.id limit 1",
            (operation_id,),
        )
    ).fetchone()
    if not fee:
        await ensure_operation_posted(conn, operation_id)
        fee = await (
            await conn.execute(
                "select l.id, l.amount, a.client_id from ledger_entries l join accounts a on a.id = l.account_id "
                "where l.operation_id = %s and l.kind = 'fee' order by l.id limit 1",
                (operation_id,),
            )
        ).fetchone()
    if not fee:
        raise AbsError(f"по операции {operation_id} нет проводки комиссии")
    fee_entry_id, fee_amount, client_id = (
        int(_col(fee, 0, "id")),
        float(_col(fee, 1, "amount")),
        int(_col(fee, 2, "client_id")),
    )
    existing = await (
        await conn.execute(
            "select l.id, l.amount, a.balance from ledger_entries l join accounts a on a.id = l.account_id where l.refund_of_entry_id = %s",
            (fee_entry_id,),
        )
    ).fetchone()
    if existing:
        return {
            "entry_id": int(_col(existing, 0, "id")),
            "amount_rub": float(_col(existing, 1, "amount")),
            "balance_after": float(_col(existing, 2, "balance")),
            "client_id": client_id,
            "duplicate": True,
            "already_refunded": True,
        }
    if require_rule and not await rule_confirmed(conn, operation_id, rule_id):
        raise AbsError(f"правило {rule_id or '?'} не подтвердило нарушение по операции {operation_id}")
    amount = float(amount_rub) if amount_rub is not None else fee_amount
    if amount > fee_amount + 0.005:
        raise AbsError(f"сумма возврата {amount:.2f} больше комиссии {fee_amount:.2f}")
    res = await post_entry(
        conn,
        run_id=run_id,
        client_id=client_id,
        kind="refund",
        amount=amount,
        correlation_id=correlation_id or uuid.uuid5(uuid.NAMESPACE_URL, f"refund:{fee_entry_id}"),
        posted_sim=posted_sim,
        operation_id=operation_id,
        counterpart=f"возврат комиссии: {reason}"[:200],
        refund_of_entry_id=fee_entry_id,
        rule_id=rule_id,
        agent_run_id=agent_run_id,
        created_by=created_by,
    )
    log.info("abs_refund_posted", operation_id=operation_id, amount=amount, rule=rule_id, by=created_by)
    return {**res, "amount_rub": amount, "client_id": client_id, "already_refunded": False}


async def find_affected(
    conn: psycopg.AsyncConnection[Any], *, run_id: int, error_code: str, since_sim: dt.datetime
) -> list[dict[str, Any]]:
    """Операции с тем же кодом ошибки в окне, без возврата комиссии (кандидаты массового возврата)."""
    rows = await (
        await conn.execute(
            """
            select o.id, o.client_id, o.fee_amount, o.amount_rub, o.started_sim, c.region_code,
                   exists (select 1 from ledger_entries r join ledger_entries f on r.refund_of_entry_id = f.id
                           where f.operation_id = o.id and r.kind = 'refund') as refunded
            from operations o join clients c on c.id = o.client_id
            where o.run_id = %s and o.error_code = %s and o.started_sim >= %s order by o.started_sim desc limit 500
            """,
            (run_id, error_code, since_sim),
        )
    ).fetchall()
    return [
        {
            "operation_id": _col(r, 0, "id"),
            "client_id": _col(r, 1, "client_id"),
            "fee_amount": float(_col(r, 2, "fee_amount") or 0),
            "amount_rub": float(_col(r, 3, "amount_rub") or 0),
            "started_sim": _col(r, 4, "started_sim"),
            "region_code": _col(r, 5, "region_code"),
            "refunded": bool(_col(r, 6, "refunded")),
        }
        for r in rows
    ]


async def accounts_view(
    conn: psycopg.AsyncConnection[dict[str, Any]], client_id: int, entries_limit: int = 20
) -> dict[str, Any] | None:
    """AccountsView для виджета «АБС (эмуляция)»: клиент, счета, последние проводки."""
    client = await (
        await conn.execute(
            "select c.id, c.public_id, c.display_name, c.segment_code, c.region_code, ci.name_ru as city_name, c.churn_risk, c.is_active "
            "from clients c left join cities ci on ci.id = c.city_id where c.id = %s",
            (client_id,),
        )
    ).fetchone()
    if not client:
        return None
    accounts = await (
        await conn.execute(
            "select id, client_id, product_id, number_masked, currency, balance::float as balance, status from accounts where client_id = %s order by id",
            (client_id,),
        )
    ).fetchall()
    entries = await (
        await conn.execute(
            "select l.id, l.account_id, l.operation_id, l.kind, l.amount::float as amount, l.counterpart, l.posted_at, l.posted_sim, "
            "l.correlation_id, l.refund_of_entry_id, l.rule_id, l.agent_run_id, l.created_by "
            "from ledger_entries l join accounts a on a.id = l.account_id where a.client_id = %s order by l.posted_sim desc, l.id desc limit %s",
            (client_id, entries_limit),
        )
    ).fetchall()
    return {"client": dict(client), "accounts": [dict(a) for a in accounts], "entries": [dict(e) for e in entries]}
