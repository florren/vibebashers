"""Транскрипты (T-208, T-216): приём JSON/TXT → анализ employee_quality (сессия комплаенса + отчёт) и client_signal (сигнал агенту)."""

from __future__ import annotations

import datetime as dt
import time
from collections.abc import Awaitable, Callable
from pathlib import Path
from typing import Any

import psycopg

from app.compliance import rules_detector as rd
from app.compliance import taxonomy
from app.compliance.llm_detector import Detector
from app.compliance.session import ComplianceService, Session, resolve_branch, resolve_employee
from app.compliance.txt_parser import normalize_turns, parse_txt
from app.contracts.registry import validate
from app.ingest.normalizer import create_signal
from app.llm.base import LLMProfile
from app.llm.failover import ProviderChain
from app.logging import get_logger
from app.sim.events import EventBus, dumps

log = get_logger(__name__)

CHANNEL_BY_KIND = {"branch_retail": "branch", "contact_center_call": "call", "contact_center_chat": "chat"}
NEGATIVE_HINTS = (
    "жалоб",
    "верните",
    "обман",
    "не предупред",
    "почему",
    "возмущ",
    "ужас",
    "не работает",
    "спишите",
    "не объясн",
    "навяз",
)


def _c(row: Any, i: int) -> Any:
    return taxonomy._c(row, i)


# ------------------------------------------------------------------------------------------------ приём
async def create_transcript(
    conn: psycopg.AsyncConnection[Any],
    doc: dict[str, Any],
    *,
    run_id: int,
    sim_time: dt.datetime,
    source: str = "api",
    fmt: str = "json",
    filename: str | None = None,
    bus: EventBus | None = None,
) -> dict[str, Any]:
    """Валидирует по ingest/transcript, резолвит отделение/сотрудника, пишет transcripts(status=received)."""
    doc = dict(doc)
    doc["turns"] = normalize_turns(list(doc.get("turns") or []))
    doc.setdefault("analyses", ["client_signal", "employee_quality"])
    errors = validate({k: v for k, v in doc.items() if v is not None or k in ("kind", "turns")}, "ingest/transcript")
    if errors:
        raise ValueError("транскрипт не по схеме ingest/transcript: " + "; ".join(errors[:3]))
    br = (
        await resolve_branch(conn, doc.get("branch_code"))
        if doc["kind"] == "branch_retail" or doc.get("branch_code")
        else None
    )
    emp = await resolve_employee(conn, br[0], doc.get("employee_public_id"), doc.get("desk_no")) if br else None
    client = doc.get("client") or {}
    row = await (
        await conn.execute(
            "insert into transcripts (run_id, kind, source, filename, format, branch_id, employee_id, client_id, contact_hints, deal_product, started_at, geo, turns, turns_count, analyses, status, received_sim) "
            "values (%s, %s, %s, %s, %s, %s, %s, %s, %s::jsonb, %s, %s, %s::jsonb, %s::jsonb, %s, %s, 'received', %s) returning id, public_id",
            (
                run_id,
                doc["kind"],
                source,
                filename,
                fmt,
                br[0] if br else None,
                emp[0] if emp else None,
                client.get("client_id"),
                dumps({k: v for k, v in client.items() if k != "client_id" and v}) if client else None,
                doc.get("deal_product"),
                doc.get("started_at"),
                dumps(doc.get("geo")) if doc.get("geo") else None,
                dumps(doc["turns"]),
                len(doc["turns"]),
                list(doc["analyses"]),
                sim_time,
            ),
        )
    ).fetchone()
    tid, pid = int(_c(row, 0)), str(_c(row, 1))
    bus = bus or EventBus(conn, strict=False)
    await bus.emit(
        run_id,
        "ingest.transcript_received",
        {
            "event_type": "ingest.transcript_received",
            "transcript_id": tid,
            "transcript_public_id": pid,
            "kind": doc["kind"],
            "turns_count": len(doc["turns"]),
            "analyses": list(doc["analyses"]),
            "external_id": doc.get("external_id"),
        },
        sim_time,
    )
    return {
        "id": tid,
        "public_id": pid,
        "status": "received",
        "turns_count": len(doc["turns"]),
        "analyses": list(doc["analyses"]),
    }


