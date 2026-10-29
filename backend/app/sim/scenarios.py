"""Демо-сценарии (ТЗ §18): загрузка YAML из data/scenarios, инъекция сообщений в текущий запуск, проверка ожиданий.

Минимум для демо и автотестов L5 (T-038 в части запуска, T-142 в части проверок):
- `load_all()` — все сценарии (отсортированы по номеру);
- `inject(conn, scenario, run_id)` — создаёт сигналы из секции `inject` YAML (подбор клиента по сегменту/психотипу/округу/коду ошибки
  или неидентифицированный контакт) и возвращает их id; агент запускается вызывающей стороной (API — через AgentService, тесты — напрямую);
- `evaluate(conn, scenario, run_id)` — проверяет `expected` по данным запуска. Ключи, для которых проверка ещё не реализована
  (нужны пакеты B06–B08: генератор сбоев, проактив, комплаенс, лента), возвращаются с `ok: null` и причиной — тест их не считает провалом.

Сценарии с `file` (9–10, B07) запускаются через транскрипт: `inject_transcript` → `analyze_transcript` → `evaluate`.
"""

from __future__ import annotations

import datetime as dt
import uuid
from pathlib import Path
from typing import Any

import psycopg
import yaml

from app.abs import service as abs_svc
from app.ingest.normalizer import create_signal
from app.sim.events import dumps

SCENARIOS_DIR = Path(__file__).resolve().parents[3] / "data" / "scenarios"

_cache: list[dict[str, Any]] | None = None


def load_all(force: bool = False) -> list[dict[str, Any]]:
    global _cache
    if _cache is None or force:
        items: list[dict[str, Any]] = []
        for f in sorted(SCENARIOS_DIR.glob("*.yaml")):
            d = yaml.safe_load(f.read_text(encoding="utf-8")) or {}
            d["_file"] = f.name
            items.append(d)
        _cache = sorted(items, key=lambda s: int(s.get("number") or 0))
    return _cache


def get(scenario_id: str) -> dict[str, Any] | None:
    return next((s for s in load_all() if s.get("id") == scenario_id), None)


def is_runnable(s: dict[str, Any]) -> bool:
    return bool(s.get("inject") or s.get("file"))


def is_transcript(s: dict[str, Any]) -> bool:
    """Сценарии 9–10: вместо сообщений — файл транскрипта (B07)."""
    return bool(s.get("file")) and not s.get("inject")


def to_api(s: dict[str, Any], row: tuple[Any, ...] | None = None) -> dict[str, Any]:
    """Schema `Scenario` из OpenAPI: описание + признак готовности к запуску в тексте."""
    desc = s.get("description_ru") or s.get("title_ru") or ""
    if not is_runnable(s):
        desc = f"{desc} (запуск появится с пакетом {s.get('requires', 'B07')})".strip()
    return {
        "id": s["id"],
        "title_ru": s.get("title_ru") or s["id"],
        "title_en": s.get("title_en") or s["id"],
        "description_ru": desc,
        "duration_sim_hours": float((s.get("fault") or {}).get("duration_sim_h") or s.get("duration_sim_hours") or 0),
        "last_run_at": row[0].isoformat() if row and row[0] else None,
        "last_result": row[1] if row else None,
    }


# ---------------------------------------------------------------- подбор клиента


def _col(row: Any, i: int) -> Any:
    """Строка psycopg может быть кортежем или dict (row_factory=dict_row в API) — берём по позиции."""
    return list(row.values())[i] if isinstance(row, dict) else row[i]


