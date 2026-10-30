"""Поиск контекста SIG/INC по любому коду существующего реестра, без обхода через общих клиентов."""

from __future__ import annotations

from typing import Any

from fastapi import HTTPException

from app.search.grammar import parse
from app.trace.store import Conn, resolve


async def case_search(conn: Conn, query: str) -> tuple[str, list[Any], str]:
    parsed = parse(query)
    normalized = str(parsed["normalized"])
    pattern = "%" + normalized.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_") + "%"
    kind = parsed["kind"]
    if kind in (None, "number"):
        return "", [], pattern
    try:
        root = await resolve(conn, str(kind), str(parsed["ref"]), "all")
    except HTTPException as exc:
        if exc.status_code == 404:
            return "", [], pattern
        raise
    data = root["data"]
    kind = root["kind"]
    sql = "select %s::bigint as signal_id, %s::bigint as incident_id"
    args: list[Any] = [data.get("signal_id"), data.get("incident_id")]
    if kind in ("signal", "csi"):
        args[0] = data.get("signal_id") if kind == "csi" else data["id"]
    if kind == "incident":
        args[1] = data["id"]
    if data.get("agent_run_id"):
        sql += " union select signal_id,incident_id from agent_runs where id=%s"
        args.append(data["agent_run_id"])
    extra = {
        "client": (
            "select id,null from signals where client_id=%s union select null,id from incidents where primary_client_id=%s",
            [data.get("id")] * 2,
        ),
        "sim_run": (
            "select id,null from signals where run_id=%s union select null,id from incidents where run_id=%s",
            [data.get("id")] * 2,
        ),
        "post": ("select id,null from signals where external_post_id=%s", [data.get("id")]),
        "transcript": ("select id,null from signals where transcript_id=%s", [data.get("id")]),
        "task": ("select signal_id,incident_id from human_decisions where task_id=%s", [data.get("id")]),
        "ledger": ("select id,null from signals where source_operation_id=%s", [data.get("operation_id")]),
        "rule": ("select signal_id,null from rule_evaluations where rule_code=%s", [data.get("code")]),
        "error_code": (
            "select id,null from signals where classification->>'error_code'=%s union select null,id from incidents where error_code=%s",
            [data.get("code")] * 2,
        ),
    }.get(kind)
    if extra:
        sql += " union " + extra[0]
        args.extend(extra[1])
    if kind in ("audio_session", "employee", "branch"):
        column = {"audio_session": "id", "employee": "employee_id", "branch": "branch_id"}[kind]
        sql += f" union select s.id,a.incident_id from audio_sessions a left join transcripts t on t.audio_session_id=a.id left join signals s on s.transcript_id=t.id where a.{column}=%s"
        args.append(data["id"])
        sql += f" union select null,ca.incident_id from audio_sessions a join compliance_alerts ca on ca.session_id=a.id where a.{column}=%s"
        args.append(data["id"])
        if kind in ("employee", "branch"):
            sql += (
                f" union select s.id,null from transcripts t join signals s on s.transcript_id=t.id where t.{column}=%s"
            )
            args.append(data["id"])
    cte = (
        """with case_seeds as ("""
        + sql
        + """), case_incidents as (
      select incident_id as id from case_seeds where incident_id is not null
      union select x.incident_id from incident_signals x join case_seeds seed on seed.signal_id=x.signal_id join signals src on src.id=x.signal_id join incidents inc on inc.id=x.incident_id and inc.run_id=src.run_id
      union select ar.incident_id from agent_runs ar join case_seeds seed on seed.signal_id=ar.signal_id where ar.incident_id is not null
    ), case_signals as (
      select signal_id as id from case_seeds where signal_id is not null
      union select x.signal_id from incident_signals x join case_incidents i on i.id=x.incident_id join incidents inc on inc.id=x.incident_id join signals src on src.id=x.signal_id and src.run_id=inc.run_id
    ) """
    )
    return cte, args, pattern


