"""Bounded causal trace assembly; reads recorded facts only (ТЗ 28.3)."""

from __future__ import annotations

from collections import defaultdict
from time import perf_counter
from typing import Any

from app.api.common import fetch_one
from app.trace.projections import OUTCOMES, node_key, project, reference, time_value
from app.trace.store import Conn, allowed_run, neighbors, resolve


async def collect(
    conn: Conn, subject: dict[str, Any], direction: str, rid: int | None, depth: int, limit: int
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], bool]:
    seen = {node_key(subject)}
    frontier = [subject]
    nodes: list[dict[str, Any]] = []
    edges: list[dict[str, Any]] = []
    truncated = False
    for _ in range(depth):
        rows = await neighbors(conn, frontier, direction, rid)
        frontier = []
        for row in rows:
            key = node_key(row)
            edge = {"from": "EVT-" + row["parent"], "to": "EVT-" + key, "relation_ru": "Привело к событию"}
            if direction == "before":
                edge["from"], edge["to"] = edge["to"], edge["from"]
            edges.append(edge)
            if key in seen:
                continue
            seen.add(key)
            if len(nodes) >= limit:
                truncated = True
                continue
            nodes.append(row)
            frontier.append(row)
        if not frontier:
            break
    else:
        # Depth is a documented bound, not a claim that the graph ended here.
        if frontier:
            truncated = truncated or any(
                node_key(n) not in seen for n in await neighbors(conn, frontier, direction, rid)
            )
    return nodes, edges, truncated


def pending_steps(nodes: list[dict[str, Any]]) -> list[dict[str, Any]]:
    result = []
    for node in nodes:
        k, d = node["kind"], node["data"]
        label, due = None, None
        if k == "human_decision" and not d.get("decision"):
            label = "Ожидается решение человека"
        elif k == "followup" and d["status"] == "scheduled":
            label, due = "Ожидается повторная проверка", d["wake_sim"]
        elif k == "task" and d["status"] in ("open", "approved", "changed"):
            label, due = "Ожидается выполнение задачи", d.get("due_sim")
        elif k == "incident" and d["status"] not in ("closed", "rejected", "duplicate"):
            label, due = "Срок SLA", d.get("sla_due_sim")
        if label:
            result.append({"kind_ru": label, "due_sim": due, "object_ref": {"kind": k, "ref": reference(node)}})
    return result


def terminal_for(subject: dict[str, Any], after: list[dict[str, Any]]) -> dict[str, Any]:
    kind = subject["kind"]
    candidates = []
    for node in [subject, *after]:
        k, d = node["kind"], node["data"]
        reached = False
        if k == "incident" and kind in ("signal", "incident", "post", "transcript", "audio_session"):
            reached = d["status"] in ("closed", "rejected", "duplicate")
        elif k == "signal" and kind == "signal":
            reached = d["status"] in ("closed", "answered", "noise")
        elif k == "reply" and kind in ("signal", "post"):
            reached = d.get("author") in ("agent", "human")
        elif kind == "ledger" and k == "ledger":
            reached = d.get("kind") in ("refund", "reversal")
        elif kind == "notification" and k == "reaction":
            reached = True
        elif kind == "post" and k == "escalation":
            reached = True
        elif node is subject:
            reached = (
                (kind == "agent_run" and d.get("outcome") in ("completed", "failed", "fallback_mock", "cancelled"))
                or (kind == "human_decision" and bool(d.get("decision")))
                or (kind == "task" and d.get("status") in ("done", "rejected", "cancelled"))
                or (kind == "escalation" and d.get("status") in ("resolved", "dismissed"))
                or (kind == "ledger" and d.get("kind") in ("refund", "reversal"))
            )
        if reached:
            candidates.append(node)
    if not candidates:
        return {"reached": False, "event_ref": None, "outcome_ru": "Обработка продолжается"}
    last = max(candidates, key=lambda n: time_value(n["data"]) or time_value(n["data"], True) or "")
    d = last["data"]
    outcome = d.get("outcome_class") or d.get("outcome") or d.get("status")
    fallback = {
        "ledger": "Возврат выполнен",
        "reaction": "Реакция клиента получена",
        "escalation": "Передано руководителю",
        "reply": "Ответ клиенту опубликован",
    }.get(last["kind"], "Решение исполнено")
    return {
        "reached": True,
        "event_ref": "EVT-" + node_key(last),
        "outcome_ru": OUTCOMES.get(str(outcome), fallback),
    }