def load_file(path: Path, *, defaults: dict[str, Any] | None = None) -> tuple[dict[str, Any], str]:
    """Файл .json/.txt → (документ, формат)."""
    import json

    if path.suffix.lower() == ".json":
        doc = json.loads(path.read_text(encoding="utf-8"))
        if isinstance(doc, dict) and "transcript" in doc:
            doc = doc["transcript"]
        for k, v in (defaults or {}).items():
            doc.setdefault(k, v)
        return doc, "json"
    return parse_txt(path.read_text(encoding="utf-8"), defaults=defaults), "txt"


# ------------------------------------------------------------------------------------------------ анализ
async def analyze_transcript(
    conn: psycopg.AsyncConnection[Any],
    transcript_id: int,
    *,
    chain: ProviderChain,
    profile: LLMProfile,
    sim_time: dt.datetime,
    alert_threshold: int = 3,
    submit_signal: Callable[[int], Awaitable[Any]] | None = None,
    pacing_delay_s: float = 0.0,
) -> dict[str, Any]:
    """Полный анализ: employee_quality → сессия/триггеры/алерты/отчёт; client_signal → сигнал (origin=transcript)."""
    t_start = time.perf_counter()
    row = await (
        await conn.execute(
            "select t.run_id, t.kind, t.turns, t.analyses, t.branch_id, b.code, t.employee_id, e.public_id, t.client_id, t.contact_hints, t.deal_product, t.geo, t.public_id, e.desk_no "
            "from transcripts t left join branches b on b.id = t.branch_id left join employees e on e.id = t.employee_id where t.id = %s",
            (transcript_id,),
        )
    ).fetchone()
    if not row:
        raise ValueError(f"транскрипт {transcript_id} не найден")
    run_id, kind, turns, analyses = int(_c(row, 0)), str(_c(row, 1)), list(_c(row, 2) or []), list(_c(row, 3) or [])
    branch_code, employee_pid, client_id, hints, deal, geo, public_id, desk_no = (
        _c(row, 5),
        _c(row, 7),
        _c(row, 8),
        _c(row, 9) or {},
        _c(row, 10),
        _c(row, 11),
        _c(row, 12),
        _c(row, 13),
    )
    await conn.execute(
        "update transcripts set status = 'analyzing', updated_at = now() where id = %s", (transcript_id,)
    )
    await conn.commit()
    bus = EventBus(conn, strict=False)
    result: dict[str, Any] = {"transcript_id": transcript_id, "public_id": public_id}
    try:
        session_id: int | None = None
        report: dict[str, Any] | None = None
        if "employee_quality" in analyses:
            svc = ComplianceService(
                conn,
                run_id=run_id,
                sim_time=sim_time,
                chain=chain,
                profile=profile,
                alert_threshold=alert_threshold,
                bus=bus,
            )
            if not branch_code:
                report = await _quality_without_session(conn, svc, turns, kind, deal, public_id)
                await conn.commit()
            else:
                s = await svc.create_session(
                    branch_code=branch_code,
                    employee_public_id=employee_pid,
                    desk_no=desk_no,
                    client_id=client_id,
                    deal_product=deal,
                    source="transcript",
                    pacing="realtime" if pacing_delay_s else "batch",
                    transcript_id=transcript_id,
                )
                session_id = s.id
                report = await _employee_quality(conn, svc, s, turns, kind, pacing_delay_s=pacing_delay_s)
                await conn.commit()
        signal_id: int | None = None
        if "client_signal" in analyses:
            signal_id = await _client_signal(
                conn, run_id, sim_time, kind, turns, client_id, hints, geo, transcript_id, branch_code, deal, report
            )
            await conn.commit()
            if signal_id and submit_signal:
                await submit_signal(signal_id)
        latency = int((time.perf_counter() - t_start) * 1000)
        await conn.execute(
            "update transcripts set status = 'done', signal_id = %s, audio_session_id = %s, report = %s::jsonb, analyzed_at = now(), updated_at = now() where id = %s",
            (signal_id, session_id, dumps({**report, "latency_ms": latency}) if report else None, transcript_id),
        )
        await bus.emit(
            run_id,
            "ingest.transcript_analyzed",
            {
                "event_type": "ingest.transcript_analyzed",
                "transcript_id": transcript_id,
                "transcript_public_id": public_id,
                "kind": kind,
                "turns_count": len(turns),
                "analyses": analyses,
                "signal_id": signal_id,
                "audio_session_id": session_id,
                "latency_ms": latency,
            },
            sim_time,
        )
        await conn.commit()
        result.update(
            {
                "status": "done",
                "signal_id": signal_id,
                "audio_session_id": session_id,
                "report": report,
                "latency_ms": latency,
            }
        )
        log.info(
            "transcript_analyzed",
            transcript_id=transcript_id,
            signal_id=signal_id,
            session_id=session_id,
            findings=len((report or {}).get("findings") or []),
            ms=latency,
        )
    except Exception as e:  # noqa: BLE001 — статус failed с текстом ошибки, не роняем воркер
        await conn.rollback()
        await conn.execute(
            "update transcripts set status = 'failed', error = %s, updated_at = now() where id = %s",
            (f"{type(e).__name__}: {e}"[:500], transcript_id),
        )
        await conn.commit()
        log.exception("transcript_failed", transcript_id=transcript_id)
        result.update({"status": "failed", "error": str(e)[:300]})
    return result