async def related_entities(conn: Conn, cte: str, args: list[Any], rid: int | None) -> tuple[list[dict[str, Any]], bool]:
    """Ссылки на найденную цепочку показываются и при отсутствии запроса HITL."""
    if not cte:
        return [], False
    from app.api.common import fetch_all
    from app.trace.relations import TYPES

    sig = "(select id from display_signals)"
    inc = "(select id from display_incidents)"
    audio = f"(select audio_session_id from transcripts where signal_id in {sig} or id in (select transcript_id from display_signals))"
    conditions = {
        "signal": f"t.id in {sig}",
        "incident": f"t.id in {inc}",
        "agent_run": f"t.signal_id in {sig} or t.incident_id in {inc}",
        "human_decision": f"t.signal_id in {sig} or t.incident_id in {inc}",
        "task": f"t.incident_id in {inc}",
        "notification": f"t.signal_id in {sig} or t.incident_id in {inc}",
        "followup": f"t.signal_id in {sig} or t.incident_id in {inc}",
        "escalation": f"t.signal_id in {sig} or t.incident_id in {inc}",
        "post": f"t.signal_id in {sig} or t.id in (select external_post_id from display_signals)",
        "transcript": f"t.signal_id in {sig} or t.id in (select transcript_id from display_signals)",
        "audio_session": f"t.incident_id in {inc} or t.id in {audio}",
        "client": "t.id in (select client_id from display_signals union select primary_client_id from display_incidents)",
        "sim_run": "t.id in (select run_id from display_signals union select run_id from display_incidents)",
        "csi": f"t.signal_id in {sig}",
        "rule": f"t.code in (select rule_code from rule_evaluations where signal_id in {sig})",
        "error_code": "t.code in (select error_code from display_incidents union select classification->>'error_code' from display_signals)",
        "ledger": f"t.agent_run_id in (select id from agent_runs where signal_id in {sig}) or t.operation_id in (select source_operation_id from display_signals)",
        "employee": f"t.id in (select employee_id from transcripts where signal_id in {sig} union select employee_id from audio_sessions where id in {audio})",
        "branch": f"t.id in (select branch_id from transcripts where signal_id in {sig} union select branch_id from audio_sessions where id in {audio})",
    }
    queries = []
    for kind, predicate in conditions.items():
        spec = TYPES[kind]
        ref = (
            "case when t.code like 'VSP-%%' then t.code else 'VSP-'||t.code end"
            if kind == "branch"
            else f"t.{spec.public}::text"
        )
        queries.append(f"select '{kind}' as kind,{ref} as ref from {spec.table} t where {predicate}")
    rows = await fetch_all(
        conn,
        cte
        + """, display_signals as (
       select * from signals where id in (select id from case_signals) and (%s::bigint is null or run_id=%s)
    ), display_incidents as (
       select * from incidents where id in (select id from case_incidents) and (%s::bigint is null or run_id=%s)
    ) select * from ("""
        + " union all ".join(queries)
        + ") refs order by kind,ref limit 101",
        [*args, rid, rid, rid, rid],
    )
    return rows[:100], len(rows) > 100


async def entity_filter(conn: Conn, query: str | None, target: str) -> tuple[str, list[Any]]:
    """Фильтр до пагинации; SQL-выражения задаются вызывающим кодом, не пользователем."""
    if not query or not query.strip():
        return "true", []
    cte, args, pattern = await case_search(conn, query)
    predicates = {
        "incident": "i.id in (select id from case_incidents)",
        "agent": "ar.signal_id in (select id from case_signals) or ar.incident_id in (select id from case_incidents)",
        "transcript": "t.signal_id in (select id from case_signals) or t.id in (select transcript_id from signals where id in (select id from case_signals)) or t.audio_session_id in (select id from audio_sessions where incident_id in (select id from case_incidents))",
        "alert": "a.incident_id in (select id from case_incidents) or a.transcript_id in (select transcript_id from signals where id in (select id from case_signals)) or a.session_id in (select t.audio_session_id from transcripts t where t.signal_id in (select id from case_signals) or t.id in (select transcript_id from signals where id in (select id from case_signals)))",
    }
    direct = {
        "incident": "i.public_id",
        "agent": "'AR-'||lpad(ar.id::text,6,'0')",
        "transcript": "t.public_id",
        "alert": "a.id::text",
    }[target]
    direct_relations = {
        "incident": [],
        "agent": [],
        "transcript": [
            "t.audio_session_id in (select id from audio_sessions where public_id ilike %s)",
            "t.employee_id in (select id from employees where public_id ilike %s)",
            "t.branch_id in (select id from branches where ('VSP-'||regexp_replace(code,'^VSP-','')) ilike %s)",
            "t.client_id in (select id from clients where public_id ilike %s)",
        ],
        "alert": [
            "s.public_id ilike %s",
            "e.public_id ilike %s",
            "('VSP-'||regexp_replace(b.code,'^VSP-','')) ilike %s",
            "a.transcript_id in (select id from transcripts where public_id ilike %s)",
        ],
    }[target]
    predicate = " or ".join([f"{direct} ilike %s", *direct_relations])
    values: list[Any] = [pattern] * (1 + len(direct_relations))
    if cte:
        predicate += f" or exists ({cte} select 1 where {predicates[target]})"
        values.extend(args)
    return "(" + predicate + ")", values
