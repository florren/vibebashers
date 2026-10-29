"""Eight-stage narrative projection of recorded trace data (ТЗ 27)."""

from __future__ import annotations

from datetime import datetime
from pathlib import Path
from typing import Any

import yaml
from fastapi import HTTPException

from app.api.common import fetch_one
from app.search.grammar import parse
from app.trace.assembler import assemble
from app.trace.privacy import mask
from app.trace.projections import node_key, project
from app.trace.store import Conn, allowed_run

STAGES = ("intake", "understanding", "identity", "rules", "decision", "action", "execution", "client_outcome")
STAGE_EVENTS = (
    ("source_message", "signal_created"),
    ("signal_normalized", "classification"),
    ("client_identified", "operation", "fault", "fee"),
    ("rule_evaluation", "policy_check"),
    ("decision", "human_request", "human_decision", "escalation", "compliance_alert"),
    ("tool_call", "incident_created", "incident_linked", "refund", "task"),
    ("team_action", "incident_status", "followup", "zone_changed"),
    ("notification", "public_reply", "client_reaction", "gift", "economics", "terminal", "churn"),
)
EVENT_STAGE = {event: stage for stage, events in zip(STAGES, STAGE_EVENTS, strict=True) for event in events}


def seconds(start: str | None, end: str | None) -> float | None:
    if not start or not end:
        return None
    return max(
        0,
        (
            datetime.fromisoformat(end.replace("Z", "+00:00")) - datetime.fromisoformat(start.replace("Z", "+00:00"))
        ).total_seconds(),
    )


def client_messages(nodes: list[dict[str, Any]]) -> list[dict[str, Any]]:
    lane = []
    for n in nodes:
        k, d = n["kind"], n["data"]
        if (
            k == "notification"
            and d.get("recipient_type") == "client"
            and d.get("status") in ("sent", "delivered")
            and d.get("sent_at")
        ):
            template = str(d.get("template_code") or "")
            message_kind = next((v for v in ("gift", "clarification", "final", "ack") if v in template), "status")
            lane.append(
                {
                    "channel_code": d["channel_code"],
                    "kind": message_kind,
                    "text_ru": mask(d["body"], 2000),
                    "delivered_at": str(d["sent_at"]),
                    "delivered_sim": d.get("sent_sim"),
                }
            )
        elif k == "reply" and d.get("author") in ("agent", "human"):
            lane.append(
                {
                    "channel_code": "social_reply",
                    "kind": "public_reply",
                    "text_ru": mask(d["text"], 2000),
                    "delivered_at": str(d["published_at"]),
                    "delivered_sim": None,
                }
            )
        elif k == "reaction" and d.get("text"):
            lane.append(
                {
                    "channel_code": "client_reaction",
                    "kind": "status",
                    "text_ru": mask(d["text"], 2000),
                    "delivered_at": str(d["created_at"]),
                    "delivered_sim": d.get("reacted_sim"),
                }
            )
    return sorted(lane, key=lambda m: m["delivered_at"])