def _finding(seq: int, trig: dict[str, Any], pat: taxonomy.Pattern | None) -> dict[str, Any]:
    return {
        "turn_seq": seq,
        "pattern_code": trig["pattern_code"],
        "family": trig["family"],
        "confidence": float(trig["confidence"]),
        "quote": trig["quote"],
        "explanation_ru": trig["explanation_ru"] or "совпадение с паттерном",
        "recommendation_ru": trig.get("recommendation_ru")
        or (pat.recommendation_ru if pat else None)
        or "Разобрать с сотрудником",
        "training_module": pat.training_module if pat else None,
        "fact_check": _report_fact(trig.get("fact_check")),
        "alert_policy": pat.alert_policy if pat else "counter",
    }


async def _employee_quality(
    conn: psycopg.AsyncConnection[Any],
    svc: ComplianceService,
    s: Session,
    turns: list[dict[str, Any]],
    kind: str,
    *,
    pacing_delay_s: float,
) -> dict[str, Any]:
    """Сессия комплаенса по транскрипту: реплики → триггеры/алерты → отчёт; сессия закрывается с отчётом."""
    import asyncio

    patterns = await taxonomy.load_patterns(conn, only_active=True)
    pmap = {p.code: p for p in patterns}
    findings: list[dict[str, Any]] = []
    employee_texts: list[tuple[int, str]] = []
    for t in turns:
        uid = await svc.add_utterance(
            s, seq=int(t["seq"]), speaker=t["speaker"], text=t["text"], t0_ms=t.get("t0_ms"), t1_ms=t.get("t1_ms")
        )
        if t["speaker"] != "employee":
            continue
        employee_texts.append((int(t["seq"]), t["text"]))
        for trig in await svc.process_utterance(s, uid, t["text"], transcript_kind=kind):
            if trig["status"] == "confirmed":
                findings.append(_finding(int(t["seq"]), trig, pmap.get(trig["pattern_code"])))
        if pacing_delay_s:
            await conn.commit()
            await asyncio.sleep(pacing_delay_s)
    header = f"Встреча {s.public_id} ({s.employee_name}, ВСП {s.branch_code})"
    report = await _finish_report(conn, svc, findings, employee_texts, turns, kind, header=header, session_id=s.id)
    report = {**report, "audio_session_id": s.id, "branch_code": s.branch_code}
    await svc.close_session(s, report)
    if findings:
        await conn.execute(
            "update employees set violations_count = violations_count + %s where id = %s",
            (len(findings), s.employee_id),
        )
    await svc._emit(s, "compliance.report_ready")
    return report


