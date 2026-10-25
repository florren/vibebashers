"""Роутер тега `engine` (OpenAPI 1.4.0). Реализовано (B04): /api/agent/runs, /api/agent/runs/{id}, /api/agent/graph. Остальное — T-106."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException, Query, Request

from app.agent.graph import GRAPH_SPEC
from app.api.common import db, fetch_all, fetch_one, page, resolve_run_id
from app.errors import NotImplementedYet

router = APIRouter(tags=["engine"])


RUN_SQL = (
    "select ar.id, ar.kind, ar.signal_id, ar.incident_id, ar.client_id, coalesce(lp.code, 'default') as llm_profile_code, ar.prompt_version, ar.graph_version, ar.outcome, ar.needed_human, "
    "ar.total_tokens, ar.prompt_tokens, ar.completion_tokens, ar.total_latency_ms, ar.started_at, ar.finished_at, ar.started_sim, ar.error, ar.cost_estimate, "
    "(select node from agent_steps st where st.run_id = ar.id order by seq desc limit 1) as current_node "
    "from agent_runs ar left join llm_profiles lp on lp.id = ar.llm_profile_id"
)


@router.get("/api/agent/runs", summary="Запуски агента (живая трассировка)")
async def get_agent_runs(
    request: Request,
    run_id: str = Query(default="current"),
    kind: str | None = None,
    signal_id: int | None = None,
    outcome: str | None = None,
    limit: int = Query(default=50, ge=1, le=500),
    cursor: str | None = None,
) -> Any:
    async with db() as conn:
        rid = await resolve_run_id(conn, run_id)
        where: list[str] = ["true"]
        args: list[Any] = []
        if rid is not None:
            where.append("ar.sim_run_id = %s")
            args.append(rid)
        for col, val in (("ar.kind", kind), ("ar.signal_id", signal_id), ("ar.outcome", outcome)):
            if val is not None:
                where.append(f"{col} = %s")
                args.append(val)
        if cursor is not None:
            try:
                cursor_id = int(cursor)
            except ValueError as exc:
                raise HTTPException(status_code=422, detail="cursor должен быть целым числом") from exc
            where.append("ar.id < %s")
            args.append(cursor_id)
        rows = await fetch_all(
            conn, f"{RUN_SQL} where {' and '.join(where)} order by ar.id desc limit %s", [*args, limit]
        )  # noqa: S608
    return page(rows, limit)


@router.get(
    "/api/agent/runs/{id}", summary="Запуск с деревом шагов (промпты, ответы, инструменты, токены, латентность)"
)
async def get_agent_runs_id(request: Request, id: int) -> Any:  # noqa: A002
    async with db() as conn:
        run = await fetch_one(conn, f"{RUN_SQL} where ar.id = %s", (id,))  # noqa: S608
        if not run:
            raise HTTPException(status_code=404, detail="запуск агента не найден")
        steps = await fetch_all(
            conn,
            "select seq, node, status, input, output, prompt, response_raw, reasoning, coalesce(tool_calls, '[]'::jsonb) as tool_calls, model, prompt_tokens, completion_tokens, latency_ms, started_at, finished_at from agent_steps where run_id = %s order by seq",
            (id,),
        )
        hd = await fetch_one(
            conn,
            "select id, reason, decision, recommendation, options, decided_by, comment, requested_sim, decided_sim from human_decisions where agent_run_id = %s order by id desc limit 1",
            (id,),
        )
    for st in steps:
        if st["node"] == "wait_human" and isinstance(st.get("input"), dict) and "signal" in st["input"]:
            st["input"] = {
                "checkpoint": True,
                "signal_id": st["input"]["signal"].get("id"),
                "current_node": st["input"].get("current_node"),
            }
    return {**run, "steps": steps, "human_decision": hd, "cost_estimate": float(run.get("cost_estimate") or 0)}


@router.get("/api/agent/graph", summary="Схема графа LangGraph (узлы, рёбра) для подсветки текущего узла")
async def get_agent_graph(request: Request) -> Any:
    return GRAPH_SPEC


@router.post(
    "/api/agent/compare", summary="Панель «ИИ против правил» — один текст через LLM-профиль и mock параллельно"
)
async def post_agent_compare(request: Request) -> Any:
    raise NotImplementedYet("T-106")


@router.get("/api/engine/entity-graph", summary="Граф сущностей клиент–сигнал–инцидент–система–команда (React Flow)")
async def get_engine_entity_graph(request: Request) -> Any:
    raise NotImplementedYet("T-106")


# T-108: только чтение. Имена не подставляются в SQL вне этого множества.
DB_ALLOW = frozenset(
    {
        "signals",
        "incidents",
        "incident_status_history",
        "notifications",
        "tasks",
        "agent_runs",
        "agent_steps",
        "client_states",
        "churn_events",
        "incident_economics",
        "faults",
    }
)
_CONTACT_KEYS = frozenset({"phone", "email", "contacts", "contact", "contacts_hint"})


def _mask_row(row: dict[str, Any]) -> dict[str, Any]:
    out = dict(row)
    for key in list(out):
        if key in _CONTACT_KEYS or key.endswith("_phone") or key.endswith("_email"):
            out[key] = None
    return out


@router.get("/api/engine/db/tables", summary="Счётчики строк по таблицам (реальное время)")
async def get_engine_db_tables(request: Request) -> Any:
    async with db() as conn:
        last = await fetch_all(
            conn,
            "select table_name, max(ts) as last_change_at from db_activity_log where table_name = any(%s) group by table_name",
            (list(DB_ALLOW),),
        )
        exact: dict[str, int] = {}
        for name in sorted(DB_ALLOW):
            row = await fetch_one(conn, f"select count(*)::bigint as rows from {name}")  # noqa: S608 — имя из DB_ALLOW
            exact[name] = int(row["rows"]) if row else 0
    last_map = {r["table_name"]: r["last_change_at"] for r in last}
    return [
        {
            "table": name,
            "rows": exact[name],
            "last_change_at": last_map[name].isoformat() if name in last_map and last_map[name] else None,
        }
        for name in sorted(DB_ALLOW)
    ]


@router.get("/api/engine/db/tables/{name}/rows", summary="Последние записи таблицы (только чтение, allow-list таблиц)")
async def get_engine_db_tables_name_rows(request: Request, name: str, limit: int = Query(default=50, ge=1, le=500)) -> Any:
    if name not in DB_ALLOW:
        raise HTTPException(status_code=403, detail="таблица вне allow-list")
    async with db() as conn:
        rows = await fetch_all(conn, f"select * from {name} order by id desc limit %s", (limit,))  # noqa: S608
    return [_mask_row(r) for r in rows]


@router.get("/api/engine/db/activity", summary="Лента INSERT/UPDATE/DELETE из db_activity_log")
async def get_engine_db_activity(
    request: Request,
    limit: int = Query(default=50, ge=1, le=500),
    cursor: str | None = None,
) -> Any:
    where = "true"
    args: list[Any] = []
    if cursor:
        where = "id < %s"
        try:
            args.append(int(cursor))
        except ValueError as exc:
            raise HTTPException(status_code=422, detail="cursor: id") from exc
    args.append(limit)
    async with db() as conn:
        rows = await fetch_all(
            conn,
            f"select id, table_name, op, pk, summary, ts from db_activity_log where {where} order by id desc limit %s",
            args,
        )
    return [
        {
            "id": r["id"],
            "table_name": r["table_name"],
            "op": r["op"],
            "pk": r["pk"],
            "summary": r["summary"],
            "ts": r["ts"].isoformat() if r["ts"] else None,
        }
        for r in rows
    ]