async def pick_client(conn: psycopg.AsyncConnection[Any], spec: dict[str, Any], exclude: list[int]) -> int | None:
    """Детерминированный выбор клиента под описание: сегмент, психотип, город/округ, наличие операции с кодом ошибки."""
    # клиент, которого сценарии ещё не использовали (иначе накопленные обращения дают «повтор 3+» и HITL)
    where = ["c.is_active"]
    if not spec.get("_reuse"):
        # ещё не использован сценариями и без накопленной истории обращений (иначе сработает «повтор 3+» → HITL)
        where.append("not exists (select 1 from signals s where s.client_id = c.id and s.origin = 'scenario')")
    args: list[Any] = []
    if spec.get("segment"):
        where.append("c.segment_code = %s")
        args.append(spec["segment"])
    if spec.get("psychotype"):
        where.append("c.psychotype_code = %s")
        args.append(spec["psychotype"])
    if spec.get("city"):
        where.append("c.city_id in (select id from cities where name_ru = %s)")
        args.append(spec["city"])
    if spec.get("district"):
        where.append("c.region_code in (select code from regions where district_code = %s)")
        args.append(spec["district"])
    if spec.get("error_code"):
        where.append("exists (select 1 from operations o where o.client_id = c.id and o.error_code = %s)")
        args.append(spec["error_code"])
    if exclude:
        where.append("not (c.id = any(%s))")
        args.append(exclude)
    # предпочитаем клиентов с наименьшей историей обращений за 14 сим-дней
    recent = "(select count(*) from signals s where s.client_id = c.id and s.received_sim > (select sim_time from sim_state where id = 1) - interval '14 days')"
    sql = f"select c.id from clients c where {' and '.join(where)} order by {recent} asc, c.id limit 1"
    row = await (await conn.execute(sql, args)).fetchone()
    if row is None and not spec.get("_reuse"):
        # все подходящие уже заняты сценариями — разрешаем повторное использование
        return await pick_client(conn, {**spec, "_reuse": True}, exclude)
    if row is None and (spec.get("error_code") or spec.get("city") or spec.get("psychotype")):
        # мягкий откат: без кода ошибки/города/психотипа, но с сегментом и округом
        soft = {k: v for k, v in spec.items() if k in ("segment", "district", "_reuse")}
        return await pick_client(conn, soft, exclude) if soft != spec else None
    return int(_col(row, 0)) if row else None


# ---------------------------------------------------------------- инъекция


async def inject(
    conn: psycopg.AsyncConnection[Any],
    scenario: dict[str, Any],
    run_id: int,
    *,
    sim_time: dt.datetime | None = None,
) -> list[dict[str, Any]]:
    """Создаёт сигналы сценария (origin=scenario). Возвращает [{signal_id, client_id, text}]; агент запускается вызывающей стороной."""
    out: list[dict[str, Any]] = []
    used: list[int] = []
    for i, m in enumerate(scenario.get("inject") or []):
        cspec = dict(m.get("client") or {})
        client_id: int | None = None
        hints: dict[str, Any] | None = None
        if cspec.get("unidentified"):
            hints = {"nickname": cspec.get("nick") or f"@{scenario['id']}_{i}", "name": cspec.get("name")}
            hints = {k: v for k, v in hints.items() if v}
        else:
            client_id = await pick_client(conn, cspec, used)
            if client_id is None:
                raise LookupError(f"сценарий {scenario['id']}: нет клиента под {cspec}")
            used.append(client_id)
        if client_id is not None and cspec.get("operation"):
            await inject_operation(
                conn, run_id, client_id, dict(cspec["operation"]), sim_time or dt.datetime.now(dt.UTC)
            )
        msg = {
            "channel": m.get("channel") or "chat",
            "external_id": f"scenario-{scenario['id']}-{run_id}-{i}-{uuid.uuid4().hex[:6]}",
            "client": {"client_id": client_id, "contact_hints": hints},
            "text": str(m["text"]).strip(),
            "timestamp": dt.datetime.now(dt.UTC).isoformat(),
            "geo": {"source": "none"},
            "origin": "scenario",
            "meta": {"scenario_id": scenario["id"], "step": i},
        }
        res = await create_signal(conn, msg, source_code="api", run_id=run_id, sim_time=sim_time, emit_event=False)
        if res.get("status") != "accepted":
            raise RuntimeError(f"сценарий {scenario['id']}: сигнал не принят: {res}")
        out.append({"signal_id": int(res["signal_id"]), "client_id": client_id, "text": msg["text"]})
    return out