async def _quality_without_session(
    conn: psycopg.AsyncConnection[Any],
    svc: ComplianceService,
    turns: list[dict[str, Any]],
    kind: str,
    deal: str | None,
    public_id: str,
) -> dict[str, Any]:
    """Контакт-центр без отделения/сотрудника: только отчёт (без триггеров и алертов), детекция та же."""
    patterns = await taxonomy.load_patterns(conn, only_active=True)
    pmap = {p.code: p for p in patterns}
    findings: list[dict[str, Any]] = []
    employee_texts: list[tuple[int, str]] = []
    for t in turns:
        if t["speaker"] != "employee":
            continue
        employee_texts.append((int(t["seq"]), t["text"]))
        hit = await svc.detect(
            t["text"], deal_product=deal, transcript_kind=kind, context=f"контакт-центр, продукт: {deal or 'не указан'}"
        )
        if hit is None:
            continue
        f, verdict, _ = hit
        conf = float(verdict.get("confidence") or 0)
        if not (bool(verdict.get("is_misselling")) and conf >= 0.6):
            continue
        code = str(verdict.get("pattern_code") or f.pattern_code)
        trig = {
            "pattern_code": code,
            "family": pmap[code].family if code in pmap else f.family,
            "confidence": round(conf, 3),
            "quote": (verdict.get("quote") or f.quote)[:240],
            "explanation_ru": verdict.get("explanation_ru") or "",
            "recommendation_ru": verdict.get("recommendation_ru") or f.recommendation_ru,
            "fact_check": verdict.get("fact_check"),
        }
        findings.append(_finding(int(t["seq"]), trig, pmap.get(code)))
    report = await _finish_report(
        conn,
        svc,
        findings,
        employee_texts,
        turns,
        kind,
        header=f"Разговор {public_id} (контакт-центр)",
        session_id=None,
    )
    return {**report, "audio_session_id": None, "branch_code": None}


async def _finish_report(
    conn: psycopg.AsyncConnection[Any],
    svc: ComplianceService,
    findings: list[dict[str, Any]],
    employee_texts: list[tuple[int, str]],
    turns: list[dict[str, Any]],
    kind: str,
    *,
    header: str,
    session_id: int | None,
) -> dict[str, Any]:
    """Этапы скрипта + итог + план действий → отчёт transcript_report (через LLM; mock = подсказка правил)."""
    script = await taxonomy.load_script(conn, taxonomy.script_kind_for(kind))
    steps_rules = rd.check_script([t for _, t in employee_texts], script)
    steps: list[dict[str, Any]] = []
    for st in steps_rules:
        ev_seq = None
        if st["evidence"]:
            ev_seq = next((seq for seq, txt in employee_texts if any(m in txt.lower() for m in st["evidence"])), None)
        status = st["status"] if st["status"] in ("done", "missed") else "not_applicable"
        steps.append({"code": st["code"], "status": status, "evidence_turn_seq": ev_seq})
    missed = [x["code"] for x in steps if x["status"] == "missed"]
    names = {st.code: st.name_ru for st in (script.steps if script else [])}
    missed_ru = [names.get(c, c) for c in missed]
    fam = sorted({f["family"] for f in findings})
    overall = (
        f"{header}: нарушений {len(findings)}"
        + (f" ({', '.join(fam)})" if fam else "")
        + (f"; пропущены этапы скрипта: {', '.join(missed_ru)}" if missed else "; этапы скрипта соблюдены")
        + "."
    )
    actions = []
    if any(f["alert_policy"] == "immediate" for f in findings):
        actions.append(
            "Срочно: разобрать встречу с сотрудником в день события, перезвонить клиенту и уточнить условия."
        )
    if any(f["family"] == "misselling" for f in findings):
        actions.append("Проверить оформленные документы по сделке на предмет навязанных/подменённых продуктов.")
    mods = sorted({f["training_module"] for f in findings if f.get("training_module")})
    if mods:
        actions.append("Назначить модули обучения: " + ", ".join(mods) + ".")
    if missed:
        actions.append("Отработать пропущенные этапы скрипта: " + ", ".join(missed_ru) + ".")
    if not actions:
        actions.append("Нарушений не выявлено; отметить встречу как эталон при разборе смены.")
    det = Detector(
        conn, run_id=svc.run_id, sim_time=svc.sim_time, chain=svc.chain, profile=svc.profile, session_id=session_id
    )
    transcript_text = "\n".join(
        f"[{t['seq']}] {'Сотрудник' if t['speaker'] == 'employee' else 'Клиент'}: {t['text']}" for t in turns
    )
    report, _, _ = await det.report(
        transcript_text=transcript_text,
        findings=findings,
        script_code=script.code if script else "—",
        script_steps=steps,
        products=await svc.products(),
        overall_hint=overall,
        action_hint=" ".join(actions),
    )
    return {**report, "employee_public_id": None, "llm_source": "mock" if svc.profile.provider == "mock" else "live"}