def causal_order(nodes: list[dict[str, Any]], edges: list[dict[str, Any]]) -> list[dict[str, Any]]:
    remaining = {"EVT-" + node_key(n): n for n in nodes}
    ordered = []
    while remaining:
        incoming = {e["to"] for e in edges if e["from"] in remaining and e["to"] in remaining}
        ready = [k for k in remaining if k not in incoming]
        # Cycles in recorded data are broken deterministically; traversal is already deduplicated.
        key = min(
            ready or list(remaining),
            key=lambda k: (time_value(remaining[k]["data"]) or time_value(remaining[k]["data"], True) or "", k),
        )
        ordered.append(remaining.pop(key))
    return ordered


def render(
    subject: dict[str, Any],
    before: list[dict[str, Any]],
    after: list[dict[str, Any]],
    edges: list[dict[str, Any]],
    *,
    before_truncated: bool = False,
    after_truncated: bool = False,
    after_limit: int = 200,
    fanout: int = 8,
) -> dict[str, Any]:
    # BFS guarantees causal depth first; timestamps only order independent siblings.
    groups = []
    phases: dict[str, list[dict[str, Any]]] = {"before": [], "after": []}
    counts = {"before": len(before), "after": len(after)}
    for phase, nodes in (("before", before), ("after", after)):
        buckets: dict[tuple[str, str], list[dict[str, Any]]] = defaultdict(list)
        for node in nodes:
            buckets[(node.get("parent", ""), project(node, phase)["kind"])].append(node)
        collapsed: set[str] = set()
        for (_, kind), values in buckets.items():
            if len(values) > fanout and kind in ("signal_created", "notification"):
                count = max(len(values), *(int(n.get("total", 0)) for n in values))
                counts[phase] += count - len(values)
                groups.append(
                    {
                        "kind": kind,
                        "count": count,
                        "sample_refs": [reference(n) for n in values[:3]],
                        "expand_hint_ru": "Откройте след образца для подробностей",
                    }
                )
                collapsed.update(node_key(n) for n in values[3:])
        ordered = causal_order(nodes, edges)
        for node in ordered:
            if node_key(node) in collapsed:
                continue
            event = project(node, phase)
            st, et = time_value(subject["data"]), event["ts_sim"]
            event["order_warning"] = bool(
                st and et and ((phase == "before" and et > st) or (phase == "after" and et < st))
            )
            phases[phase].append(event)
    subj = project(subject, "subject")
    subject_title = subj["brief_ru"][:200]
    if subject["kind"] == "ledger":
        subject_title = f"{subject_title[:170]} · {subj['badges']['amount_rub']:.2f} ₽"
    # TraceResponse has no subject-event field; its facts remain available in journey projections.
    visible_before, visible_after = phases["before"][:40], phases["after"][:after_limit]
    visible = {subj["id"], *(e["id"] for e in visible_before), *(e["id"] for e in visible_after)}
    terminal = terminal_for(subject, after)
    if terminal.get("event_ref") not in visible:
        terminal_node: dict[str, Any] | None = next(
            (n for n in after if "EVT-" + node_key(n) == terminal.get("event_ref")), None
        )
        if terminal_node and after_limit:
            event = project(terminal_node, "after")
            visible_after = [*visible_after[: after_limit - 1], event]
            visible.add(event["id"])
    return {
        "subject": {
            "kind": subject["kind"],
            "ref": reference(subject),
            "title_ru": subject_title,
            "status": subject["data"].get("status") or subject["data"].get("outcome"),
        },
        "before": visible_before,
        "after": visible_after,
        "edges": [e for e in edges if e["from"] in visible and e["to"] in visible],
        "groups": groups,
        "pending": pending_steps([subject, *before, *after]),
        "terminal": terminal,
        "stats": {
            "before_count": counts["before"],
            "after_count": counts["after"],
            "build_ms": 0,
            "truncated_before": before_truncated or len(phases["before"]) > 40,
            "truncated_after": after_truncated or len(phases["after"]) > after_limit,
        },
    }


async def assemble(
    conn: Conn, kind: str, ref: str, *, run_id: str = "all", before_depth: int = 3, after_limit: int = 200
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    start = perf_counter()
    subject = await resolve(conn, kind, ref, run_id)
    rid = await allowed_run(conn, run_id)
    settings = await fetch_one(conn, "SELECT value FROM settings WHERE key='trace'")
    config = (settings or {}).get("value") or {}
    depth = min(before_depth, int(config.get("before_depth", 3)), 3)
    before, be, bt = await collect(conn, subject, "before", rid, depth, 241)
    after, ae, at = await collect(conn, subject, "after", rid, 10, 1000)
    result = render(
        subject,
        before,
        after,
        [*be, *ae],
        before_truncated=bt,
        after_truncated=at,
        after_limit=after_limit,
        fanout=int(config.get("fanout_threshold", 8)),
    )
    result["stats"]["build_ms"] = round((perf_counter() - start) * 1000)
    return result, [subject, *before, *after]
