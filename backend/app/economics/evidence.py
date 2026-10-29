"""T-265: две области оценки, provenance, один риск на клиента и одно основание на сделку."""

from __future__ import annotations

import datetime as dt
from decimal import Decimal
from typing import Any

from psycopg.types.json import Jsonb

from app.api.common import fetch_all, fetch_one
from app.economics import calibration as cal
from app.economics import impact
from app.errors import Problem
from app.sim.events import dumps


def policy_for(scope: str, registry: dict[str, Any]) -> dict[str, Any] | None:
    policy = registry["fine_policies"].get(scope)
    if policy is None:
        return None
    if policy["scope"] != scope or policy["currency"] != "RUB" or policy["unit"] != "deal":
        raise ValueError("Несовместимая политика штрафов")
    amount = Decimal(str(policy["amount_rub"]))
    if not amount.is_finite() or amount < 0 or amount != amount.quantize(Decimal("0.01")):
        raise ValueError("Некорректная сумма политики")
    if scope == "observed" and any(
        not policy.get(key) or str(policy[key]).upper().startswith("DEMO")
        for key in ("basis_ref", "business_approval_ref", "legal_approval_ref")
    ):
        return None
    return dict(policy)


def qualify(row: dict[str, Any], policy: dict[str, Any] | None) -> tuple[Decimal, str]:
    if policy is None:
        return Decimal(0), "no_approved_policy"
    if row["policy_sha256"] != cal.digest(policy) or row["policy"] != policy:
        return Decimal(0), "policy_changed"
    if row["decision"] != "go":
        return Decimal(0), "no_go"
    if row["outcome"] != "prevented":
        return Decimal(0), "not_prevented"
    if not row["session_started_sim"] <= row["intervention_sim"] < row["deal_closed_sim"]:
        return Decimal(0), "late_intervention"
    if (
        not cal.timestamp(policy["effective_from_sim"])
        <= row["intervention_sim"]
        < cal.timestamp(policy["effective_until_sim"])
    ):
        return Decimal(0), "outside_policy_period"
    return Decimal(str(policy["amount_rub"])), "qualified_demo" if policy[
        "scope"
    ] == "demo" else "qualified_attestation"


async def add_evidence(conn: Any, run_id: int | None, payload: dict[str, Any]) -> dict[str, Any]:
    if run_id is None:
        raise Problem(409, "Нет текущего запуска")
    registry = cal.load_registry()
    policy = policy_for(payload["scope"], registry)
    if policy is None:
        raise Problem(409, "Сначала зарегистрируйте согласованную политику для выбранного контура")
    if policy["id"] != payload["policy_id"]:
        raise Problem(409, "Версия политики изменилась")
    sha = cal.digest(payload)
    async with conn.transaction():
        await conn.execute(
            "select pg_advisory_xact_lock(hashtextextended(%s, 0))",
            (f"finance-key:{run_id}:{payload['scope']}:{payload['idempotency_key']}",),
        )
        # Один последовательный журнал на сделку: параллельные ревизии не меняют порядок подтверждений.
        await conn.execute(
            "select pg_advisory_xact_lock(hashtextextended(%s, 0))",
            (f"finance:{run_id}:{payload['scope']}:{payload['deal_ref']}",),
        )
        existing = await fetch_one(
            conn,
            "select id, payload_sha256 from financial_evidence where run_id=%s and scope=%s and idempotency_key=%s",
            (run_id, payload["scope"], payload["idempotency_key"]),
        )
        if existing:
            if existing["payload_sha256"] != sha:
                raise Problem(409, "Ключ идемпотентности уже использован для другого содержимого")
            return {"id": existing["id"], "run_id": run_id, "replayed": True}
        source = await fetch_one(
            conn,
            """
          select i.id, i.incident_type, i.primary_client_id, s.client_id, s.started_sim, st.sim_time
          from incidents i join compliance_alerts a on a.incident_id=i.id
          join audio_sessions s on s.id=a.session_id and s.run_id=i.run_id
          cross join sim_state st
          where i.id=%s and i.run_id=%s and a.id=%s and st.id=1
        """,
            (payload["incident_id"], run_id, payload["alert_id"]),
        )
        if source is None or source["incident_type"] != "misselling":
            raise Problem(404, "Алерт мисселлинга в выбранном запуске не найден")
        if (
            source["primary_client_id"] is not None
            and source["client_id"] is not None
            and source["primary_client_id"] != source["client_id"]
        ):
            raise Problem(409, "Клиент сессии не совпадает с клиентом инцидента")
        intervention, closed = cal.timestamp(payload["intervention_sim"]), cal.timestamp(payload["deal_closed_sim"])
        if intervention < source["started_sim"] or max(intervention, closed) > source["sim_time"]:
            raise Problem(422, "Время доказательства вне наблюдаемой сессии/симуляции")
        row = await fetch_one(
            conn,
            """
          insert into financial_evidence (run_id,incident_id,alert_id,scope,deal_ref,idempotency_key,payload_sha256,
            intervention_sim,deal_closed_sim,outcome,evidence_ref,recorded_by,policy,policy_sha256)
          values (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s) returning id
        """,
            (
                run_id,
                payload["incident_id"],
                payload["alert_id"],
                payload["scope"],
                payload["deal_ref"],
                payload["idempotency_key"],
                sha,
                intervention,
                closed,
                payload["outcome"],
                payload["evidence_ref"],
                payload["recorded_by"],
                Jsonb(policy),
                cal.digest(policy),
            ),
        )
        assert row is not None
        await conn.execute(
            "select pg_notify('metrics', %s)",
            (
                dumps(
                    {
                        "type": "FINANCIAL_IMPACT_UPDATED",
                        "run_id": run_id,
                        "data": {"evidence_id": row["id"], "incident_id": payload["incident_id"]},
                    }
                ),
            ),
        )
    return {"id": row["id"], "run_id": run_id, "replayed": False}


