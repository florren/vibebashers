"""Сессии комплаенс-контроля (T-186, T-188): реплики → детектор → триггеры → счётчик → алерт руководителю → инцидент.

Источник в MVP — транскрипт (batch или realtime-проигрывание текста). События compliance.* по contracts/events/compliance/session_event.
"""

from __future__ import annotations

import datetime as dt
import time
from dataclasses import dataclass
from typing import Any

import psycopg

from app.compliance import rules_detector as rd
from app.compliance import taxonomy
from app.compliance.llm_detector import Detector
from app.llm.base import LLMProfile
from app.llm.failover import ProviderChain
from app.logging import get_logger
from app.sim.events import EventBus, dumps

log = get_logger(__name__)

PATTERN_ALIASES = {
    "hidden_fee": "concealment",
    "hidden_conditions": "concealment",
    "rude": "rudeness",
    "tying": "tie_in",
}


def canon_pattern(code: str) -> str:
    return PATTERN_ALIASES.get(code, code)


@dataclass
class Session:
    id: int
    public_id: str
    run_id: int
    branch_id: int
    branch_code: str
    employee_id: int
    employee_name: str
    desk_no: int
    client_id: int | None
    deal_product: str | None
    source: str
    pacing: str
    status: str
    trigger_count: int
    alert_threshold: int
    incident_id: int | None
    transcript_id: int | None


async def load_products(conn: psycopg.AsyncConnection[Any]) -> dict[str, dict[str, Any]]:
    rows = await (await conn.execute("select code, name_ru, tariffs, promos from products")).fetchall()
    return {
        taxonomy._c(r, 0): {
            "name_ru": taxonomy._c(r, 1),
            "tariffs": taxonomy._c(r, 2) or {},
            "promos": taxonomy._c(r, 3) or [],
        }
        for r in rows
    }


async def resolve_branch(conn: psycopg.AsyncConnection[Any], code: str | None) -> tuple[int, str] | None:
    row = await (
        await conn.execute(
            "select id, code from branches where (%s::text is null) or code = %s::text or code = regexp_replace(%s::text, '^VSP-', '') order by (code = %s::text) desc, id limit 1",
            (code, code, code, code),
        )
    ).fetchone()
    return (int(taxonomy._c(row, 0)), str(taxonomy._c(row, 1))) if row else None


async def resolve_employee(
    conn: psycopg.AsyncConnection[Any], branch_id: int, public_id: str | None, desk_no: int | None
) -> tuple[int, str, int] | None:
    row = await (
        await conn.execute(
            "select id, display_name, desk_no from employees where branch_id = %s and is_active "
            "order by (public_id = %s::text) desc, (desk_no = %s::int) desc, desk_no nulls last, id limit 1",
            (branch_id, public_id, desk_no),
        )
    ).fetchone()
    if not row and public_id:
        row = await (
            await conn.execute("select id, display_name, desk_no from employees where public_id = %s", (public_id,))
        ).fetchone()
    return (int(taxonomy._c(row, 0)), str(taxonomy._c(row, 1)), int(taxonomy._c(row, 2) or 1)) if row else None


