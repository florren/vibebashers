"""Только реальные notification/task/incident facts, без LLM оценки и записей."""

from __future__ import annotations

import datetime as dt
import re
from typing import Any

import psycopg
from psycopg.rows import dict_row

from app.agent.policies import PARTNER_PRIVILEGES, forbidden_phrases
from app.contracts.events.behavior.psychotype_params import PsychotypeParams
from app.sim.behavior.care import CareObservation, CommunicationEvidence, GiftEvidence, SlaEvidence


async def rows(conn: psycopg.AsyncConnection[Any], sql: str, args: tuple[Any, ...]) -> list[dict[str, Any]]:
    async with conn.cursor(row_factory=dict_row) as cursor:
        await cursor.execute(sql, args)
        return list(await cursor.fetchall())


def template_fields_present(template: str, body: str, variables: list[str]) -> bool:
    """Только полностью заполненный известный template, не догадка по ключевым словам."""
    parts = re.split(r"\{\{\s*([a-zA-Z_][a-zA-Z0-9_]*)\s*\}\}", template)
    if set(parts[1::2]) != set(variables):
        return False
    pattern = "".join(re.escape(part) if index % 2 == 0 else "(.+?)" for index, part in enumerate(parts))
    matched = re.fullmatch(pattern, body, flags=re.S)
    return (
        matched is not None
        and all(value.strip() for value in matched.groups())
        and "{{" not in body
        and "}}" not in body
    )


async def related(
    conn: psycopg.AsyncConnection[Any], current: dict[str, Any], *, signal_id: int | None, incident_id: int | None
) -> bool:
    found = await rows(
        conn,
        "with recursive lineage as ("
        "select s.id,s.parent_signal_id,s.source_operation_id,s.source_fault_id,array[s.id] path,1 depth from signals s "
        "where s.run_id=%s and s.client_id=%s and (s.id=%s or exists(select 1 from incident_signals x join incidents i on i.id=x.incident_id "
        "where x.signal_id=s.id and i.id=%s and i.run_id=s.run_id)) union all "
        "select p.id,p.parent_signal_id,p.source_operation_id,p.source_fault_id,l.path||p.id,l.depth+1 "
        "from lineage l join signals p on p.id=l.parent_signal_id where p.run_id=%s and p.client_id=%s and l.depth<64 and not p.id=any(l.path)) "
        "select 1 from behavior_causes b where b.run_id=%s and b.client_id=%s and b.episode_no=%s and ("
        "exists(select 1 from lineage s where s.source_operation_id=b.operation_id or (b.fault_id is not null and s.source_fault_id=b.fault_id)) "
        "or exists(select 1 from incidents i where i.id=%s and i.run_id=b.run_id and b.fault_id is not null and i.fault_id=b.fault_id)) limit 1",
        (
            current["run_id"],
            current["client_id"],
            signal_id,
            incident_id,
            current["run_id"],
            current["client_id"],
            current["run_id"],
            current["client_id"],
            current["episode_no"],
            incident_id,
        ),
    )
    return bool(found)


async def notification_observations(
    conn: psycopg.AsyncConnection[Any], current: dict[str, Any], notification_id: int
) -> tuple[CareObservation, ...]:
    data = await rows(
        conn,
        "select * from notifications where id=%s and run_id=%s and client_id=%s and recipient_type in ('client','public')",
        (notification_id, current["run_id"], current["client_id"]),
    )
    if not data:
        return ()
    notice = data[0]
    if notice["status"] not in ("sent", "delivered") or notice["sent_sim"] is None:
        return ()
    if not await related(conn, current, signal_id=notice["signal_id"], incident_id=notice["incident_id"]):
        return ()
    at: dt.datetime = notice["sent_sim"]
    body = notice["body"]
    valid = bool(body.strip()) and not forbidden_phrases(body) and "{{" not in body and "}}" not in body
    templates = await rows(
        conn,
        "select body,variables from notification_templates where code=%s and (segment_code=%s or segment_code is null)",
        (notice["template_code"], current["segment_code"]),
    )
    complete = any(template_fields_present(row["body"], body, row["variables"]) for row in templates)
    result: list[CareObservation] = [
        CommunicationEvidence(
            notification_id,
            at,
            notice["status"],
            True,
            valid,
            notice["template_code"] == "proactive_fault",
            notice["template_code"] or "",
            complete,
        )
    ]
    if notice["incident_id"] is not None:
        incident = await rows(
            conn,
            "select sla_breached from incidents where id=%s and run_id=%s",
            (notice["incident_id"], current["run_id"]),
        )
        breach = await rows(
            conn,
            "select 1 from sim_events where run_id=%s and sim_time<=%s "
            "and event_type in ('sla.breached','sla.report_missing','sla.first_response_overdue') "
            "and payload->>'incident_id'=%s limit 1",
            (current["run_id"], at, str(notice["incident_id"])),
        )
        if incident and (valid or incident[0]["sla_breached"] or breach):
            result.append(SlaEvidence(notice["incident_id"], at, True, bool(incident[0]["sla_breached"] or breach)))
    if valid and notice["template_code"] == "gift_offer":
        params = PsychotypeParams.model_validate(current["params_snapshot"])
        tasks = await rows(
            conn,
            "select id,payload from tasks where run_id=%s and client_id=%s and incident_id=%s "
            "and kind='gift' and status='done'",
            (current["run_id"], current["client_id"], notice["incident_id"]),
        )
        for task in tasks:
            payload = task["payload"] or {}
            issued = payload.get("issued") or {}
            gift = payload.get("gift") or {}
            # Существующий producer не хранит notification_id в issued: проверяем
            # его точные persisted label+sim_time, не соседство по времени/ID.
            if (
                not isinstance(issued, dict)
                or not isinstance(gift, dict)
                or not isinstance(issued.get("label"), str)
                or not issued["label"].strip()
                or issued["label"] not in body
            ):
                continue
            stamp = issued.get("sim_time")
            if not isinstance(stamp, str) or dt.datetime.fromisoformat(stamp) != at:
                continue
            points = gift.get("points")
            if (
                gift.get("gift_code") == "bonus_points"
                and isinstance(points, int)
                and not isinstance(points, bool)
                and points > 0
            ):
                result.append(
                    GiftEvidence(task["id"], at, "bonus_points", True, True, notice["status"], params.gift_elasticity)
                )
            if gift.get("privilege_code") in PARTNER_PRIVILEGES:
                if params.privilege_elasticity is None:
                    raise ValueError("pinned privilege_elasticity отсутствует; default запрещён")
                result.append(
                    GiftEvidence(
                        task["id"], at, "partner_privilege", True, True, notice["status"], params.privilege_elasticity
                    )
                )
    return tuple(result)
