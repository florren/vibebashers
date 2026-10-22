"""Роутер тега `agent` (OpenAPI 1.4.0). Реализовано (B04): decision-chain по шагам и tool_calls запуска."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException, Query, Request
from fastapi.responses import PlainTextResponse

from app.api.common import db, fetch_all, fetch_one

router = APIRouter(tags=["agent"])


@router.get(
    "/api/agent/runs/{id}/decision-chain",
    summary="[ДТЗ FR-3.5] Компактная цепочка решений «инструмент → аргументы → почему» (JSON или Markdown)",
)
async def get_agent_runs_id_decision_chain(request: Request, id: int, format: str = Query(default="json")) -> Any:  # noqa: A002
    async with db() as conn:
        run = await fetch_one(
            conn,
            "select id, signal_id, incident_id, outcome, prompt_version, started_at, finished_at from agent_runs where id = %s",
            (id,),
        )
        if not run:
            raise HTTPException(status_code=404, detail="запуск агента не найден")
        steps = await fetch_all(
            conn,
            "select seq, node, status, reasoning, coalesce(tool_calls, '[]'::jsonb) as tool_calls, output, latency_ms from agent_steps where run_id = %s order by seq",
            (id,),
        )
    chain = []
    for st in steps:
        for tc in st["tool_calls"] or []:
            chain.append(
                {
                    "seq": st["seq"],
                    "node": st["node"],
                    "tool": tc.get("name"),
                    "args": tc.get("args"),
                    "ok": tc.get("ok"),
                    "side_effect": tc.get("side_effect"),
                    "why_ru": (st.get("reasoning") or "")[:300],
                    "ms": tc.get("ms"),
                }
            )
        if not st["tool_calls"] and st["node"] in ("normalize", "classify", "decide", "wait_human", "close"):
            chain.append(
                {
                    "seq": st["seq"],
                    "node": st["node"],
                    "tool": None,
                    "args": None,
                    "ok": st["status"] != "error",
                    "side_effect": False,
                    "why_ru": (st.get("reasoning") or "")[:300],
                    "ms": st.get("latency_ms"),
                }
            )
    result = {
        "agent_run_id": id,
        "signal_id": run["signal_id"],
        "incident_id": run["incident_id"],
        "outcome": run["outcome"],
        "prompt_version": run["prompt_version"],
        "steps": chain,
    }
    if format == "markdown":
        lines = [f"# Цепочка решений — запуск агента #{id}", ""]
        for c in chain:
            tool = f"`{c['tool']}`" if c["tool"] else f"узел `{c['node']}`"
            lines.append(
                f"{c['seq']}. {tool} — {c['why_ru'] or '—'}" + (f" (аргументы: {c['args']})" if c["args"] else "")
            )
        return PlainTextResponse("\n".join(lines), media_type="text/markdown")
    return result