SNAPSHOT = """
 left join lateral (
   select st.id as step_id, ar.id as agent_run_id, st.model, ar.prompt_version, ar.graph_version,
          st.output->'churn_risk' as raw_score, st.output->>'score_pipeline' as score_pipeline,
          st.output->>'churn_predicted_sim' as predicted_sim_text
   from agent_runs ar join agent_steps st on st.run_id=ar.id
   where ar.id=r.primary_agent_run_id and ar.sim_run_id=r.run_id
     and st.node in ('classify','instant_decide') and st.status in ('ok','fallback')
   order by st.seq,st.id limit 1
 ) prediction on true
"""


def risk_of(row: dict[str, Any], profile: dict[str, Any] | None) -> dict[str, Any]:
    raw_time = row.get("predicted_sim_text")
    try:
        predicted = cal.timestamp(raw_time) if raw_time else None
    except (ValueError, TypeError):
        predicted = None
    result = cal.assess(
        row.get("raw_score"),
        model=row.get("model"),
        prompt_version=row.get("prompt_version"),
        pipeline=row.get("score_pipeline"),
        predicted_sim=predicted,
        profile=profile,
    )
    if profile is not None and (
        row.get("graph_version") != "v1" or (predicted is not None and predicted > row["resolved_sim"])
    ):
        result.update(status="unknown", probability=None, reason="source_mismatch")
    if row.get("missing") or row.get("stale"):
        result.update(status="unknown", probability=None, reason="missing_economics")
    result.update(
        agent_run_id=row.get("agent_run_id"), step_id=row.get("step_id"), graph_version=row.get("graph_version")
    )
    return result