async def inject_transcript(
    conn: psycopg.AsyncConnection[Any],
    scenario: dict[str, Any],
    run_id: int,
    *,
    sim_time: dt.datetime | None = None,
) -> dict[str, Any]:
    """Сценарии с `file`: кладёт транскрипт из data/import/transcripts (source=scenario); анализ запускает вызывающая сторона."""
    from app.compliance.transcripts import create_transcript, load_file

    path = SCENARIOS_DIR.parent / "import" / "transcripts" / str(scenario["file"])
    if not path.exists():
        raise LookupError(f"сценарий {scenario['id']}: файл {path.name} не найден")
    doc, fmt = load_file(path)
    if scenario.get("branch"):
        doc["branch_code"] = str(scenario["branch"])
    if scenario.get("desk"):
        doc["desk_no"] = int(scenario["desk"])
    if scenario.get("deal"):
        doc["deal_product"] = str(scenario["deal"])
    doc.pop("employee_public_id", None)  # имя из YAML — не public_id; сотрудника выбираем по столу
    client_id = await pick_client(conn, dict(scenario.get("client") or {}), []) if scenario.get("client") else None
    if client_id:
        doc["client"] = {"client_id": client_id}
    doc["external_id"] = f"scenario-{scenario['id']}-{run_id}-{uuid.uuid4().hex[:6]}"
    tr = await create_transcript(
        conn,
        doc,
        run_id=run_id,
        sim_time=sim_time or dt.datetime.now(dt.UTC),
        source="scenario",
        fmt=fmt,
        filename=path.name,
    )
    return {"transcript_id": int(tr["id"]), "client_id": client_id}


async def inject_operation(
    conn: psycopg.AsyncConnection[Any], run_id: int, client_id: int, op: dict[str, Any], sim_time: dt.datetime
) -> int:
    """Свежая неуспешная операция клиента «20 сим-минут назад» — чтобы контекст агента и бизнес-правила видели факт сбоя."""
    started = sim_time - dt.timedelta(minutes=int(op.get("minutes_ago") or 20))
    row = await (
        await conn.execute(
            "insert into operations (run_id, client_id, product_code, op_type, system_path, amount_rub, method, merchant, fee_amount, status, error_code, started_sim, finished_sim) "
            "values (%s, %s, %s, %s, %s, %s, %s, %s, %s, 'failed', %s, %s, %s) returning id",
            (
                run_id,
                client_id,
                op.get("product_code") or "debit_card",
                op.get("op_type") or "card_payment",
                list(op.get("system_path") or ["mobile_app", "processing", "core_abs"]),
                op.get("amount_rub"),
                op.get("method") or "online",
                op.get("merchant"),
                op.get("fee_amount") or 0,
                op["error_code"],
                started,
                started + dt.timedelta(seconds=3),
            ),
        )
    ).fetchone()
    op_id = int(_col(row, 0))
    await abs_svc.ensure_operation_posted(conn, op_id)
    return op_id


# ---------------------------------------------------------------- проверка ожиданий

NOT_YET = {
    "move_to_private": "B08 (перевод в личные сообщения)",
    "proactive_notice": "B06 (проактивные уведомления по сбою)",
    "preventive_notice": "B06",
    "sla_met": "B05 (SLA-тики по сим-времени)",
    "wake_on_reply": "B05 (пробуждение по ответу клиента)",
    "escalate_on_silence": "B05",
    "escalation_on_silence": "B05",
    "map_zone": "B14 (карта)",
    "fast_path_p50_s": "замер латентности — только на live",
    "proactive_on_activity_drop": "B06 (модель поведения)",
    "regression_incident": "B06 (регрессия сбоя)",
    "retained": "B06 (модель поведения)",
    "complaints": "B06 (генератор массового сбоя)",
}