def _report_fact(fc: dict[str, Any] | None) -> dict[str, Any] | None:
    """transcript_report.findings[].fact_check = {claim, truth, source_table, source_key, verified}: берём первый опровергнутый факт."""
    if not fc:
        return None
    facts: list[dict[str, Any]] = (
        list(fc["facts"]) if isinstance(fc.get("facts"), list) else ([fc] if fc.get("claim") else [])
    )
    pick = next((f for f in facts if f.get("is_false")), facts[0] if facts else None)
    if not pick:
        return None
    return {
        "claim": str(pick.get("claim", ""))[:300],
        "truth": str(pick.get("truth", ""))[:300],
        "source_table": pick.get("source_table") or "products",
        "source_key": pick.get("source_key"),
        "verified": bool(pick.get("verified", False)),
    }


async def _client_signal(
    conn: psycopg.AsyncConnection[Any],
    run_id: int,
    sim_time: dt.datetime,
    kind: str,
    turns: list[dict[str, Any]],
    client_id: int | None,
    hints: dict[str, Any],
    geo: dict[str, Any] | None,
    transcript_id: int,
    branch_code: str | None,
    deal: str | None,
    report: dict[str, Any] | None,
) -> int | None:
    """Реплики клиента → сигнал агенту (origin=transcript), только если клиент жалуется/просит; иначе сигнал не создаём."""
    client_lines = [t["text"] for t in turns if t["speaker"] == "client"]
    if not client_lines:
        return None
    text = " ".join(client_lines)
    complaining = any(h in text.lower() for h in NEGATIVE_HINTS)
    if not complaining:
        return None  # нарушения сотрудника без жалобы клиента закрывает инцидент комплаенса, а не сигнал агенту
    findings = list((report or {}).get("findings") or [])
    if findings:
        text += (
            " [Комплаенс: в разговоре зафиксированы нарушения со стороны сотрудника — "
            + ", ".join(sorted({f["pattern_code"] for f in findings}))
            + "]"
        )
    msg = {
        "channel": CHANNEL_BY_KIND.get(kind, "branch"),
        "channel_subtype": "transcript",
        "external_id": f"transcript-{transcript_id}",
        "client": {"client_id": client_id, "contact_hints": hints or None},
        "text": text[:4000],
        "timestamp": sim_time.isoformat(),
        "geo": geo or {"source": "none"},
        "origin": "transcript",
        "meta": {"transcript_id": transcript_id, "branch_code": branch_code, "deal_product": deal},
    }
    res = await create_signal(
        conn, msg, source_code="rest_transcripts", run_id=run_id, sim_time=sim_time, emit_event=True
    )
    return int(res["signal_id"]) if res.get("status") == "accepted" else None