class ComplianceService:
    def __init__(
        self,
        conn: psycopg.AsyncConnection[Any],
        *,
        run_id: int,
        sim_time: dt.datetime,
        chain: ProviderChain,
        profile: LLMProfile,
        alert_threshold: int = 3,
        bus: EventBus | None = None,
    ) -> None:
        self.conn, self.run_id, self.sim_time, self.chain, self.profile = conn, run_id, sim_time, chain, profile
        self.alert_threshold = alert_threshold
        self.bus = bus or EventBus(conn, strict=False)
        self._products: dict[str, dict[str, Any]] | None = None

    # ------------------------------------------------------------------ сессии
    async def create_session(
        self,
        *,
        branch_code: str | None,
        employee_public_id: str | None = None,
        desk_no: int | None = None,
        client_id: int | None = None,
        deal_product: str | None = None,
        source: str = "transcript",
        pacing: str = "batch",
        transcript_id: int | None = None,
        diarization_mode: str = "manual",
        stt_provider: str = "none",
        stt_model: str | None = None,
        alert_threshold: int | None = None,
        demo_asset_id: int | None = None,
        store_audio: bool = False,
    ) -> Session:
        br = await resolve_branch(self.conn, branch_code)
        if not br:
            raise ValueError(f"отделение не найдено: {branch_code}")
        emp = await resolve_employee(self.conn, br[0], employee_public_id, desk_no)
        if not emp:
            raise ValueError(f"сотрудник не найден: {employee_public_id or desk_no} в {br[1]}")
        row = await (
            await self.conn.execute(
                "insert into audio_sessions (run_id, branch_id, employee_id, client_id, deal_product, source, stt_provider, stt_model, diarization_mode, status, trigger_count, alert_threshold, started_at, started_sim, store_audio, pacing, transcript_id, demo_asset_id) "
                "values (%s, %s, %s, %s, %s, %s, %s, %s, %s, 'live', 0, %s, now(), %s, %s, %s, %s, %s) returning id, public_id",
                (
                    self.run_id,
                    br[0],
                    emp[0],
                    client_id,
                    deal_product,
                    source,
                    stt_provider,
                    stt_model,
                    diarization_mode,
                    alert_threshold or self.alert_threshold,
                    self.sim_time,
                    store_audio,
                    pacing,
                    transcript_id,
                    demo_asset_id,
                ),
            )
        ).fetchone()
        s = Session(
            id=int(taxonomy._c(row, 0)),
            public_id=str(taxonomy._c(row, 1)),
            run_id=self.run_id,
            branch_id=br[0],
            branch_code=br[1],
            employee_id=emp[0],
            employee_name=emp[1],
            desk_no=desk_no or emp[2],
            client_id=client_id,
            deal_product=deal_product,
            source=source,
            pacing=pacing,
            status="live",
            trigger_count=0,
            alert_threshold=alert_threshold or self.alert_threshold,
            incident_id=None,
            transcript_id=transcript_id,
        )
        await self._emit(s, "compliance.session_started")
        return s

    async def get_session(self, session_id: int) -> Session | None:
        row = await (
            await self.conn.execute(
                "select s.id, s.public_id, s.run_id, s.branch_id, b.code, s.employee_id, e.display_name, coalesce(e.desk_no, 1), s.client_id, s.deal_product, s.source, s.pacing, s.status, s.trigger_count, s.alert_threshold, s.incident_id, s.transcript_id "
                "from audio_sessions s join branches b on b.id = s.branch_id join employees e on e.id = s.employee_id where s.id = %s",
                (session_id,),
            )
        ).fetchone()
        if not row:
            return None
        v = [taxonomy._c(row, i) for i in range(17)]
        return Session(
            int(v[0]),
            str(v[1]),
            int(v[2]),
            int(v[3]),
            str(v[4]),
            int(v[5]),
            str(v[6]),
            int(v[7]),
            v[8],
            v[9],
            str(v[10]),
            str(v[11]),
            str(v[12]),
            int(v[13]),
            int(v[14]),
            v[15],
            v[16],
        )

    async def add_utterance(
        self,
        s: Session,
        *,
        seq: int,
        speaker: str,
        text: str,
        t0_ms: int | None = None,
        t1_ms: int | None = None,
        speaker_source: str = "transcript",
        speaker_confidence: float = 1.0,
        stt_confidence: float | None = None,
        latency_ms: int | None = None,
    ) -> int:
        row = await (
            await self.conn.execute(
                "insert into utterances (session_id, seq, speaker, speaker_confidence, speaker_source, text, t0_ms, t1_ms, is_final, stt_confidence, latency_ms) values (%s, %s, %s, %s, %s, %s, %s, %s, true, %s, %s) returning id",
                (
                    s.id,
                    seq,
                    speaker,
                    speaker_confidence,
                    speaker_source,
                    text,
                    t0_ms or 0,
                    t1_ms if t1_ms is not None else (t0_ms or 0) + max(1000, len(text) * 60),
                    stt_confidence,
                    latency_ms,
                ),
            )
        ).fetchone()
        uid = int(taxonomy._c(row, 0))
        utt: dict[str, Any] = {
            "utterance_id": uid,
            "seq": seq,
            "speaker": speaker,
            "speaker_confidence": speaker_confidence,
            "text": text[:400],
            "is_final": True,
            "latency_ms": latency_ms,
        }
        if t0_ms is not None:
            utt["t0_ms"] = int(t0_ms)
        if t1_ms is not None:
            utt["t1_ms"] = int(t1_ms)
        await self._emit(s, "compliance.utterance", utterance=utt)
        return uid

    async def set_speaker(self, utterance_id: int, speaker: str) -> None:
        await self.conn.execute(
            "update utterances set speaker = %s, speaker_source = 'manual', speaker_confidence = 1.0 where id = %s",
            (speaker, utterance_id),
        )

    # ------------------------------------------------------------------ детекция
    async def products(self) -> dict[str, dict[str, Any]]:
        if self._products is None:
            self._products = await load_products(self.conn)
        return self._products

    async def detect(
        self, text: str, *, deal_product: str | None, transcript_kind: str, context: str, session_id: int | None = None
    ) -> tuple[rd.Finding, dict[str, Any], int] | None:
        """Правила → лучшая предварительная находка → вердикт LLM (mock = правила). None — реплика чистая."""
        patterns = await taxonomy.load_patterns(self.conn, only_active=True)
        script = await taxonomy.load_script(self.conn, taxonomy.script_kind_for(transcript_kind))
        prelim = rd.detect_utterance(
            text, patterns, script=script, products=await self.products(), deal_product=deal_product
        )
        if not prelim:
            return None
        # compliance_triggers.utterance_id уникален: одна реплика — один триггер; берём самый уверенный (immediate-паттерны в приоритете)
        pmap = {p.code: p for p in patterns}
        prelim.sort(
            key=lambda f: (
                (pmap.get(f.pattern_code) and pmap[f.pattern_code].alert_policy == "immediate"),
                f.confidence,
            ),
            reverse=True,
        )
        det = Detector(
            self.conn,
            run_id=self.run_id,
            sim_time=self.sim_time,
            chain=self.chain,
            profile=self.profile,
            session_id=session_id,
        )
        verdict, agent_run_id, _ = await det.verdict(
            prelim[0], text=text, context=context, products=await self.products()
        )
        return prelim[0], verdict, agent_run_id

    async def process_utterance(
        self, s: Session, utterance_id: int, text: str, *, transcript_kind: str = "branch_retail"
    ) -> list[dict[str, Any]]:
        """Реплика сотрудника → правила → подтверждение LLM → триггеры/счётчик/алерт. Возвращает созданные триггеры."""
        patterns = await taxonomy.load_patterns(self.conn, only_active=True)
        pmap = {p.code: p for p in patterns}
        context = (
            f"отделение {s.branch_code}, сотрудник {s.employee_name}, продукт сделки: {s.deal_product or 'не указан'}"
        )
        hit = await self.detect(
            text, deal_product=s.deal_product, transcript_kind=transcript_kind, context=context, session_id=s.id
        )
        if hit is None:
            return []
        prelim = [hit[0]]
        created: list[dict[str, Any]] = []
        for f in prelim:
            t0 = time.perf_counter()
            verdict, agent_run_id = hit[1], hit[2]
            conf = float(verdict.get("confidence") or 0)
            confirmed = bool(verdict.get("is_misselling")) and conf >= 0.6
            code = canon_pattern(str(verdict.get("pattern_code") or f.pattern_code))
            status = "confirmed" if confirmed else "dismissed"
            row = await (
                await self.conn.execute(
                    "insert into compliance_triggers (session_id, utterance_id, pattern_code, confidence, quote, explanation_ru, detected_by, status, agent_run_id, latency_ms, recommendation_ru, fact_check) "
                    "values (%s, %s, %s, %s, %s, %s, 'both', %s, %s, %s, %s, %s::jsonb) returning id",
                    (
                        s.id,
                        utterance_id,
                        code,
                        round(conf, 3),
                        (verdict.get("quote") or f.quote)[:400],
                        verdict.get("explanation_ru") or "",
                        status,
                        agent_run_id,
                        int((time.perf_counter() - t0) * 1000),
                        verdict.get("recommendation_ru") or f.recommendation_ru,
                        dumps(verdict.get("fact_check")) if verdict.get("fact_check") else None,
                    ),
                )
            ).fetchone()
            trig = {
                "id": int(taxonomy._c(row, 0)),
                "utterance_id": utterance_id,
                "pattern_code": code,
                "family": pmap[code].family if code in pmap else f.family,
                "confidence": round(conf, 3),
                "quote": (verdict.get("quote") or f.quote)[:240],
                "explanation_ru": verdict.get("explanation_ru") or "",
                "status": status,
                "recommendation_ru": verdict.get("recommendation_ru") or f.recommendation_ru,
                "fact_check": verdict.get("fact_check"),
            }
            created.append(trig)
            if not confirmed:
                continue
            s.trigger_count += 1
            await self.conn.execute(
                "update audio_sessions set trigger_count = %s, updated_at = now() where id = %s",
                (s.trigger_count, s.id),
            )
            await self._emit(
                s,
                "compliance.trigger",
                trigger={
                    "trigger_id": trig["id"],
                    "utterance_id": utterance_id,
                    "pattern_code": code,
                    "confidence": trig["confidence"],
                    "quote": trig["quote"],
                    "detected_by": "both",
                    "status": status,
                    "latency_ms": None,
                    "family": trig["family"],
                    "recommendation_ru": trig["recommendation_ru"],
                },
            )
            pat = pmap.get(code)
            immediate = bool(pat and pat.alert_policy == "immediate" and conf >= pat.immediate_threshold)
            if immediate or s.trigger_count >= s.alert_threshold:
                await self.raise_alert(s, kind="immediate" if immediate else "threshold", trigger=trig)
        return created

    # ------------------------------------------------------------------ алерты и инциденты
    async def raise_alert(self, s: Session, *, kind: str, trigger: dict[str, Any] | None = None) -> int | None:
        """Один алерт на сессию на вид (immediate/threshold); инцидент комплаенсу — один на сессию."""
        dup = await (
            await self.conn.execute(
                "select id from compliance_alerts where session_id = %s and kind = %s", (s.id, kind)
            )
        ).fetchone()
        if dup:
            return None
        if s.incident_id is None:
            s.incident_id = await self._open_incident(s, trigger)
        rec = (trigger or {}).get(
            "recommendation_ru"
        ) or "Разобрать встречу с сотрудником, при необходимости перезвонить клиенту."
        row = await (
            await self.conn.execute(
                "insert into compliance_alerts (session_id, incident_id, sent_at, channels, latency_ms, recommendation_ru, kind, transcript_id) values (%s, %s, now(), %s, %s, %s, %s, %s) returning id",
                (s.id, s.incident_id, ["manager_ui", "ws"], 0, rec, kind, s.transcript_id),
            )
        ).fetchone()
        alert_id = int(taxonomy._c(row, 0))
        s.status = "alerted"
        await self.conn.execute(
            "update audio_sessions set status = 'alerted', incident_id = %s, updated_at = now() where id = %s",
            (s.incident_id, s.id),
        )
        await self.conn.execute(
            "insert into notifications (run_id, recipient_type, team_code, incident_id, channel_code, template_code, subject, body, status, sent_sim, sent_at) "
            "values (%s, 'team', 'team_branch_network', %s, 'manager_ui', 'compliance_alert', %s, %s, 'sent', %s, now())",
            (
                self.run_id,
                s.incident_id,
                f"Комплаенс: {'немедленный алерт' if kind == 'immediate' else 'порог срабатываний'} — {s.employee_name}, стол {s.desk_no}",
                f"Отделение {s.branch_code}, сотрудник {s.employee_name}: {(trigger or {}).get('pattern_code', '—')} — «{(trigger or {}).get('quote', '')[:160]}». {rec}",
                self.sim_time,
            ),
        )
        alert = {
            "alert_id": alert_id,
            "kind": "counter" if kind == "threshold" else kind,
            "incident_id": s.incident_id,
            "channels": ["ws"],
            "summary_ru": f"{'Немедленный алерт' if kind == 'immediate' else 'Порог срабатываний'}: {(trigger or {}).get('pattern_code', '—')} ({s.trigger_count}/{s.alert_threshold})",
            "quotes": [(trigger or {}).get("quote", "")][: 1 if trigger else 0],
            "latency_ms": None,
            "recommendation_ru": rec,
        }
        await self._emit(s, "compliance.alert", alert=alert)
        log.info(
            "compliance_alert", session_id=s.id, kind=kind, trigger_count=s.trigger_count, incident_id=s.incident_id
        )
        return alert_id

    async def _open_incident(self, s: Session, trigger: dict[str, Any] | None) -> int:
        title = f"Мисселинг/поведение: {s.employee_name}, ВСП {s.branch_code}"
        row = await (
            await self.conn.execute(
                "insert into incidents (run_id, title, incident_type, team_code, co_team_codes, complexity, criticality, priority, status, flags, mass_impact, primary_client_id, created_by, created_sim, sla_due_sim, take_due_sim, routing_status, problem_summary) "
                "values (%s, %s, 'misselling', 'team_compliance', %s, 'medium', 'high', 2, 'awaiting_human', %s, 1, %s, 'compliance', %s, %s, %s, 'routed', %s::jsonb) returning id",
                (
                    self.run_id,
                    title[:120],
                    ["team_branch_network"],
                    ["compliance"],
                    s.client_id,
                    self.sim_time,
                    self.sim_time + dt.timedelta(days=3),
                    self.sim_time + dt.timedelta(hours=4),
                    dumps(
                        {
                            "session_id": s.id,
                            "session_public_id": s.public_id,
                            "employee_id": s.employee_id,
                            "branch_code": s.branch_code,
                            "trigger": trigger,
                            "deal_product": s.deal_product,
                            "text_ru": f"Встреча {s.public_id}: срабатываний {s.trigger_count}. Первый триггер: {(trigger or {}).get('pattern_code')} — «{(trigger or {}).get('quote', '')[:200]}»",
                        }
                    ),
                ),
            )
        ).fetchone()
        inc_id = int(taxonomy._c(row, 0))
        await self.conn.execute(
            "insert into incident_status_history (incident_id, from_status, to_status, actor_type, actor_ref, reason, changed_sim) values (%s, null, 'awaiting_human', 'agent', 'compliance', 'алерт комплаенс-контроля: ждёт решения руководителя', %s)",
            (inc_id, self.sim_time),
        )
        return inc_id

    async def ack_alert(
        self, alert_id: int, *, decision: str, by: str, comment: str | None = None
    ) -> dict[str, Any] | None:
        row = await (
            await self.conn.execute(
                "update compliance_alerts set acknowledged_at = now(), acknowledged_by = %s, decision = %s where id = %s and acknowledged_at is null returning session_id, incident_id",
                (by, decision, alert_id),
            )
        ).fetchone()
        if not row:
            existing = await (
                await self.conn.execute(
                    "select session_id,incident_id,decision from compliance_alerts where id=%s", (alert_id,)
                )
            ).fetchone()
            if not existing:
                return None
            return {
                "alert_id": alert_id,
                "session_id": taxonomy._c(existing, 0),
                "incident_id": taxonomy._c(existing, 1),
                "decision": taxonomy._c(existing, 2),
                "deduplicated": True,
            }
        session_id, incident_id = int(taxonomy._c(row, 0)), taxonomy._c(row, 1)
        if incident_id:
            new_status = {
                "false_positive": "rejected",
                "open_incident": "in_progress",
                "go": "in_progress",
                "acknowledged": "routed",
            }[decision]
            await self.conn.execute(
                "update incidents set status = %s, updated_at = now() where id = %s", (new_status, incident_id)
            )
            await self.conn.execute(
                "insert into incident_status_history (incident_id, from_status, to_status, actor_type, actor_ref, reason, changed_sim) values (%s, 'awaiting_human', %s, 'human', %s, %s, %s)",
                (
                    incident_id,
                    new_status,
                    by,
                    f"решение руководителя: {decision}" + (f" — {comment}" if comment else ""),
                    self.sim_time,
                ),
            )
        await self.conn.execute(
            "update human_decisions set decision=%s,decided_by=%s,comment=%s,decided_sim=%s,decided_at=now(),use_as_fewshot=case when %s then false else use_as_fewshot end "
            "where id=(select human_decision_id from compliance_alerts where id=%s) and decision is null",
            (
                "reject" if decision == "false_positive" else "accept",
                by,
                comment,
                self.sim_time,
                by.startswith("demo-agent:"),
                alert_id,
            ),
        )
        s = await self.get_session(session_id)
        if s:
            await self._emit(
                s,
                "compliance.alert",
                alert={
                    "alert_id": alert_id,
                    "incident_id": incident_id,
                    "channels": ["ws"],
                    "summary_ru": f"Решение руководителя: {decision}" + (f" — {comment}" if comment else ""),
                    "quotes": [],
                    "kind": "report",
                    "recommendation_ru": None,
                },
            )
        return {"alert_id": alert_id, "session_id": session_id, "incident_id": incident_id, "decision": decision}

    async def close_session(self, s: Session, report: dict[str, Any] | None = None) -> None:
        s.status = "closed"
        await self.conn.execute(
            "update audio_sessions set status = 'closed', finished_at = now(), report = coalesce(%s::jsonb, report), updated_at = now() where id = %s",
            (dumps(report) if report else None, s.id),
        )
        await self._emit(s, "compliance.session_closed")

    # ------------------------------------------------------------------ события
    async def _emit(self, s: Session, event_type: str, **extra: Any) -> None:
        payload: dict[str, Any] = {
            "event_type": event_type,
            "session_id": s.id,
            "employee_id": s.employee_id,
            "employee_display_name": s.employee_name,
            "branch_code": s.branch_code,
            "desk_no": s.desk_no,
            "client_id": s.client_id,
            "deal_product": s.deal_product,
            "source": s.source,
            "stt_provider": "none",
            "trigger_count": s.trigger_count,
            "alert_threshold": s.alert_threshold,
            "status": s.status,
            "pacing": s.pacing,
            "transcript_id": s.transcript_id,
            **extra,
        }
        try:
            await self.bus.emit(self.run_id, event_type, payload, self.sim_time)
        except Exception as e:  # noqa: BLE001 — событие не должно ломать обработку
            log.warning("compliance_event_failed", event_type=event_type, error=str(e)[:200])
        # до WS событие доходит через sim_events → topic compliance (realtime/notify.FAMILY_TOPIC)
