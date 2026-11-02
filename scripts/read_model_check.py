"""T-235: приёмка записанных search/trace через GET, без запуска нового агента."""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any
from urllib.parse import quote

import httpx
import psycopg
from app.contracts.registry import validate
from app.search.grammar import PREFIXES
from app.trace.privacy import mask
from app.trace.relations import TYPES
from psycopg import sql


@dataclass(frozen=True)
class SearchCase:
    code: str
    query: str = field(repr=False)
    kind: str
    ref: str


# SQL фиксирован; значения запроса не используются как SQL identifiers.
FORMATS = {
    "UUID": (
        "select correlation_id::text,public_id from ledger_entries where correlation_id is not null order by id limit 1",
        "ledger",
    ),
    "tracking_token": (
        "select tracking_token,public_id from signals where tracking_token is not null order by id limit 1",
        "signal",
    ),
    "nickname": (
        "select h.value #>> '{}',c.public_id from clients c cross join lateral jsonb_path_query(c.social_handles,'$.** ? (@.type() == \"string\")') h(value) where left(h.value #>> '{}',1)='@' order by c.id,h.value::text limit 1",
        "client",
    ),
    "masked_card": (
        "select '**** '||p.card_last4,c.public_id from client_products p join clients c on c.id=p.client_id where p.card_last4 is not null order by c.id,p.id limit 1",
        "client",
    ),
    "masked_phone": (
        "select contacts->>'phone_masked',public_id from clients where contacts->>'phone_masked' like '+%' order by id limit 1",
        "client",
    ),
    "number": ("select id::text,public_id from signals order by id limit 1", "signal"),
    "text": (
        "select left(text,200),public_id from signals where length(text)>3 order by id limit 1",
        "signal",
    ),
    "rule": ("select code,code from business_rules order by code limit 1", "rule"),
    "error_code": (
        "select code,code from error_codes order by code limit 1",
        "error_code",
    ),
}


async def recorded_cases(conn: Any, scenario: dict[str, Any]) -> tuple[list[SearchCase], list[str]]:
    """Отсутствующие доказательства — ошибки, а не фиктивные совпадения/пропуски."""
    cases, missing = [], []
    queries = scenario.get("queries") or {}
    if set(queries.get("prefixes") or []) != set(PREFIXES):
        missing.append("manifest:prefixes")
    if set(queries.get("formats") or []) != set(FORMATS):
        missing.append("manifest:formats")
    for prefix, kind in PREFIXES.items():
        spec = TYPES[kind]
        row = await (
            await conn.execute(
                sql.SQL("select {}::text from {} order by {} limit 1").format(
                    sql.Identifier(spec.public),
                    sql.Identifier(spec.table),
                    sql.Identifier(spec.key),
                )
            )
        ).fetchone()
        if row is None:
            missing.append(f"prefix:{prefix}")
            continue
        ref = str(row[0])
        if kind == "branch" and not ref.startswith("VSP-"):
            ref = "VSP-" + ref
        cases.append(SearchCase(f"prefix:{prefix}", ref, kind, ref))
    for name, (statement, kind) in FORMATS.items():
        row = await (await conn.execute(statement)).fetchone()
        if row is None or not row[0]:
            missing.append(f"format:{name}")
        else:
            cases.append(SearchCase(f"format:{name}", str(row[0]), kind, str(row[1])))
    return cases, missing


async def check_search(http: httpx.AsyncClient, case: SearchCase) -> bool:
    try:
        response = await http.get("/api/search", params={"q": case.query, "run_id": "all", "limit": 50})
    except httpx.HTTPError:
        # Exception URL может содержать capability token; журналируем только code.
        return False
    if response.status_code != 200:
        return False
    try:
        payload = response.json()
    except ValueError:
        return False
    if validate(payload, "trace/search_response"):
        return False
    if case.code == "format:tracking_token" and case.query in json.dumps(payload, ensure_ascii=False):
        return False
    for hit in payload["hits"]:
        for name in ("title_ru", "snippet_ru"):
            value = hit.get(name)
            if value and mask(value, len(value) + 1) != value:
                return False
    return any(hit["kind"] == case.kind and hit["ref"] == case.ref for hit in payload["hits"])


