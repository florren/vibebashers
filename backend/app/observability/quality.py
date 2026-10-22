"""Отчёт о качестве: что сломалось (ошибки, 5xx, failed), что работает не так (HITL-правки, ложные алерты,
fallback на правила, проваленные сценарии), где доработать (рекомендации). Источники — только БД и
наблюдаемость процесса; формат — JSON и Markdown (docs/REPORTS.md)."""

from __future__ import annotations

import time
from datetime import UTC, datetime
from typing import Any

import psycopg

from app.observability import http as http_obs

REPORT_VERSION = "quality-v1"


async def _rows(conn: psycopg.AsyncConnection[Any], sql: str, params: tuple[Any, ...] = ()) -> list[dict[str, Any]]:
    cur = await conn.execute(sql, params)
    cols = [d.name for d in cur.description or []]
    out = []
    for r in await cur.fetchall():
        out.append(dict(r) if isinstance(r, dict) else dict(zip(cols, r, strict=False)))
    return out


def _f(x: Any) -> float:
    return float(x) if x is not None else 0.0


def _pct(a: float, b: float) -> float:
    return round(100.0 * a / b, 1) if b else 0.0


async def build_quality_report(
    conn: psycopg.AsyncConnection[Any], run_id: int | None, *, include_http: bool = True
) -> dict[str, Any]:
    """run_id=None — все запуски. Все запросы только чтение."""
    rf_runs = "where sim_run_id = %s" if run_id else ""
    rf_run = "where run_id = %s" if run_id else ""
    p: tuple[Any, ...] = (run_id,) if run_id else ()

    # --- агент: прогоны и шаги --------------------------------------------------------------
    runs = await _rows(
        conn,
        f"""select kind, outcome, count(*) n, count(error) errors,
                   percentile_cont(0.5) within group (order by total_latency_ms) p50_ms,
                   percentile_cont(0.95) within group (order by total_latency_ms) p95_ms,
                   coalesce(sum(total_tokens),0) tokens
            from agent_runs {rf_runs} group by 1,2 order by 1,2""",
        p,
    )
    run_errors = await _rows(
        conn,
        f"select left(error, 160) error, count(*) n, max(id) last_run_id from agent_runs {rf_runs + (' and' if rf_runs else 'where')} error is not null group by 1 order by 2 desc limit 15",
        p,
    )
    steps = await _rows(
        conn,
        f"""select s.node, s.status, count(*) n,
                   percentile_cont(0.5) within group (order by s.latency_ms) p50_ms,
                   percentile_cont(0.95) within group (order by s.latency_ms) p95_ms,
                   coalesce(sum(s.prompt_tokens+s.completion_tokens),0) tokens
            from agent_steps s join agent_runs r on r.id = s.run_id {rf_runs.replace("sim_run_id", "r.sim_run_id")}
            group by 1,2 order by 1,2""",
        p,
    )
    step_errors = await _rows(
        conn,
        f"""select s.node, left(coalesce(s.output->>'error', s.output->>'reason', s.response_raw, '—'), 160) error, count(*) n, max(s.run_id) last_run_id
            from agent_steps s join agent_runs r on r.id = s.run_id
            where s.status in ('error','retry') {("and r.sim_run_id = %s" if run_id else "")}
            group by 1,2 order by 3 desc limit 15""",
        p,
    )
    lat = await _rows(
        conn,
        f"""select s.node, percentile_cont(0.5) within group (order by s.latency_ms) p50_ms,
                   percentile_cont(0.95) within group (order by s.latency_ms) p95_ms
            from agent_steps s join agent_runs r on r.id = s.run_id {rf_runs.replace("sim_run_id", "r.sim_run_id")} group by 1""",
        p,
    )
    lat_by_node = {row["node"]: row for row in lat}
    nodes: dict[str, dict[str, Any]] = {}
    for s in steps:
        slot = nodes.setdefault(
            s["node"],
            {
                "node": s["node"],
                "total": 0,
                "ok": 0,
                "fallback": 0,
                "error": 0,
                "retry": 0,
                "skipped": 0,
                "p50_ms": 0,
                "p95_ms": 0,
                "tokens": 0,
            },
        )
        slot["total"] += s["n"]
        slot[s["status"]] = slot.get(s["status"], 0) + s["n"]
        slot["tokens"] += int(s["tokens"])
    for slot in nodes.values():
        row = lat_by_node.get(slot["node"], {})
        slot["p50_ms"], slot["p95_ms"] = round(_f(row.get("p50_ms"))), round(_f(row.get("p95_ms")))
        slot["llm"] = bool(slot["tokens"] or slot["fallback"])
        slot["error_rate"] = _pct(slot["error"] + slot["retry"], slot["total"])
        slot["fallback_rate"] = _pct(slot["fallback"], slot["total"])
    total_runs = sum(r["n"] for r in runs)
    failed_runs = sum(r["n"] for r in runs if r["outcome"] == "failed")
    fallback_runs = sum(r["n"] for r in runs if r["outcome"] == "fallback_mock")
    total_steps = sum(v["total"] for v in nodes.values())
    llm_steps = sum(v["total"] for v in nodes.values() if v["llm"])
    fallback_steps = sum(v["fallback"] for v in nodes.values())

    # --- HITL: правки человека = «агент работает, но не так» --------------------------------
    hitl = await _rows(conn, f"select decision, count(*) n from human_decisions {rf_runs} group by 1", p)
    overrides = await _rows(
        conn,
        f"""select id, decision, reason, decided_by, left(comment, 200) comment, signal_id, incident_id, agent_run_id,
                   agent_proposal, modified_proposal, decided_at
            from human_decisions where decision in ('modify','reject') {("and sim_run_id = %s" if run_id else "")}
            order by decided_at desc nulls last limit 20""",
        p,
    )
    for o in overrides:
        o["changed_fields"] = _diff_keys(o.pop("agent_proposal", None), o.pop("modified_proposal", None))
        o["decided_at"] = o["decided_at"].isoformat() if o.get("decided_at") else None
    decided = sum(h["n"] for h in hitl if h["decision"])
    overridden = sum(h["n"] for h in hitl if h["decision"] in ("modify", "reject"))
    pending = await _rows(
        conn,
        f"""select count(*) n, min(requested_at) oldest from human_decisions where decision is null {("and sim_run_id = %s" if run_id else "")}""",
        p,
    )

    # --- инциденты и SLA ---------------------------------------------------------------------
    inc = await _rows(
        conn,
        f"select status, count(*) n, count(*) filter (where sla_breached) breached from incidents {rf_run} group by 1",
        p,
    )
    inc_breached = await _rows(
        conn,
        f"select public_id, title, team_code, status, sla_due_sim, criticality from incidents where sla_breached {('and run_id = %s' if run_id else '')} order by sla_due_sim desc limit 15",
        p,
    )
    for i in inc_breached:
        i["sla_due_sim"] = i["sla_due_sim"].isoformat() if i.get("sla_due_sim") else None
    sig = await _rows(conn, f"select status, count(*) n from signals {rf_run} group by 1", p)
    followups = await _rows(conn, f"select status, count(*) n from followups {rf_runs} group by 1", p)

    # --- сценарии ----------------------------------------------------------------------------
    scen = await _rows(conn, "select id, title_ru, last_run_at, last_result from scenarios order by id")
    scenarios = []
    for s in scen:
        res = s.get("last_result") or {}
        failed = [c for c in (res.get("checks") or []) if c.get("ok") is False]
        scenarios.append(
            {
                "id": s["id"],
                "title_ru": s["title_ru"],
                "last_run_at": s["last_run_at"].isoformat() if s.get("last_run_at") else None,
                "passed": res.get("passed") if res else None,
                "failed_checks": [{"code": c.get("code"), "detail": c.get("detail")} for c in failed],
            }
        )

    # --- комплаенс ---------------------------------------------------------------------------
    alerts = await _rows(
        conn,
        f"""select a.kind, a.decision, count(*) n from compliance_alerts a join audio_sessions s on s.id = a.session_id
            {("where s.run_id = %s" if run_id else "")} group by 1,2""",
        p,
    )
    alerts_total = sum(a["n"] for a in alerts if a["kind"] != "report")
    alerts_false = sum(a["n"] for a in alerts if a["decision"] == "false_positive")
    alerts_decided = sum(a["n"] for a in alerts if a["decision"] and a["kind"] != "report")
    tr = await _rows(conn, f"select status, count(*) n from transcripts {rf_run} group by 1", p)
    tr_failed = await _rows(
        conn,
        f"select public_id, filename, left(error, 200) error from transcripts where status = 'failed' {('and run_id = %s' if run_id else '')} order by id desc limit 10",
        p,
    )

    # --- HTTP (процесс) и журнал ------------------------------------------------------------
    http = http_obs.stats.snapshot() if include_http else None

    summary = {
        "generated_at": datetime.now(UTC).isoformat(),
        "run_id": run_id,
        "agent_runs": total_runs,
        "agent_failed": failed_runs,
        "agent_fallback_mock": fallback_runs,
        "steps": total_steps,
        "llm_steps": llm_steps,
        "steps_fallback_pct": _pct(fallback_steps, llm_steps),
        "steps_error": sum(v["error"] + v["retry"] for v in nodes.values()),
        "hitl_decided": decided,
        "hitl_overridden": overridden,
        "hitl_override_pct": _pct(overridden, decided),
        "hitl_pending": int(pending[0]["n"]) if pending else 0,
        "incidents": sum(i["n"] for i in inc),
        "sla_breached": sum(i["breached"] for i in inc),
        "scenarios_failed": [s["id"] for s in scenarios if s["passed"] is False],
        "scenarios_passed": sum(1 for s in scenarios if s["passed"]),
        "compliance_alerts": alerts_total,
        "compliance_false_pct": _pct(alerts_false, alerts_decided),
        "transcripts_failed": sum(t["n"] for t in tr if t["status"] == "failed"),
        "http_5xx": http["s5xx"] if http else None,
        "http_501": http["s501"] if http else None,
    }
    recommendations = _recommend(summary, nodes, overrides, scenarios, http, tr_failed, run_errors, step_errors)
    summary["health"] = _health(summary)
    return {
        "version": REPORT_VERSION,
        "summary": summary,
        "agent": {
            "runs": runs,
            "run_errors": run_errors,
            "nodes": sorted(nodes.values(), key=lambda x: (-x["error_rate"], -x["fallback_rate"])),
            "step_errors": step_errors,
        },
        "hitl": {
            "by_decision": hitl,
            "overrides": overrides,
            "pending": {
                "n": int(pending[0]["n"]) if pending else 0,
                "oldest": pending[0]["oldest"].isoformat() if pending and pending[0]["oldest"] else None,
            },
        },
        "incidents": {
            "by_status": inc,
            "sla_breached": inc_breached,
            "signals_by_status": sig,
            "followups_by_status": followups,
        },
        "scenarios": scenarios,
        "compliance": {"alerts": alerts, "transcripts_by_status": tr, "transcripts_failed": tr_failed},
        "http": http,
        "recommendations": recommendations,
    }