async def _run_data(conn: psycopg.AsyncConnection[Any], run_id: int) -> dict[str, Any]:
    sigs = await (
        await conn.execute(
            "select id, client_id, status, classification, decision, sentiment from signals where run_id = %s and origin = 'scenario' order by id",
            (run_id,),
        )
    ).fetchall()
    incs = await (
        await conn.execute(
            "select id, status, team_code, co_team_codes, priority, flags, mass_impact, incident_type from incidents where run_id = %s order by id",
            (run_id,),
        )
    ).fetchall()
    runs = await (
        await conn.execute(
            "select ar.id, ar.outcome, ar.needed_human, (select count(*) from agent_steps s where s.run_id = ar.id) from agent_runs ar where ar.sim_run_id = %s order by ar.id",
            (run_id,),
        )
    ).fetchall()
    fups = await (
        await conn.execute("select reason, status, wake_sim from followups where sim_run_id = %s", (run_id,))
    ).fetchall()
    gifts = await (
        await conn.execute(
            "select payload->'gift'->>'gift_code' from tasks where run_id = %s and kind = 'gift'", (run_id,)
        )
    ).fetchall()
    rules_rows = await (
        await conn.execute(
            "select s.output->'matched' from agent_steps s join agent_runs ar on ar.id = s.run_id where ar.sim_run_id = %s and s.node = 'check_rules'",
            (run_id,),
        )
    ).fetchall()
    rules = {m.get("rule_code") for r in rules_rows for m in (_col(r, 0) or []) if isinstance(m, dict)}
    refunds = await (
        await conn.execute(
            "select l.id, l.amount, l.created_by, l.rule_id, a.client_id from ledger_entries l join accounts a on a.id = l.account_id "
            "where l.kind = 'refund' and (l.run_id = %s or l.operation_id in (select source_operation_id from signals where run_id = %s and origin = 'scenario'))",
            (run_id, run_id),
        )
    ).fetchall()
    replies = await (
        await conn.execute(
            "select r.id, r.author, r.latency_ms, p.status, p.author_client_id from external_replies r join external_posts p on p.id = r.post_id "
            "join signals s on s.id = p.signal_id where s.run_id = %s and s.origin = 'scenario'",
            (run_id,),
        )
    ).fetchall()
    accounts = await (
        await conn.execute(
            "select a.client_id, a.balance, (select count(*) from ledger_entries l where l.account_id = a.id) from accounts a "
            "where a.client_id in (select client_id from signals where run_id = %s and origin = 'scenario' and client_id is not null)",
            (run_id,),
        )
    ).fetchall()
    return {
        "refunds": [
            {
                "id": _col(r, 0),
                "amount": float(_col(r, 1)),
                "by": _col(r, 2),
                "rule": _col(r, 3),
                "client_id": _col(r, 4),
            }
            for r in refunds
        ],
        "replies": [
            {
                "id": _col(r, 0),
                "author": _col(r, 1),
                "latency_ms": _col(r, 2),
                "post_status": _col(r, 3),
                "identified": _col(r, 4) is not None,
            }
            for r in replies
        ],
        "accounts": [{"client_id": _col(r, 0), "balance": float(_col(r, 1)), "entries": _col(r, 2)} for r in accounts],
        "rules": sorted(r for r in rules if r),
        "signals": [
            {
                "id": _col(r, 0),
                "client_id": _col(r, 1),
                "status": _col(r, 2),
                "classification": _col(r, 3) or {},
                "decision": _col(r, 4) or {},
                "sentiment": _col(r, 5),
            }
            for r in sigs
        ],
        "incidents": [
            {
                "id": _col(r, 0),
                "status": _col(r, 1),
                "team": _col(r, 2),
                "co_teams": list(_col(r, 3) or []),
                "priority": _col(r, 4),
                "flags": list(_col(r, 5) or []),
                "mass_impact": _col(r, 6),
                "type": _col(r, 7),
            }
            for r in incs
        ],
        "agent_runs": [
            {"id": _col(r, 0), "outcome": _col(r, 1), "needed_human": _col(r, 2), "steps": int(_col(r, 3))}
            for r in runs
        ],
        "followups": [{"reason": _col(r, 0), "status": _col(r, 1), "wake_sim": _col(r, 2)} for r in fups],
        "gifts": [_col(r, 0) for r in gifts],
    }


