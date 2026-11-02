"""Роутер тега `clients` (OpenAPI 1.4.0). Поиск реализован (нужен режиму жюри), «Клиент 360» — карточка T-091."""

from __future__ import annotations

import re
from typing import Any

from fastapi import APIRouter, HTTPException, Query, Request

from app.api.common import db, fetch_all, fetch_one
from app.api.tasks import TASK_SQL, _shape
from app.trace.store import allowed_run, read_db

router = APIRouter(tags=["clients"])


@router.get("/api/clients", summary="Поиск клиента (для жюри-режима и фильтров)")
async def get_clients(
    request: Request,
    q: str | None = None,
    segment: str | None = None,
    region_code: str | None = None,
    limit: int = Query(default=20, ge=1, le=200),
) -> Any:
    where: list[str] = ["true"]
    args: list[Any] = []
    if q:
        where.append("(c.display_name ilike %s or c.public_id ilike %s or ct.name_ru ilike %s)")
        args += [f"%{q}%", f"%{q}%", f"%{q}%"]
    if segment:
        where.append("c.segment_code = %s")
        args.append(segment)
    if region_code:
        where.append("c.region_code = %s")
        args.append(region_code)
    args.append(limit)
    async with db() as conn:
        return await fetch_all(
            conn,
            "select c.id, c.public_id, c.display_name, c.segment_code, c.region_code, ct.name_ru as city_name, c.churn_risk, c.is_active "
            f"from clients c left join cities ct on ct.id = c.city_id where {' and '.join(where)} order by c.is_active desc, c.id limit %s",  # noqa: S608
            args,
        )


def _mask_contacts(raw: dict[str, Any] | None) -> dict[str, Any]:
    # Профиль не должен отдавать произвольные секреты из свободного JSON контактов.
    out = {
        key: value for key, value in (raw or {}).items() if key in ("phone_masked", "email_masked", "preferred", "city")
    }
    for key in ("phone", "email"):
        if (raw or {}).get(key):
            out[key] = "***"
    return out


_COMMUNICATION_HINTS = {
    "loyal_pragmatic": "Коротко объясните факт и результат решения; избегайте лишних обещаний.",
    "anxious": "Подтвердите, что проблема замечена, объясните следующий шаг и регулярно сообщайте о ходе работы.",
    "demanding_rational": "Приведите причины, конкретные сроки и факты; соблюдайте договорённости.",
    "public_emotional": "Ответьте быстро и спокойно, признайте неудобство и предложите личный канал для деталей.",
    "silent_churner": "Свяжитесь проактивно: не ждите жалобы, предложите понятный следующий шаг.",
    "bonus_hunter": "Разъясните условия и уместную компенсацию; не обещайте подарок до подтверждения.",
    "novice": "Объясняйте простыми словами, по шагам; проверьте, что клиент понял решение.",
    "status_oriented": "Предложите персональное сопровождение, точные сроки и контакт ответственного сотрудника.",
}