async def assessment(
    conn: Any, run_id: int | None, start: dt.datetime | None, end: dt.datetime | None
) -> dict[str, Any]:
    registry = cal.load_registry()
    profiles = {scope: cal.load_profile(scope, registry) for scope in ("demo", "observed")}
    policies = {scope: policy_for(scope, registry) for scope in ("demo", "observed")}
    aggregates: dict[str, dict[str, Any]] = {
        scope: {
            "scope": scope,
            "known_risk_rub": Decimal(0),
            "known_clients": 0,
            "unknown_clients": 0,
            "duplicate_cases": 0,
            "unidentified_cases": 0,
            "fine_rub": Decimal(0),
            "qualified_deals": 0,
            "excluded_deals": 0,
            "reasons": {},
        }
        for scope in profiles
    }
    base, args = impact.scope(run_id, None, None)
    sql = (
        """with all_cases as ("""
        + base
        + """), ranked as (
      select c.*,i.run_id,i.created_sim,i.primary_client_id,i.agent_run_id as primary_agent_run_id,
             row_number() over(partition by i.primary_client_id order by i.created_sim,i.id) as client_rank
      from all_cases c join incidents i on i.id=c.incident_id)
      select r.*,prediction.* from ranked r """
        + SNAPSHOT
        + " where true"
    )
    params = list(args)
    if start is not None:
        sql += " and r.resolved_sim >= %s and r.resolved_sim < %s"
        params.extend([start, end])
    # Память ограничена одним пакетом; выбор первого кейса клиента выполняется PostgreSQL до фильтра периода.
    refund = Decimal(0)
    case_count = 0
    complete_refunds = True
    async with conn.cursor(name="financial_cases") as cur:
        await cur.execute(sql, params)
        while rows := await cur.fetchmany(256):
            for row in rows:
                case_count += 1
                if row["missing"] or row["stale"]:
                    complete_refunds = False
                refund += Decimal(str(row["refund"]))
                for scope, agg in aggregates.items():
                    if row["primary_client_id"] is None:
                        agg["unidentified_cases"] += 1
                        continue
                    if row["client_rank"] != 1:
                        agg["duplicate_cases"] += 1
                        continue
                    risk = risk_of(row, profiles[scope])
                    if risk["status"] != "calibrated":
                        agg["unknown_clients"] += 1
                        agg["reasons"][risk["reason"]] = agg["reasons"].get(risk["reason"], 0) + 1
                    else:
                        agg["known_clients"] += 1
                        agg["known_risk_rub"] += Decimal(
                            str(impact.money(row["scenario_base"] * Decimal(str(risk["probability"]))))
                        )
    # Последняя версия каждой сделки выбирается по всему запуску; отзыв исключает прежнюю оценку.
    fine_rows = await fetch_all(
        conn,
        """
      with latest as (select distinct on (scope,deal_ref) * from financial_evidence where run_id=%s order by scope,deal_ref,id desc)
      select f.*,a.decision,s.started_sim as session_started_sim
      from latest f join compliance_alerts a on a.id=f.alert_id
      join audio_sessions s on s.id=a.session_id and s.run_id=f.run_id
      join incidents i on i.id=f.incident_id and i.run_id=f.run_id
      where i.status in ('resolved','closed') and coalesce(i.resolved_sim,i.closed_sim) is not null
    """
        + (
            " and coalesce(i.resolved_sim,i.closed_sim)>=%s and coalesce(i.resolved_sim,i.closed_sim)<%s"
            if start is not None
            else ""
        ),
        (run_id, start, end) if start is not None else (run_id,),
    )
    for row in fine_rows:
        agg = aggregates[row["scope"]]
        amount, reason = qualify(row, policies[row["scope"]])
        if reason.startswith("qualified"):
            agg["fine_rub"] += amount
            agg["qualified_deals"] += 1
        else:
            agg["excluded_deals"] += 1
            agg["reasons"][reason] = agg["reasons"].get(reason, 0) + 1
    result = []
    for scope, agg in aggregates.items():
        profile, policy = profiles[scope], policies[scope]
        complete = profile is not None and not agg["unknown_clients"] and not agg["unidentified_cases"]
        risk_total = agg["known_risk_rub"] if complete else None
        if not complete_refunds:
            agg["reasons"]["incomplete_refunds"] = 1
        net = risk_total - refund if risk_total is not None and complete_refunds else None
        fine_total = agg["fine_rub"] if policy is not None else None
        combined = (
            net + fine_total
            if net is not None and fine_total is not None and policy is not None and policy["additive_to_dcltv"]
            else None
        )
        result.append(
            {
                **agg,
                "risk_total_rub": risk_total,
                "net_rub": net,
                "refund_rub": refund,
                "fine_rub": fine_total,
                "combined_net_rub": combined,
                "calibration": profile,
                "fine_policy": policy,
                "case_count": case_count,
            }
        )
    return {"run_id": run_id, "start_date": start, "end_date": end, "horizon_days": 7, "contours": result}


async def case_proof(conn: Any, incident_id: int, run_id: int) -> dict[str, Any]:
    base, args = impact.scope(run_id, None, None)
    row = await fetch_one(
        conn,
        "with cases as ("
        + base
        + """), r as (
       select c.*,i.run_id,i.agent_run_id as primary_agent_run_id from cases c join incidents i on i.id=c.incident_id where c.incident_id=%s)
       select r.*,prediction.* from r """
        + SNAPSHOT,
        (*args, incident_id),
    )
    registry = cal.load_registry()
    risks = [
        {"scope": scope, **risk_of(row or {}, cal.load_profile(scope, registry))} for scope in ("demo", "observed")
    ]
    alerts = await fetch_all(
        conn,
        "select a.id,a.decision,s.public_id as session_ref from compliance_alerts a join audio_sessions s on s.id=a.session_id where a.incident_id=%s and s.run_id=%s order by a.id",
        (incident_id, run_id),
    )
    records = await fetch_all(
        conn,
        "select id,scope,deal_ref,intervention_sim,deal_closed_sim,outcome,evidence_ref,recorded_by,policy,policy_sha256,recorded_at from financial_evidence where incident_id=%s and run_id=%s order by id desc limit 20",
        (incident_id, run_id),
    )
    return {
        "risks": risks,
        "alerts": alerts,
        "records": records,
        "policies": {scope: policy_for(scope, registry) for scope in ("demo", "observed")},
    }