def _all_flags(d: dict[str, Any]) -> set[str]:
    flags: set[str] = set()
    for s in d["signals"]:
        flags |= set(s["classification"].get("flags") or [])
        flags |= set(s["decision"].get("flags") or [])
    for i in d["incidents"]:
        flags |= set(i["flags"])
    return flags


def _check(code: str, ok: bool | None, detail: str) -> dict[str, Any]:
    return {"code": code, "ok": ok, "detail": detail}


async def evaluate(conn: psycopg.AsyncConnection[Any], scenario: dict[str, Any], run_id: int) -> dict[str, Any]:
    """Сверяет `expected` сценария с данными запуска. ok=None — проверка ещё не реализована (см. NOT_YET)."""
    d = await _run_data(conn, run_id)
    exp = dict(scenario.get("expected") or {})
    checks: list[dict[str, Any]] = []
    flags = _all_flags(d)
    teams = {i["team"] for i in d["incidents"]} | {t for i in d["incidents"] for t in i["co_teams"]}
    decisions = [s["decision"] for s in d["signals"] if s["decision"]]
    sig_types = {s["classification"].get("signal_type") for s in d["signals"]}

    tr = await _transcript_data(conn, run_id) if any(k in TRANSCRIPT_KEYS for k in exp) else None

    for key, want in exp.items():
        if key in NOT_YET:
            checks.append(_check(key, None, f"не проверяется: {NOT_YET[key]}"))
            continue
        if key in TRANSCRIPT_KEYS:
            checks.append(_check_transcript(key, want, tr or {}))
            continue
        if key == "flags":
            missing = [f for f in want if f not in flags]
            checks.append(
                _check(key, not missing, f"есть {sorted(flags)}; нет {missing}" if missing else f"все: {want}")
            )
        elif key == "flag":
            checks.append(_check(key, want in flags, f"флаги {sorted(flags)}"))
        elif key == "priority":
            prios = [i["priority"] for i in d["incidents"]]
            checks.append(_check(key, want in prios, f"приоритеты инцидентов {prios}"))
        elif key == "incident_team":
            checks.append(_check(key, want in teams, f"команды {sorted(t for t in teams if t)}"))
        elif key == "incident_teams":
            missing = [t for t in want if t not in teams]
            checks.append(_check(key, not missing, f"команды {sorted(t for t in teams if t)}; нет {missing}"))
        elif key == "gift":
            kinds = set(d["gifts"]) | {(dd.get("gift") or {}).get("gift_code") for dd in decisions}
            checks.append(_check(key, want in kinds, f"подарки {sorted(k for k in kinds if k)}"))
        elif key == "under_the_hood":
            ok = any(r["steps"] >= 8 for r in d["agent_runs"])
            checks.append(
                _check(key, ok, f"прогонов {len(d['agent_runs'])}, шагов {[r['steps'] for r in d['agent_runs']]}")
            )
        elif key == "clarification":
            asked = [
                dd
                for dd in decisions
                if dd.get("router_action") == "request_clarification" or dd.get("clarification_question_ru")
            ]
            statuses = [s["status"] for s in d["signals"]]
            checks.append(
                _check(key, bool(asked) == bool(want), f"уточнений {len(asked)}; статусы сигналов {statuses}")
            )
        elif key in ("sleeps", "sleep_hours"):
            deferred = [s for s in d["signals"] if s["status"] in ("deferred", "awaiting_client")] or [
                f for f in d["followups"] if f["reason"] in ("awaiting_client", "clarification")
            ]
            checks.append(
                _check(
                    key,
                    bool(deferred),
                    f"отложенных {len(deferred)}; followups {[f['reason'] for f in d['followups']]}",
                )
            )
        elif key == "dedupe_to_one_incident":
            n = len([i for i in d["incidents"] if i["type"] == "fault" or i["mass_impact"]]) or len(d["incidents"])
            checks.append(
                _check(
                    key,
                    len(d["incidents"]) == 1,
                    f"инцидентов {len(d['incidents'])} (массовых {n}), сигналов {len(d['signals'])}",
                )
            )
        elif key == "refund":
            ok = bool(d["refunds"]) == bool(want)
            by = sorted({r["by"] for r in d["refunds"]})
            total = sum(r["amount"] for r in d["refunds"])
            checks.append(_check(key, ok, f"возвратов {len(d['refunds'])} на {total:.2f} ₽ ({', '.join(by) or '—'})"))
        elif key == "public_reply":
            agent_replies = [r for r in d["replies"] if r["author"] == "agent"]
            ok = bool(agent_replies) == bool(want)
            lat = [r["latency_ms"] for r in agent_replies if r["latency_ms"] is not None]
            checks.append(
                _check(
                    key,
                    ok,
                    f"публичных ответов агента {len(agent_replies)}; статусы постов {sorted({r['post_status'] for r in d['replies']})}; латентность мс {lat[:3]}",
                )
            )
        elif key == "abs_widget":
            ok = bool(d["accounts"]) and any(a["entries"] > 0 for a in d["accounts"])
            checks.append(
                _check(
                    key,
                    ok == bool(want),
                    f"счетов {len(d['accounts'])}, проводок {[a['entries'] for a in d['accounts']]}",
                )
            )
        elif key == "sentiment":
            sents = {s["sentiment"] or s["classification"].get("sentiment") for s in d["signals"]}
            checks.append(_check(key, want in sents, f"тональности {sorted(s for s in sents if s)}"))
        elif key == "hidden_negativity":
            ok = bool({"sarcasm", "hidden_negativity", "passive_aggression"} & flags) or any(
                s["classification"].get("hidden_negativity") for s in d["signals"]
            )
            checks.append(_check(key, ok, f"флаги {sorted(flags)}"))
        elif key == "escalation_role":
            roles = {(dd.get("escalation") or {}).get("to_role") for dd in decisions}
            checks.append(_check(key, want in roles, f"роли эскалации {sorted(r for r in roles if r)}"))
        elif key == "rule":
            rules = {str(r) for r in d["rules"]} | {
                str((dd.get("route") or {}).get("rule_id"))
                for dd in decisions
                if (dd.get("route") or {}).get("rule_id")
            }
            ok = str(want) in rules or "rule_confirmed" in flags
            checks.append(_check(key, ok, f"правила {sorted(rules)}; флаги {sorted(flags)}"))
        elif key == "signal_type":
            checks.append(_check(key, want in sig_types, f"типы {sorted(t for t in sig_types if t)}"))
        else:
            checks.append(_check(key, None, "нет проверки для этого ключа"))

    passed = all(c["ok"] is not False for c in checks) and (
        bool(d["signals"]) or bool(tr and tr.get("status") == "done")
    )
    return {
        "passed": passed,
        "checks": checks,
        "counts": {
            "signals": len(d["signals"]),
            "incidents": len(d["incidents"]),
            "agent_runs": len(d["agent_runs"]),
            "completed": sum(1 for r in d["agent_runs"] if r["outcome"] == "completed"),
            "errors": sum(1 for r in d["agent_runs"] if r["outcome"] == "error"),
        },
    }