@router.get(
    "/api/clients/{id}/360",
    summary="Клиент 360 — профиль, продукты, операции, сигналы, инциденты, состояние и стиль коммуникации",
)
async def get_clients_id_360(  # noqa: A002
    id: int,
    ops_hours: int = Query(default=72, ge=1, le=720),
    run_id: str = Query(default="current"),
) -> Any:
    if run_id not in ("current", "all") and not re.fullmatch(r"[1-9][0-9]*", run_id):
        raise HTTPException(422, "run_id: current | all | positive integer")
    async with read_db() as conn:
        client = await fetch_one(
            conn,
            "select c.id,c.public_id,c.display_name,c.segment_code,c.region_code,ct.name_ru as city_name, "
            "c.churn_risk,c.is_active,c.clv_estimate_rub,c.contacts,c.psychotype_code, "
            "p.name_ru as psychotype_name_ru,p.name_en as psychotype_name_en "
            "from clients c left join cities ct on ct.id=c.city_id "
            "left join psychotypes p on p.code=c.psychotype_code where c.id=%s",
            (id,),
        )
        if client is None:
            raise HTTPException(404, "клиент не найден")
        clock = await fetch_one(conn, "select sim_time,current_run_id from sim_state where id=1")
        if clock is None:
            raise HTTPException(503, "симуляционные часы ещё не настроены")
        rid = await allowed_run(conn, run_id)
        selected = None
        if rid is not None and rid != -1:
            selected = await fetch_one(conn, "select id,started_sim,finished_sim from sim_runs where id=%s", (rid,))
            if selected is None:
                raise HTTPException(404, "запуск не найден")
        baselines = await fetch_all(conn, "select id from sim_runs where kind='baseline'")
        scope = None if rid is None else [int(row["id"]) for row in baselines] + ([rid] if rid != -1 else [])
        as_of = clock["sim_time"]
        if selected and rid != clock["current_run_id"]:
            last = await fetch_one(conn, "select max(sim_time) as sim_time from sim_events where run_id=%s", (rid,))
            as_of = selected["finished_sim"] or (last or {}).get("sim_time") or selected["started_sim"]
        products = await fetch_all(
            conn,
            "select id,product_code,status,terms,card_last4,opened_sim,closed_sim from client_products where client_id=%s order by id",
            (id,),
        )
        operations = await fetch_all(
            conn,
            "select o.id,o.run_id,o.product_code,o.op_type,o.status,o.amount_rub::double precision as amount_rub,o.error_code,o.started_sim,o.finished_sim, "
            "f.id as fault_id,f.system_code as fault_system_code,r.public_id as run_public_id "
            "from operations o join sim_runs r on r.id=o.run_id left join faults f on f.id=o.fault_id and f.run_id=o.run_id "
            "where o.client_id=%s and (%s::bigint[] is null or o.run_id=any(%s)) "
            "and o.started_sim >= %s - make_interval(hours=>%s) and o.started_sim <= %s "
            "order by o.started_sim desc,o.id desc limit 50",
            (id, scope, scope, as_of, ops_hours, as_of),
        )
        signals = await fetch_all(
            conn,
            "select s.id,s.public_id,s.run_id,r.public_id as run_public_id,s.text,s.channel_code,s.sentiment,s.status,s.received_sim "
            "from signals s join sim_runs r on r.id=s.run_id where s.client_id=%s "
            "and (%s::bigint[] is null or s.run_id=any(%s)) order by s.received_sim desc,s.id desc limit 50",
            (id, scope, scope),
        )
        incidents = await fetch_all(
            conn,
            "select i.id,i.public_id,i.title,i.incident_type,i.product_code,i.system_code,i.team_code,i.status,i.created_sim "
            "from incidents i where (%s::bigint[] is null or i.run_id=any(%s)) and (i.primary_client_id=%s "
            "or exists(select 1 from incident_signals x join signals s on s.id=x.signal_id and s.run_id=i.run_id "
            "where x.incident_id=i.id and s.client_id=%s) "
            "or exists(select 1 from churn_events ce where ce.closure_incident_id=i.id and ce.run_id=i.run_id and ce.client_id=%s)) "
            "order by (i.incident_type='account_closure') desc,i.created_sim desc,i.id desc limit 50",
            (scope, scope, id, id, id),
        )
        state_history = await fetch_all(
            conn,
            "select cs.id,cs.run_id,r.public_id as run_public_id,cs.state,cs.since_sim,cs.trigger,cs.care_score::double precision as care_score,cs.hazard::double precision as hazard, "
            "i.public_id as incident_public_id,s.public_id as signal_public_id "
            "from client_states cs join sim_runs r on r.id=cs.run_id "
            "left join incidents i on i.id=cs.incident_id and i.run_id=cs.run_id "
            "left join signals s on s.id=cs.signal_id and s.run_id=cs.run_id "
            "where cs.client_id=%s and (%s::bigint[] is null or cs.run_id=any(%s)) "
            "order by cs.since_sim desc,cs.id desc limit 100",
            (id, scope, scope),
        )
        state = await fetch_one(
            conn,
            "select state,since_sim,care_score::double precision as care_score,hazard::double precision as hazard from client_states where client_id=%s "
            "and (%s::bigint[] is null or run_id=any(%s)) "
            "order by (run_id=%s) desc,is_current desc,since_sim desc,id desc limit 1",
            (id, scope, scope, rid if rid not in (None, -1) else clock["current_run_id"]),
        )
        gifts = await fetch_all(
            conn,
            f"{TASK_SQL} where t.client_id=%s and t.kind='gift' and (%s::bigint[] is null or t.run_id=any(%s)) "
            "and (t.status in ('approved','changed','done') or (t.status='open' and not t.requires_hitl)) "
            "order by t.created_sim desc,t.id desc limit 50",
            (id, scope, scope),
        )
    result = {
        key: client[key]
        for key in (
            "id",
            "public_id",
            "display_name",
            "segment_code",
            "region_code",
            "city_name",
            "churn_risk",
            "is_active",
            "clv_estimate_rub",
        )
    }
    result.update(
        {
            "contacts": _mask_contacts(client["contacts"]),
            "psychotype": {
                "code": client["psychotype_code"],
                "name_ru": client["psychotype_name_ru"],
                "name_en": client["psychotype_name_en"],
                "communication_hint_ru": _COMMUNICATION_HINTS.get(
                    client["psychotype_code"], "Объясните следующий шаг и согласуйте удобный канал связи."
                ),
            },
            "products": products,
            "operations": operations,
            "signals": signals,
            "incidents": incidents,
            "state_history": state_history,
            "gifts": [_shape(row) for row in gifts],
        }
    )
    if state:
        result["current_state"] = state
    return result