async def check_trace(
    http: httpx.AsyncClient, case: SearchCase, *, causal: bool = False, pending: bool = False, minimum_fanout: int = 0
) -> bool:
    try:
        response = await http.get(f"/api/trace/{case.kind}/{quote(case.ref, safe='')}", params={"run_id": "all"})
    except httpx.HTTPError:
        return False
    if response.status_code != 200:
        return False
    try:
        payload = response.json()
    except ValueError:
        return False
    valid = (
        not validate(payload, "trace/trace_response")
        and payload["subject"]["kind"] == case.kind
        and payload["subject"]["ref"] == case.ref
    )
    if not valid:
        return False
    if not safe_text(payload):
        return False
    if causal and (not payload["before"] or not payload["after"]):
        return False
    if pending and (not payload["pending"] or payload["terminal"]["reached"]):
        return False
    if minimum_fanout and not any(
        group["kind"] == "signal_created" and group["count"] >= minimum_fanout for group in payload["groups"]
    ):
        return False
    return True


def safe_text(value: Any) -> bool:
    """Проверяет тексты; UUID и числовые object refs не являются контактами."""
    if isinstance(value, list):
        return all(safe_text(item) for item in value)
    if isinstance(value, dict):
        for key, item in value.items():
            if key in ("title_ru", "brief_ru", "label_ru", "value_ru") and isinstance(item, str):
                if mask(item, len(item) + 1) != item:
                    return False
            if not safe_text(item):
                return False
    return True


async def recorded_contexts(conn: Any) -> tuple[list[tuple[SearchCase, str, int]], list[str]]:
    statements = {
        "causal_signal": (
            "signal",
            "select s.public_id,0 from signals s where exists(select 1 from agent_runs a where a.signal_id=s.id) order by s.id limit 1",
        ),
        "causal_incident": (
            "incident",
            "select public_id,0 from incidents where agent_run_id is not null order by id limit 1",
        ),
        "pending": (
            "incident",
            "select public_id,0 from incidents where status not in ('closed','rejected','duplicate') order by id limit 1",
        ),
        "fanout": (
            "incident",
            "select i.public_id,count(*) from incidents i join incident_signals s on s.incident_id=i.id and s.linked_sim>i.created_sim group by i.id having count(*)>=120 order by i.id limit 1",
        ),
    }
    contexts, missing = [], []
    for name, (kind, statement) in statements.items():
        row = await (await conn.execute(statement)).fetchone()
        if row is None:
            missing.append(f"context:{name}")
        else:
            contexts.append((SearchCase(f"context:{name}", row[0], kind, row[0]), name, int(row[1])))
    return contexts, missing


async def run_search_trace(base: str, dsn: str, scenario: dict[str, Any]) -> bool:
    async with await psycopg.AsyncConnection.connect(dsn) as conn:
        await conn.execute("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ, READ ONLY")
        await conn.execute("SET LOCAL statement_timeout='3000ms'")
        cases, missing = await recorded_cases(conn, scenario)
        contexts, missing_contexts = await recorded_contexts(conn)
    failed = [*missing, *missing_contexts]
    async with httpx.AsyncClient(base_url=base, timeout=10) as http:
        for case in cases:
            if not await check_search(http, case):
                failed.append(case.code)
            if case.code.startswith("prefix:") and not await check_trace(http, case):
                failed.append(f"trace:{case.code}")
        for case, name, count in contexts:
            if not await check_trace(
                http, case, causal=name.startswith("causal_"), pending=name == "pending", minimum_fanout=count
            ):
                failed.append(case.code)
    # В журнале только имена проверок: capability tokens и контакты не печатаются.
    mark = "FAIL" if failed else "OK"
    print(  # noqa: T201
        f"  [{scenario['number']:>2}] {mark} {scenario['title_ru']}: {len(cases)} поисковых проверок; ошибки: {', '.join(failed) or 'нет'}"
    )
    return not failed