TRANSCRIPT_KEYS = {"patterns", "alert_to_manager", "counter_threshold", "findings", "script_steps_missed"}


async def _transcript_data(conn: psycopg.AsyncConnection[Any], run_id: int) -> dict[str, Any]:
    """Последний транскрипт сценария в запуске: статус, отчёт, подтверждённые триггеры, алерты, порог."""
    row = await (
        await conn.execute(
            "select t.id, t.status, t.report, t.error, s.id, s.trigger_count, s.alert_threshold from transcripts t left join audio_sessions s on s.id = t.audio_session_id "
            "where t.run_id = %s and t.source = 'scenario' order by t.id desc limit 1",
            (run_id,),
        )
    ).fetchone()
    if not row:
        return {}
    trig = await (
        await conn.execute(
            "select pattern_code, status, confidence, quote, fact_check from compliance_triggers where session_id = %s order by id",
            (_col(row, 4),),
        )
    ).fetchall()
    alerts = await (
        await conn.execute(
            "select kind, decision, incident_id from compliance_alerts where session_id = %s order by id",
            (_col(row, 4),),
        )
    ).fetchall()
    return {
        "transcript_id": _col(row, 0),
        "status": _col(row, 1),
        "report": _col(row, 2) or {},
        "error": _col(row, 3),
        "trigger_count": _col(row, 5),
        "alert_threshold": _col(row, 6),
        "confirmed": [_col(t, 0) for t in trig if _col(t, 1) == "confirmed"],
        "triggers": [
            {"code": _col(t, 0), "status": _col(t, 1), "quote": _col(t, 3), "fact_check": _col(t, 4)} for t in trig
        ],
        "alerts": [{"kind": _col(a, 0), "decision": _col(a, 1), "incident_id": _col(a, 2)} for a in alerts],
    }