def _diff_keys(a: Any, b: Any) -> list[str]:
    if not isinstance(a, dict) or not isinstance(b, dict):
        return []
    return sorted(k for k in set(a) | set(b) if a.get(k) != b.get(k))[:12]


def _recommend(
    s: dict[str, Any],
    nodes: dict[str, dict[str, Any]],
    overrides: list[dict[str, Any]],
    scenarios: list[dict[str, Any]],
    http: dict[str, Any] | None,
    tr_failed: list[dict[str, Any]],
    run_errors: list[dict[str, Any]],
    step_errors: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Правила «что доработать»: каждая рекомендация — где смотреть и что делать. severity: high|medium|low."""
    rec: list[dict[str, Any]] = []

    def add(sev: str, area: str, text: str, where: str) -> None:
        rec.append({"severity": sev, "area": area, "text": text, "where": where})

    if s["agent_failed"]:
        top = run_errors[0]["error"] if run_errors else "см. agent_runs.error"
        add(
            "high",
            "agent",
            f"{s['agent_failed']} прогонов агента завершились ошибкой; самая частая: «{top}».",
            "GET /api/engine/runs?outcome=failed · agent_runs.error · var/log/app.jsonl event=agent_run_failed",
        )
    for n in nodes.values():
        if n["error_rate"] >= 5 and n["total"] >= 5:
            ex = next((e["error"] for e in step_errors if e["node"] == n["node"]), "—")
            add(
                "high",
                "agent",
                f"Узел «{n['node']}»: {n['error_rate']} % шагов с ошибкой/повтором ({n['error'] + n['retry']} из {n['total']}); пример: «{ex}».",
                f"agent_steps where node='{n['node']}' and status in ('error','retry') · промпт backend/app/agent/prompts/",
            )
    if s["steps_fallback_pct"] >= 50 and s["steps"] >= 20:
        add(
            "medium",
            "llm",
            f"{s['steps_fallback_pct']} % LLM-шагов выполнены на mock-правилах вместо модели (провайдер недоступен или без ключа). На демо это значит «заглушки», а не модель.",
            ".env GIGACHAT_AUTH_KEY_1/OPENROUTER_API_KEY · GET /api/health.llm · GET /api/engine/db/tables llm_profiles",
        )
    elif s["steps_fallback_pct"] >= 5 and s["llm_steps"] >= 20:
        add(
            "low",
            "llm",
            f"{s['steps_fallback_pct']} % шагов на fallback — модель периодически отказывает (таймаут/квота).",
            "var/log/app.jsonl event=llm_failover · agent_steps.status='fallback'",
        )
    if s["hitl_decided"] >= 3 and s["hitl_override_pct"] >= 30:
        fields = sorted({f for o in overrides for f in o["changed_fields"]})[:6]
        add(
            "high",
            "agent",
            f"Люди правят или отклоняют {s['hitl_override_pct']} % предложений агента ({s['hitl_overridden']} из {s['hitl_decided']}). Чаще меняют поля: {', '.join(fields) or '—'}.",
            "human_decisions where decision in ('modify','reject') · промпт decide.md · правила routing_rules/hitl_policies",
        )
    elif s["hitl_overridden"]:
        add(
            "medium",
            "agent",
            f"{s['hitl_overridden']} решений агента изменены человеком — разобрать комментарии как few-shot (use_as_fewshot).",
            "GET /api/hitl?decided=1 · human_decisions.comment",
        )
    if s["hitl_pending"] >= 20:
        add(
            "medium",
            "process",
            f"В очереди HITL {s['hitl_pending']} нерешённых запросов — очередь копится, порог HITL слишком широкий или нет дежурного.",
            "/?tab=hitl · hitl_policies · docs/USER-GUIDE.md §4",
        )
    if s["incidents"] and s["sla_breached"] / max(s["incidents"], 1) >= 0.2:
        add(
            "high",
            "process",
            f"SLA нарушен у {s['sla_breached']} из {s['incidents']} инцидентов — проверить маршрутизацию команд и эскалации.",
            "incidents where sla_breached · routing_rules · followups",
        )
    for sc in scenarios:
        if sc["passed"] is False:
            codes = ", ".join(c["code"] for c in sc["failed_checks"]) or "—"
            add(
                "high",
                "scenario",
                f"Сценарий «{sc['title_ru']}» ({sc['id']}) провален: {codes}.",
                f"make scenario ID={sc['id']} · scenarios.last_result · data/scenarios/",
            )
    never = [sc["id"] for sc in scenarios if sc["passed"] is None]
    if never:
        add(
            "low",
            "scenario",
            f"Сценарии не запускались: {', '.join(never)}. Нет данных о качестве.",
            "make scenario ID=all",
        )
    if s["compliance_alerts"] >= 3 and s["compliance_false_pct"] >= 25:
        add(
            "medium",
            "compliance",
            f"Ложных алертов комплаенса {s['compliance_false_pct']} % — ослабить ключевые фразы или поднять порог уверенности.",
            "compliance_alerts.decision='false_positive' · data/misselling_patterns.yaml · rules_detector.WEAK_KEYWORDS",
        )
    if tr_failed:
        add(
            "high",
            "compliance",
            f"{len(tr_failed)} транскриптов не разобраны: «{tr_failed[0]['error']}».",
            "GET /api/ingest/transcripts?status=failed · transcripts.error",
        )
    if http:
        if http["s5xx"]:
            worst = next((r for r in http["routes"] if r["s5xx"]), None)
            add(
                "high",
                "api",
                f"{http['s5xx']} ответов 5xx с момента запуска; чаще всего {worst['method']} {worst['route']}."
                if worst
                else f"{http['s5xx']} ответов 5xx.",
                "GET /api/reports/http · var/log/app.jsonl level=error event=http_request",
            )
        wanted = [r for r in http["routes"] if r["s501"]]
        if wanted:
            top = ", ".join(f"{r['method']} {r['route']} ({r['s501']})" for r in wanted[:5])
            add(
                "medium",
                "product",
                f"Пользователи/агенты вызывают нереализованные функции (501): {top}. Это очередь доработок по спросу.",
                "docs/tasks/README.md · карточки T-… из ответа 501",
            )
        if http["slow"]:
            slow = sorted((r for r in http["routes"] if r["slow"]), key=lambda r: -r["slow"])[:3]
            add(
                "low",
                "api",
                "Медленные запросы (>2 с): "
                + ", ".join(f"{r['method']} {r['route']} ×{r['slow']} (max {r['max_ms']} мс)" for r in slow)
                + ".",
                "индексы · pg_stat_statements · EXPLAIN",
            )
    if not rec:
        add("low", "ok", "Проблем не обнаружено: ошибок нет, правок человека мало, сценарии проходят.", "—")
    order = {"high": 0, "medium": 1, "low": 2}
    return sorted(rec, key=lambda r: order[r["severity"]])


def _health(s: dict[str, Any]) -> int:
    """Индекс здоровья 0–100: штрафы за ошибки, fallback, правки человека, SLA, проваленные сценарии, 5xx."""
    score = 100.0
    score -= min(30, 3 * s["agent_failed"] + s["steps_error"])
    score -= min(15, s["steps_fallback_pct"] / 5)
    score -= min(20, s["hitl_override_pct"] / 3)
    score -= min(10, 2 * s["sla_breached"])
    score -= min(15, 5 * len(s["scenarios_failed"]))
    score -= min(10, 2 * (s["http_5xx"] or 0))
    score -= min(10, 5 * s["transcripts_failed"])
    return int(max(0, round(score)))


# ------------------------------------------------------------------------------------------ Markdown
def render_markdown(rep: dict[str, Any]) -> str:
    s = rep["summary"]
    L: list[str] = []
    L.append(f"# Отчёт о качестве CX Pulse Control — {s['generated_at'][:16].replace('T', ' ')} UTC")
    L.append("")
    L.append(f"Запуск: {s['run_id'] or 'все'} · индекс здоровья **{s['health']}/100** · версия {rep['version']}")
    L.append("")
    L.append("## Сводка")
    L.append("")
    L.append("| Показатель | Значение |")
    L.append("|---|---|")
    L.append(
        f"| Прогонов агента / с ошибкой / на mock | {s['agent_runs']} / {s['agent_failed']} / {s['agent_fallback_mock']} |"
    )
    L.append(
        f"| Шагов / с ошибкой / LLM-шагов на fallback | {s['steps']} / {s['steps_error']} / {s['steps_fallback_pct']} % из {s['llm_steps']} |"
    )
    L.append(
        f"| HITL: решено / изменено или отклонено / в очереди | {s['hitl_decided']} / {s['hitl_overridden']} ({s['hitl_override_pct']} %) / {s['hitl_pending']} |"
    )
    L.append(f"| Инцидентов / с нарушением SLA | {s['incidents']} / {s['sla_breached']} |")
    L.append(
        f"| Сценарии: пройдено / провалено | {s['scenarios_passed']} / {', '.join(s['scenarios_failed']) or '0'} |"
    )
    L.append(f"| Комплаенс: алертов / ложных | {s['compliance_alerts']} / {s['compliance_false_pct']} % |")
    L.append(f"| Транскриптов с ошибкой | {s['transcripts_failed']} |")
    if s["http_5xx"] is not None:
        L.append(f"| HTTP 5xx / 501 (с запуска процесса) | {s['http_5xx']} / {s['http_501']} |")
    L.append("")
    L.append("## Что доработать")
    L.append("")
    for r in rep["recommendations"]:
        mark = {"high": "🔴", "medium": "🟡", "low": "🟢"}[r["severity"]]
        L.append(f"- {mark} **[{r['area']}]** {r['text']}  \n  _Где смотреть:_ {r['where']}")
    L.append("")
    L.append("## Агент по узлам")
    L.append("")
    L.append("| Узел | Шагов | ok | fallback | error+retry | % ошибок | p50 мс | p95 мс | токены |")
    L.append("|---|---:|---:|---:|---:|---:|---:|---:|---:|")
    for n in rep["agent"]["nodes"]:
        L.append(
            f"| {n['node']} | {n['total']} | {n['ok']} | {n['fallback']} | {n['error'] + n['retry']} | {n['error_rate']} | {n['p50_ms']} | {n['p95_ms']} | {n['tokens']} |"
        )
    if rep["agent"]["step_errors"]:
        L.append("")
        L.append("Ошибки шагов:")
        for e in rep["agent"]["step_errors"]:
            L.append(f"- `{e['node']}` ×{e['n']}: {e['error']} (run {e['last_run_id']})")
    if rep["agent"]["run_errors"]:
        L.append("")
        L.append("Ошибки прогонов:")
        for e in rep["agent"]["run_errors"]:
            L.append(f"- ×{e['n']}: {e['error']} (run {e['last_run_id']})")
    L.append("")
    L.append("## HITL — где человек поправил агента")
    L.append("")
    if not rep["hitl"]["overrides"]:
        L.append("Правок нет.")
    else:
        L.append("| # | Решение | Причина | Изменённые поля | Комментарий | Кто |")
        L.append("|---|---|---|---|---|---|")
        for o in rep["hitl"]["overrides"]:
            L.append(
                f"| {o['id']} | {o['decision']} | {o['reason'] or '—'} | {', '.join(o['changed_fields']) or '—'} | {(o['comment'] or '—').replace('|', '/')} | {o['decided_by'] or '—'} |"
            )
    L.append("")
    L.append("## Сценарии")
    L.append("")
    for sc in rep["scenarios"]:
        st = "✓" if sc["passed"] else ("✗" if sc["passed"] is False else "·")
        extra = (
            ("; провалено: " + ", ".join(f"{c['code']} ({c['detail']})" for c in sc["failed_checks"]))
            if sc["failed_checks"]
            else ""
        )
        L.append(f"- {st} {sc['id']} — {sc['title_ru']}{extra}")
    if rep["incidents"]["sla_breached"]:
        L.append("")
        L.append("## Инциденты с нарушением SLA")
        L.append("")
        for i in rep["incidents"]["sla_breached"]:
            L.append(
                f"- {i['public_id']} [{i['criticality']}] {i['title']} — команда {i['team_code']}, статус {i['status']}, срок {i['sla_due_sim']}"
            )
    if rep["compliance"]["transcripts_failed"]:
        L.append("")
        L.append("## Транскрипты с ошибкой")
        L.append("")
        for t in rep["compliance"]["transcripts_failed"]:
            L.append(f"- {t['public_id']} {t['filename'] or ''}: {t['error']}")
    http = rep.get("http")
    if http:
        L.append("")
        L.append("## HTTP (с момента запуска процесса)")
        L.append("")
        L.append(
            f"Запросов {http['requests']}, 5xx {http['s5xx']}, 501 {http['s501']}, 4xx {http['s4xx']}, медленных {http['slow']}."
        )
        bad = [r for r in http["routes"] if r["s5xx"] or r["s501"] or r["s4xx"]][:15]
        if bad:
            L.append("")
            L.append("| Маршрут | Всего | 5xx | 501 | 4xx | avg мс | max мс |")
            L.append("|---|---:|---:|---:|---:|---:|---:|")
            for r in bad:
                L.append(
                    f"| {r['method']} {r['route']} | {r['total']} | {r['s5xx']} | {r['s501']} | {r['s4xx']} | {r['avg_ms']} | {r['max_ms']} |"
                )
        if http["recent_errors"]:
            L.append("")
            L.append("Последние ошибки:")
            for e in http["recent_errors"][:10]:
                ts = time.strftime("%H:%M:%S", time.gmtime(e["ts"]))
                L.append(
                    f"- {ts} {e['status']} {e['method']} {e['path']} ({e['latency_ms']} мс){' — ' + e['error'] if e.get('error') else ''}"
                )
    L.append("")
    return "\n".join(L)