def build_journey(
    trace: dict[str, Any], nodes: list[dict[str, Any]], notes: dict[str, str] | None = None
) -> dict[str, Any]:
    events = [
        project(
            n,
            "subject"
            if i == 0
            else "before"
            if n in nodes[1:] and any(e["id"] == "EVT-" + node_key(n) for e in trace["before"])
            else "after",
        )
        for i, n in enumerate(nodes)
        if n["kind"] not in {"client", "employee", "branch", "rule", "error_code", "sim_run", "agent_run"}
    ]
    grouped = {s: [e for e in events if EVENT_STAGE[e["kind"]] == s] for s in STAGES}
    for values in grouped.values():
        values.sort(key=lambda e: (e["ts_sim"] or e["ts_real"], e["id"]))
    # Статические справочники и запуск агента не являются выполненными стадиями.
    # Early acknowledgements do not advance the internal workflow to its final stage.
    active = 7 if trace["terminal"]["reached"] else max((i for i, s in enumerate(STAGES[:-1]) if grouped[s]), default=0)
    # Параллельная эскалация руководителю создаёт HITL-запись, но не блокирует агент.
    # Обычный запрос решения по-прежнему останавливает путь, даже если есть ответ клиенту.
    waiting = any(
        n["kind"] == "human_decision"
        and not n["data"].get("decision")
        and (n["data"].get("agent_proposal") or {}).get("kind") != "escalation"
        for n in nodes
    )
    if waiting:
        active = STAGES.index("decision")
    reached = trace["terminal"]["reached"] and not waiting
    stages = []
    for i, stage in enumerate(STAGES):
        values = grouped[stage]
        status = (
            "waiting_human"
            if waiting and i == active
            else "done"
            if values and (i < active or reached)
            else "active"
            if i == active
            else "skipped"
            if i < active
            else "pending"
        )
        if values:
            for clock, label in (("ts_sim", "Длительность стадии сим, с"), ("ts_real", "Длительность стадии реал, с")):
                times = sorted(e[clock] for e in values if e[clock])
                duration = seconds(times[0], times[-1]) if times else None
                if duration is not None:
                    values[0]["key_facts"].append(
                        {"label_ru": label, "value_ru": str(round(duration, 3)), "masked": False}
                    )
        if values and notes and stage in notes:
            values[0]["key_facts"].append(
                {"label_ru": "Заметка ведущего", "value_ru": notes[stage][:200], "masked": False}
            )
        stages.append({"stage": stage, "status": status, "events": values})
    lane = client_messages(nodes)
    first = min((e["ts_real"] for e in events if e["kind"] == "signal_created"), default=None)
    first_reply = next((m["delivered_at"] for m in lane if m["channel_code"] != "client_reaction"), None)
    delay = seconds(first, first_reply)
    if delay is not None and grouped["intake"]:
        grouped["intake"][0]["key_facts"].append(
            {"label_ru": "Первый ответ, с", "value_ru": str(round(delay, 3)), "masked": False}
        )
    money = sum(float(n["data"]["amount"]) for n in nodes if n["kind"] == "ledger" and n["data"]["kind"] == "refund")
    sources = {e["badges"].get("llm_source") for e in events}
    source = "mock" if "mock" in sources else "replay" if "replay" in sources else "live"
    sim_times = sorted(e["ts_sim"] for e in events if e["ts_sim"])
    duration = seconds(sim_times[0], sim_times[-1]) if sim_times else None
    return {
        "subject": {k: trace["subject"][k] for k in ("kind", "ref", "title_ru")},
        "stages": stages,
        "client_lane": lane,
        "summary": {
            "outcome_ru": "Ожидаем решения человека" if waiting else trace["terminal"]["outcome_ru"],
            "amount_rub": money or None,
            "duration_sim": f"PT{duration:g}S" if duration is not None else None,
            "llm_source": source,
        },
    }


async def journey(conn: Conn, ref: str, run_id: str = "current", presenter: bool = False) -> dict[str, Any]:
    p = parse(ref)
    kind = p["kind"] or "signal"
    if kind == "number":
        kind = "signal"
    trace, nodes = await assemble(conn, kind, ref, run_id=run_id)
    notes = None
    if presenter:
        rid = nodes[0].get("scope_id")
        row = await fetch_one(conn, "SELECT scenario_id FROM sim_runs WHERE id=%s", (rid,))
        scenario = str((row or {}).get("scenario_id") or "")
        all_notes = yaml.safe_load((Path(__file__).parent / "notes/journey_notes.yaml").read_text())
        number = 8 if "qr" in scenario else 11 if "sarcasm" in scenario else 1 if "deposit" in scenario else None
        notes = all_notes.get(number)
    return build_journey(trace, nodes, notes)


async def latest(conn: Conn, origin: str, run_id: str) -> dict[str, Any]:
    rid = await allowed_run(conn, run_id)
    condition = {
        "any": "true",
        "jury": "s.origin='jury'",
        "feed": "s.external_post_id IS NOT NULL",
        "sim": "s.origin IN ('sim','scenario')",
    }[origin]
    row = await fetch_one(
        conn,
        f"SELECT s.public_id FROM signals s WHERE {condition} AND (%s::bigint IS NULL OR s.run_id=%s OR s.run_id IN (SELECT id FROM sim_runs WHERE kind='baseline')) ORDER BY s.received_at DESC, s.id DESC LIMIT 1",
        (rid, rid),
    )
    if not row:
        raise HTTPException(404, "Обращений пока нет")
    result = await journey(conn, row["public_id"], run_id)
    result["latest_href"] = "/journey/" + row["public_id"]
    return result
