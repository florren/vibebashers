"""Роутер тега `agent` (OpenAPI 1.4.0). Реализовано (B04): decision-chain по шагам и tool_calls запуска."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException, Query, Request
from fastapi.responses import PlainTextResponse

from app.agent.tools.write import PII_RE
from app.api.common import db, fetch_all, fetch_one
from app.sim.events import dumps

router = APIRouter(tags=["agent"])


async def build_decision_chain(conn: Any, agent_run_id: int) -> dict[str, Any] | None:
    """Цепочка решений запуска по контракту `events/agent/decision_chain.schema.json`: инструмент → аргументы (ПДн маскированы) → почему."""
    run = await fetch_one(
        conn,
        "select ar.id, ar.signal_id, ar.incident_id, ar.outcome, i.public_id as ticket_id, s.decision->>'router_action' as router_action, "
        "coalesce(lp.provider, 'mock') as provider "
        "from agent_runs ar left join incidents i on i.id = ar.incident_id left join signals s on s.id = ar.signal_id "
        "left join llm_profiles lp on lp.id = ar.llm_profile_id where ar.id = %s",
        (agent_run_id,),
    )
    if not run:
        return None
    steps = await fetch_all(
        conn,
        "select seq, node, status, reasoning, coalesce(tool_calls, '[]'::jsonb) as tool_calls, output, latency_ms from agent_steps where run_id = %s order by seq",
        (agent_run_id,),
    )
    chain: list[dict[str, Any]] = []
    n = 0
    for st in steps:
        why = PII_RE.sub("[скрыто]", (st.get("reasoning") or ""))[:600]
        for tc in st["tool_calls"] or []:
            n += 1
            res = tc.get("result")
            brief = res if isinstance(res, str) else (dumps(res) if res is not None else None)
            chain.append(
                {
                    "step": n,
                    "node": st["node"],
                    "tool": tc.get("name"),
                    "args": _mask(tc.get("args")),
                    "result_brief": (PII_RE.sub("[скрыто]", brief)[:300] if brief else None),
                    "why_ru": why or f"вызов {tc.get('name')}",
                    "latency_ms": int(tc["ms"]) if tc.get("ms") is not None else None,
                    "wraps": ["side_effect"]
                    if tc.get("side_effect")
                    else (["failed"] if tc.get("ok") is False else None),
                }
            )
        if not st["tool_calls"] and st["node"] in (
            "normalize",
            "classify",
            "decide",
            "wait_human",
            "close",
            "check_rules",
            "identify_client",
        ):
            n += 1
            out = st.get("output")
            chain.append(
                {
                    "step": n,
                    "node": st["node"],
                    "tool": None,
                    "args": None,
                    "result_brief": (PII_RE.sub("[скрыто]", dumps(out))[:300] if out else None),
                    "why_ru": why or f"узел {st['node']}",
                    "latency_ms": int(st["latency_ms"]) if st.get("latency_ms") is not None else None,
                    "wraps": ["error"] if st["status"] == "error" else None,
                }
            )
    ra = (
        run["router_action"]
        if run["router_action"] in ("route", "escalate", "request_clarification", "none")
        else "none"
    )
    provider = str(run["provider"] or "mock")
    return {
        "agent_run_id": agent_run_id,
        "signal_id": run["signal_id"],
        "ticket_id": run["ticket_id"],
        "router_action": ra,
        "llm_source": "mock" if provider == "mock" else "live",
        "steps": chain,
    }


def _mask(args: Any) -> dict[str, Any] | None:
    if not isinstance(args, dict):
        return None
    return {k: (PII_RE.sub("[скрыто]", v) if isinstance(v, str) else v) for k, v in args.items()}


@router.get(
    "/api/agent/runs/{id}/decision-chain",
    summary="[ДТЗ FR-3.5] Компактная цепочка решений «инструмент → аргументы → почему» (JSON или Markdown)",
)
async def get_agent_runs_id_decision_chain(request: Request, id: int, format: str = Query(default="json")) -> Any:  # noqa: A002
    async with db() as conn:
        result = await build_decision_chain(conn, id)
    if result is None:
        raise HTTPException(status_code=404, detail="запуск агента не найден")
    chain = result["steps"]
    if format == "markdown":
        lines = [f"# Цепочка решений — запуск агента #{id}", ""]
        for c in chain:
            tool = f"`{c['tool']}`" if c["tool"] else f"узел `{c['node']}`"
            lines.append(
                f"{c['step']}. {tool} — {c['why_ru'] or '—'}" + (f" (аргументы: {c['args']})" if c["args"] else "")
            )
        return PlainTextResponse("\n".join(lines), media_type="text/markdown")
    return result