def _squash(s: str) -> str:
    return "".join(str(s).lower().split())


def _check_transcript(key: str, want: Any, tr: dict[str, Any]) -> dict[str, Any]:
    if not tr:
        return _check(key, False, "транскрипт сценария не найден в запуске")
    if tr.get("status") != "done":
        return _check(key, False, f"анализ не завершён: {tr.get('status')} {tr.get('error') or ''}".strip())
    findings = list((tr.get("report") or {}).get("findings") or [])
    codes = set(tr["confirmed"]) | {f["pattern_code"] for f in findings}
    kinds = {a["kind"] for a in tr["alerts"]}
    if key == "patterns":
        missing = [p for p in want if p not in codes]
        return _check(key, not missing, f"подтверждены {sorted(codes)}" + (f"; нет {missing}" if missing else ""))
    if key == "alert_to_manager":
        return _check(
            key,
            bool(tr["alerts"]) == bool(want),
            f"алерты {sorted(kinds)}; инцидент {[a['incident_id'] for a in tr['alerts']][:1]}",
        )
    if key == "counter_threshold":
        ok = tr.get("alert_threshold") == want and "threshold" in kinds and (tr.get("trigger_count") or 0) >= want
        return _check(
            key,
            ok,
            f"порог {tr.get('alert_threshold')}, срабатываний {tr.get('trigger_count')}, алерты {sorted(kinds)}",
        )
    if key == "script_steps_missed":
        steps = {
            s["code"]: s["status"] for s in ((tr.get("report") or {}).get("script_compliance") or {}).get("steps") or []
        }
        bad = [c for c in want if steps.get(c) != "missed"]
        return _check(key, not bad, f"этапы {steps}" + (f"; ожидались пропущенными {bad}" if bad else ""))
    if key == "findings":
        problems: list[str] = []
        for item in want:
            code = item.get("code")
            fs = [f for f in findings if f["pattern_code"] == code]
            if not fs:
                problems.append(f"нет находки {code}")
                continue
            if item.get("alert") and item["alert"] not in kinds:
                problems.append(f"{code}: нет алерта {item['alert']}")
            blob = _squash(" ".join(f"{f.get('quote', '')} {dumps(f.get('fact_check') or {})}" for f in fs))
            if item.get("quote") and _squash(item["quote"]) not in blob:
                problems.append(f"{code}: нет цитаты «{item['quote']}»")
            if (
                item.get("truth")
                and _squash(item["truth"]) not in blob
                and _squash(item["truth"]).replace(",", ".") not in blob
            ):
                problems.append(f"{code}: нет правды «{item['truth']}»")
        return _check(
            key, not problems, "; ".join(problems) if problems else f"находки {sorted(codes)}, алерты {sorted(kinds)}"
        )
    return _check(key, None, "неизвестный ключ")


async def save_result(conn: psycopg.AsyncConnection[Any], scenario_id: str, result: dict[str, Any]) -> None:
    await conn.execute(
        "update scenarios set last_run_at = now(), last_result = %s::jsonb where id = %s",
        (dumps({"passed": result["passed"], "checks": result["checks"]}), scenario_id),
    )
