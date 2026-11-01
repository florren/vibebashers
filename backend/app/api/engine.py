"""Роутер тега `engine` (OpenAPI 1.4.0). Реализовано (B04): /api/agent/runs, /api/agent/runs/{id}, /api/agent/graph. Остальное — T-106."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException, Query, Request

from app.agent.graph import GRAPH_SPEC
from app.api.common import db, fetch_all, fetch_one, page, resolve_run_id
from app.contracts.registry import deref
from app.llm.base import LLMProfile
from app.llm.mock import MockProvider
from app.search.cases import entity_filter
from app.trace.privacy import mask
from app.trace.store import read_db

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
    q: str | None = Query(None, max_length=200),
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
        predicate, values = await entity_filter(conn, q, "agent")
        where.append(predicate)
        args.extend(values)
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


_COMPARE_FIELDS = ("signal_type", "sentiment", "product", "criticality", "negativity")


def classification_diff(llm: dict[str, Any], mock: dict[str, Any]) -> list[dict[str, Any]]:
    diff = []
    for field in _COMPARE_FIELDS:
        if llm.get(field) != mock.get(field):
            diff.append({"field": field, "llm": llm.get(field), "mock": mock.get(field)})
    return diff


@router.post(
    "/api/agent/compare", summary="Панель «ИИ против правил» — один текст через LLM-профиль и mock параллельно"
)
async def post_agent_compare(request: Request) -> Any:
    body = await request.json()
    text = str(body.get("text") or "").strip()
    if len(text) < 3:
        raise HTTPException(status_code=422, detail="text слишком короткий")
    schema = deref("agent/classification")
    profile = LLMProfile(code="compare", provider="mock", model="mock-rules-v1")
    mock_obj, _, _ = await MockProvider().complete_structured(
        [{"role": "user", "content": text}], schema, profile, timeout_s=5
    )
    chain = getattr(request.app.state, "llm_chain", None)
    llm_profile = getattr(request.app.state, "llm_profile", None) or profile
    llm_obj = dict(mock_obj)
    llm_run_id = None
    if chain is not None:
        try:
            result = await chain.complete_structured(
                [{"role": "user", "content": text}], schema, llm_profile, context="default"
            )
            llm_obj = dict(result.obj or {})
        except Exception as exc:  # noqa: BLE001 — панель показывает mock, если живая модель недоступна
            llm_obj = {**mock_obj, "error": str(exc)[:200]}
    return {
        "llm": llm_obj,
        "mock": mock_obj,
        "diff": classification_diff(llm_obj, mock_obj),
        "llm_run_id": llm_run_id,
        "mock_run_id": None,
    }


@router.get("/api/engine/entity-graph", summary="Граф сущностей клиент–сигнал–инцидент–система–команда (React Flow)")
async def get_engine_entity_graph(
    request: Request,
    incident_id: int | None = None,
    client_id: int | None = None,
    depth: int = Query(default=2, ge=1, le=4),
) -> Any:
    nodes: list[dict[str, Any]] = []
    edges: list[dict[str, Any]] = []
    if incident_id is None and client_id is None:
        return {"nodes": nodes, "edges": edges}
    async with db() as conn:
        if incident_id is not None:
            inc = await fetch_one(
                conn,
                "select id, public_id, title, team_code, system_code, primary_client_id from incidents where id = %s",
                (incident_id,),
            )
            if inc:
                nodes.append(
                    {
                        "id": f"incident:{inc['id']}",
                        "type": "incident",
                        "label": inc["public_id"],
                        "data": {"title": inc["title"]},
                    }
                )
                if inc["team_code"]:
                    nodes.append(
                        {"id": f"team:{inc['team_code']}", "type": "team", "label": inc["team_code"], "data": {}}
                    )
                    edges.append(
                        {
                            "id": f"e-team-{inc['id']}",
                            "source": f"incident:{inc['id']}",
                            "target": f"team:{inc['team_code']}",
                            "label": "team",
                        }
                    )
                if inc["system_code"]:
                    nodes.append(
                        {
                            "id": f"system:{inc['system_code']}",
                            "type": "system",
                            "label": inc["system_code"],
                            "data": {},
                        }
                    )
                    edges.append(
                        {
                            "id": f"e-sys-{inc['id']}",
                            "source": f"incident:{inc['id']}",
                            "target": f"system:{inc['system_code']}",
                            "label": "system",
                        }
                    )
                client_id = client_id or inc["primary_client_id"]
                if depth >= 2:
                    sigs = await fetch_all(
                        conn,
                        "select s.id, s.public_id from incident_signals isg join signals s on s.id = isg.signal_id where isg.incident_id = %s limit 20",
                        (incident_id,),
                    )
                    for s in sigs:
                        nodes.append({"id": f"signal:{s['id']}", "type": "signal", "label": s["public_id"], "data": {}})
                        edges.append(
                            {
                                "id": f"e-sig-{s['id']}",
                                "source": f"signal:{s['id']}",
                                "target": f"incident:{inc['id']}",
                                "label": "signal",
                            }
                        )
        if client_id is not None:
            client = await fetch_one(
                conn, "select id, public_id, display_name from clients where id = %s", (client_id,)
            )
            if client:
                nodes.append(
                    {
                        "id": f"client:{client['id']}",
                        "type": "client",
                        "label": client["public_id"],
                        "data": {"name": client["display_name"]},
                    }
                )
                if incident_id is not None:
                    edges.append(
                        {
                            "id": f"e-cli-{incident_id}",
                            "source": f"client:{client['id']}",
                            "target": f"incident:{incident_id}",
                            "label": "client",
                        }
                    )
    return {"nodes": nodes, "edges": edges}


# T-108: имена/SQL выражения выбираются исключительно из этого закрытого каталога.
DB_ALLOW = frozenset(
    {
        "signals",
        "incidents",
        "incident_signals",
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
_SENSITIVE = frozenset(
    {
        "phone",
        "email",
        "contacts",
        "contact",
        "contacts_hint",
        "authorization",
        "password",
        "secret",
        "token",
        "tracking_token",
        "api_key",
        "encrypted_key",
        "prompt",
        "response_raw",
        "reasoning",
        "input",
        "output",
        "tool_calls",
    }
)


def _mask_value(value: Any, key: str = "") -> Any:
    name = key.lower()
    if name in _SENSITIVE or any(part in name for part in ("password", "secret", "token", "api_key", "phone", "email")):
        return None
    if isinstance(value, dict):
        return {k: _mask_value(v, k) for k, v in value.items()}
    if isinstance(value, list):
        return [_mask_value(v) for v in value]
    if isinstance(value, str):
        return mask(value, limit=10000)
    return value


def _mask_row(row: dict[str, Any]) -> dict[str, Any]:
    return {key: _mask_value(value, key) for key, value in row.items()}


def _table_source(name: str) -> tuple[str, str, str]:
    if name in ("incident_status_history", "incident_signals"):
        return (
            f"{name} t join incidents parent on parent.id=t.incident_id",
            "parent.run_id",
            "t.incident_id desc,t.signal_id" if name == "incident_signals" else "t.id",
        )
    if name == "agent_steps":
        return "agent_steps t join agent_runs parent on parent.id=t.run_id", "parent.sim_run_id", "t.id"
    return (
        f"{name} t",
        "t.sim_run_id" if name == "agent_runs" else "t.run_id",
        "t.incident_id" if name == "incident_economics" else "t.id",
    )


async def _db_scope(conn: Any, run_id: str) -> list[int] | None:
    if run_id not in ("current", "all") and (
        not run_id.isascii() or not run_id.isdigit() or len(run_id) > 18 or int(run_id) <= 0
    ):
        raise HTTPException(422, "run_id: current | all | positive integer")
    rid = await resolve_run_id(conn, run_id)
    if run_id == "all":
        return None
    if rid is not None and not await fetch_one(conn, "select id from sim_runs where id=%s", (rid,)):
        raise HTTPException(404, "запуск не найден")
    baseline = await fetch_all(conn, "select id from sim_runs where kind='baseline'")
    return [int(row["id"]) for row in baseline] + ([rid] if rid is not None else [])


@router.get("/api/engine/db/tables", summary="Счётчики строк по таблицам (реальное время)")
async def get_engine_db_tables(run_id: str = "current") -> Any:
    async with read_db() as conn:
        scope = await _db_scope(conn, run_id)
        stats = await fetch_all(
            conn,
            "select relname,n_live_tup from pg_stat_user_tables where schemaname='public' and relname=any(%s)",
            (list(DB_ALLOW),),
        )
        estimates = {row["relname"]: int(row["n_live_tup"]) for row in stats}
        changes = await fetch_all(
            conn,
            "select table_name,max(ts) as ts from db_activity_log where table_name=any(%s) and (%s::bigint[] is null or run_id=any(%s)) group by table_name",
            (list(DB_ALLOW), scope, scope),
        )
        last = {row["table_name"]: row["ts"] for row in changes}
        result = []
        for name in sorted(DB_ALLOW):
            exact = scope is not None or estimates.get(name, 0) < 10000
            count = estimates.get(name, 0)
            if exact:
                source, column, _ = _table_source(name)
                row = await fetch_one(
                    conn,
                    f"select count(*) as n from {source} where (%s::bigint[] is null or {column}=any(%s))",
                    (scope, scope),
                )  # noqa: S608
                count = row["n"] if row else 0
            result.append({"table": name, "rows": count, "exact": exact, "last_change_at": last.get(name)})
    return result


@router.get("/api/engine/db/tables/{name}/rows", summary="Последние записи таблицы (только чтение, allow-list таблиц)")
async def get_engine_db_tables_name_rows(
    name: str, limit: int = Query(default=50, ge=1, le=500), run_id: str = "current"
) -> Any:
    if name not in DB_ALLOW:
        raise HTTPException(403, "таблица вне allow-list")
    source, column, order = _table_source(name)
    async with read_db() as conn:
        scope = await _db_scope(conn, run_id)
        rows = await fetch_all(
            conn,
            f"select t.* from {source} where (%s::bigint[] is null or {column}=any(%s)) order by {order} desc limit %s",
            (scope, scope, limit),
        )  # noqa: S608
    return [_mask_row(row) for row in rows]


@router.get("/api/engine/db/activity", summary="Лента INSERT/UPDATE/DELETE из db_activity_log")
async def get_engine_db_activity(
    limit: int = Query(default=50, ge=1, le=500),
    cursor: str | None = None,
    run_id: str = "current",
    table: str | None = None,
) -> Any:
    if table is not None and table not in DB_ALLOW:
        raise HTTPException(403, "таблица вне allow-list")
    if cursor is not None and (not cursor.isascii() or not cursor.isdigit() or len(cursor) > 18):
        raise HTTPException(422, "cursor: positive id")
    async with read_db() as conn:
        scope = await _db_scope(conn, run_id)
        rows = await fetch_all(
            conn,
            "select id,run_id,table_name,op,pk,summary,ts from db_activity_log where table_name=any(%s) and (%s::bigint[] is null or run_id=any(%s)) and (%s::bigint is null or id < %s) order by id desc limit %s",
            (
                [table] if table else list(DB_ALLOW),
                scope,
                scope,
                int(cursor) if cursor else None,
                int(cursor) if cursor else None,
                limit,
            ),
        )
    # Legacy summary может содержать произвольные значения: выдаём только имена полей.
    for row in rows:
        raw = row["summary"] or {}
        fields = raw.get("changed_fields")
        row["summary"] = {"changed_fields": [str(key) for key in fields] if isinstance(fields, list) else sorted(raw)}
    return rows
