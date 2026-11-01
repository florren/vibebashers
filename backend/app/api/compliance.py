"""Роутер тега `compliance` (OpenAPI 1.4.0). Сессии из транскриптов, микрофона и файла, триггеры, алерты, таксономия, отчёты, статистика.

Источник `file` (T-183): сервер читает WAV чанками в реальном темпе. Неизвестный source — 422.
"""

from __future__ import annotations

import asyncio
import wave
from pathlib import Path
from typing import Any

from fastapi import APIRouter, HTTPException, Query, Request
from fastapi.responses import JSONResponse, PlainTextResponse, Response

from app.api._compliance_support import analyze_in_background, run_context
from app.api.common import db, fetch_all, fetch_one, resolve_run_id
from app.compliance import taxonomy
from app.compliance.session import ComplianceService
from app.compliance.transcripts import create_transcript, load_file
from app.config import get_settings
from app.search.cases import entity_filter
from app.sim.events import dumps
from app.stt import registry
from app.stt.live import play_wav, request_stop, set_file_speaker

_REPO_ROOT = Path(__file__).resolve().parents[3]

router = APIRouter(tags=["compliance"])

SESSION_COLS = (
    "s.id, s.public_id, s.deal_product, s.source, s.stt_provider, s.stt_model, s.diarization_mode, s.status, s.trigger_count, s.alert_threshold, "
    "s.incident_id, s.started_at, s.finished_at, s.store_audio, s.pacing, s.transcript_id, s.client_id, "
    "jsonb_build_object('id', b.id, 'code', b.code, 'name_ru', b.name_ru, 'region_code', b.region_code, 'manager_display_name', b.manager_display_name) as branch, "
    "jsonb_build_object('id', e.id, 'public_id', e.public_id, 'display_name', e.display_name, 'desk_no', e.desk_no, 'position', e.position, 'violations_count', e.violations_count) as employee"
)
SESSION_FROM = "from audio_sessions s join branches b on b.id = s.branch_id join employees e on e.id = s.employee_id"
ALERT_COLS = (
    "a.id, a.session_id, a.incident_id, b.code as branch_code, coalesce(e.desk_no, 1) as desk_no, e.display_name as employee_display_name, "
    "coalesce(a.recommendation_ru, '') as summary_ru, a.sent_at, a.channels, a.latency_ms, a.acknowledged_at, a.acknowledged_by, a.decision, a.kind, a.transcript_id, s.trigger_count, s.deal_product, "
    "(select coalesce(jsonb_agg(ct.quote order by ct.id), '[]'::jsonb) from compliance_triggers ct where ct.session_id = s.id and ct.status = 'confirmed') as quotes, "
    "(select coalesce(jsonb_agg(distinct ct.pattern_code), '[]'::jsonb) from compliance_triggers ct where ct.session_id = s.id and ct.status = 'confirmed') as patterns"
)
ALERT_FROM = "from compliance_alerts a join audio_sessions s on s.id = a.session_id join branches b on b.id = s.branch_id join employees e on e.id = s.employee_id"


@router.get("/api/compliance/branches", summary="Отделения с сотрудниками (для выбора на экране /compliance)")
async def get_compliance_branches(request: Request) -> Any:
    async with db() as conn:
        return await fetch_all(
            conn,
            "select b.id, b.code, b.name_ru, c.name_ru as city_name, b.region_code, b.manager_display_name, (b.manager_chat_id is not null) as telegram_alerts_enabled, "
            "coalesce((select jsonb_agg(jsonb_build_object('id', e.id, 'public_id', e.public_id, 'display_name', e.display_name, 'desk_no', e.desk_no, 'position', e.position, 'violations_count', e.violations_count, 'is_active', e.is_active) order by e.desk_no) "
            "from employees e where e.branch_id = b.id), '[]'::jsonb) as employees "
            "from branches b left join cities c on c.id = b.city_id order by b.code",
        )


@router.get("/api/compliance/sessions", summary="Аудиосессии")
async def get_compliance_sessions(
    request: Request,
    run_id: str | None = None,
    status: str | None = None,
    employee_id: int | None = None,
    limit: int = Query(default=50, ge=1, le=500),
    cursor: str | None = None,
) -> Any:
    where: list[str] = ["true"]
    args: list[Any] = []
    async with db() as conn:
        rid = await resolve_run_id(conn, run_id)
        if rid is not None:
            where.append("s.run_id = %s")
            args.append(rid)
        if status:
            where.append("s.status = any(%s)")
            args.append(status.split(","))
        if employee_id:
            where.append("s.employee_id = %s")
            args.append(employee_id)
        if cursor and cursor.isdigit():
            where.append("s.id < %s")
            args.append(int(cursor))
        rows = await fetch_all(
            conn,
            f"select {SESSION_COLS} {SESSION_FROM} where {' and '.join(where)} order by s.id desc limit %s",
            [*args, limit + 1],
        )  # noqa: S608
    items = rows[:limit]
    return {"items": items, "next_cursor": str(items[-1]["id"]) if len(rows) > limit else None}


async def _start_mic_session(request: Request, body: dict[str, Any]) -> Any:
    """source=mic (B10): создаёт живую сессию и отдаёт URL бинарного WebSocket /ws/audio/{id}; реплики приходят по мере речи."""
    from app.stt import registry

    code = body.get("stt_provider") or registry.default_code()
    try:
        prov = registry.get(code)
    except LookupError:
        info = next((x for x in registry.list_info() if x.code == code), None)
        raise HTTPException(
            status_code=422, detail=f"STT-провайдер {code!r} недоступен: {info.note_ru if info else ''}"
        ) from None
    mode = body.get("diarization_mode") or "manual"
    if mode not in ("stereo", "manual", "auto"):
        raise HTTPException(status_code=422, detail="diarization_mode: stereo | manual | auto")
    if code == "browser" and mode == "stereo":
        raise HTTPException(status_code=422, detail="browser не разделяет каналы — выберите manual или auto")
    async with db() as conn:
        emp = await fetch_one(
            conn,
            "select e.public_id, e.desk_no, b.code from employees e join branches b on b.id = e.branch_id where e.id = %s",
            (int(body["employee_id"]),),
        )
        if not emp:
            raise HTTPException(status_code=404, detail="сотрудник не найден")
        run_id, sim_time = await run_context(request, conn)
        s = get_settings()
        svc = ComplianceService(
            conn,
            run_id=run_id,
            sim_time=sim_time,
            chain=request.app.state.llm_chain,
            profile=request.app.state.llm_chain.profile_for("fast", request.app.state.llm_profile),
            alert_threshold=int(body.get("alert_threshold") or s.compliance_alert_threshold),
        )
        sess = await svc.create_session(
            branch_code=emp["code"],
            employee_public_id=emp["public_id"],
            desk_no=emp["desk_no"],
            client_id=int(body["client_id"]) if body.get("client_id") else None,
            deal_product=body.get("deal_product"),
            source="mic",
            pacing="realtime",
            diarization_mode=mode,
            stt_provider=code,
            stt_model=prov.info().model,
        )
        row = await fetch_one(conn, f"select {SESSION_COLS} {SESSION_FROM} where s.id = %s", (sess.id,))  # noqa: S608
    channels = 2 if mode == "stereo" else 1
    return JSONResponse(
        _json({**(row or {}), "audio_ws_url": f"/ws/audio/{sess.id}", "sample_rate": 16000, "channels": channels}),
        status_code=201,
    )


def _wav_channels(path: Path) -> int:
    if not path.is_file():
        raise HTTPException(status_code=422, detail="файл демо-актива не найден")
    try:
        with wave.open(str(path), "rb") as wf:
            channels = wf.getnchannels()
            pcm16 = wf.getsampwidth() == 2 and wf.getframerate() == 16000 and wf.getcomptype() == "NONE"
            if not pcm16 or channels not in (1, 2):
                raise HTTPException(status_code=422, detail="WAV должен быть PCM16, 16 кГц, 1 или 2 канала")
    except HTTPException:
        raise
    except (wave.Error, EOFError, OSError) as exc:
        raise HTTPException(status_code=422, detail="WAV должен быть PCM16, 16 кГц, 1 или 2 канала") from exc
    return channels


async def _start_file_session(request: Request, body: dict[str, Any]) -> Any:
    """source=file (T-183): WAV из demo_assets чанками 100 мс в LiveSession. audio_ws_url не отдаём."""
    mode = body.get("diarization_mode")
    if mode not in ("stereo", "manual", "auto"):
        raise HTTPException(status_code=422, detail="diarization_mode: stereo | manual | auto")
    code = body.get("stt_provider") or registry.default_code()
    if code == "browser":
        raise HTTPException(status_code=422, detail="stt_provider=browser не принимает файл — нужен серверный STT")
    try:
        prov = registry.get(code)
    except LookupError:
        raise HTTPException(status_code=422, detail=f"STT-провайдер {code!r} недоступен") from None
    if not body.get("employee_id"):
        raise HTTPException(status_code=422, detail="нужен employee_id")
    if not body.get("demo_asset_id"):
        raise HTTPException(status_code=422, detail="для source=file нужен demo_asset_id")
    async with db() as conn:
        emp = await fetch_one(
            conn,
            "select e.public_id, e.desk_no, b.code from employees e join branches b on b.id = e.branch_id where e.id = %s",
            (int(body["employee_id"]),),
        )
        if not emp:
            raise HTTPException(status_code=404, detail="сотрудник не найден")
        asset = await fetch_one(conn, "select kind, path from demo_assets where id = %s", (int(body["demo_asset_id"]),))
        if not asset:
            raise HTTPException(status_code=404, detail="демо-актив не найден")
        if asset["kind"] != "audio":
            raise HTTPException(status_code=422, detail="демо-актив должен быть kind=audio")
        raw = Path(str(asset["path"]))
        path = raw if raw.is_absolute() else _REPO_ROOT / raw
        channels = _wav_channels(path)
        if mode == "stereo" and channels != 2:
            raise HTTPException(status_code=422, detail="режим stereo требует WAV с двумя каналами")
        run_id, sim_time = await run_context(request, conn)
        s = get_settings()
        svc = ComplianceService(
            conn,
            run_id=run_id,
            sim_time=sim_time,
            chain=request.app.state.llm_chain,
            profile=request.app.state.llm_chain.profile_for("fast", request.app.state.llm_profile),
            alert_threshold=int(body.get("alert_threshold") or s.compliance_alert_threshold),
        )
        sess = await svc.create_session(
            branch_code=emp["code"],
            employee_public_id=emp["public_id"],
            desk_no=emp["desk_no"],
            client_id=int(body["client_id"]) if body.get("client_id") else None,
            deal_product=body.get("deal_product"),
            source="file",
            pacing="realtime",
            diarization_mode=mode,
            stt_provider=code,
            stt_model=prov.info().model,
            alert_threshold=int(body.get("alert_threshold") or s.compliance_alert_threshold),
            demo_asset_id=int(body["demo_asset_id"]),
            store_audio=bool(body.get("store_audio", False)),
        )
        row = await fetch_one(conn, f"select {SESSION_COLS} {SESSION_FROM} where s.id = %s", (sess.id,))  # noqa: S608
    asyncio.create_task(play_wav(request.app, sess.id, str(path), provider_code=code, channels=channels))
    return JSONResponse(
        _json({**(row or {}), "audio_ws_url": None, "sample_rate": 16000, "channels": channels}),
        status_code=201,
    )


@router.post("/api/compliance/sessions", summary="Начать сессию (микрофон, файл или транскрипт)", status_code=201)
async def post_compliance_sessions(request: Request, body: dict[str, Any]) -> Any:
    """source=transcript: берёт демо-актив (demo_asset_id → demo_assets.path) или файл из data/import/transcripts по `asset`, проигрывает реплики в темпе `pacing`."""
    source = body.get("source") or "transcript"
    if source == "mic":
        return await _start_mic_session(request, body)
    if source == "file":
        return await _start_file_session(request, body)
    if source != "transcript":
        raise HTTPException(status_code=422, detail="source: mic | file | transcript")
    from pathlib import Path

    from app.api.ingest import IMPORT_DIR

    path: Path | None = None
    async with db() as conn:
        if body.get("demo_asset_id"):
            row = await fetch_one(conn, "select path from demo_assets where id = %s", (int(body["demo_asset_id"]),))
            if not row:
                raise HTTPException(status_code=404, detail="демо-актив не найден")
            path = Path(row["path"]) if Path(row["path"]).is_absolute() else IMPORT_DIR.parents[1] / row["path"]
        elif body.get("asset"):
            cand = IMPORT_DIR / str(body["asset"])
            if not cand.exists() or cand.suffix.lower() not in (".json", ".txt"):
                raise HTTPException(status_code=404, detail="файл транскрипта не найден в data/import/transcripts")
            path = cand
        if path is None:
            raise HTTPException(
                status_code=422, detail="для source=transcript нужен demo_asset_id или asset (имя файла)"
            )
        emp = await fetch_one(
            conn,
            "select e.public_id, e.desk_no, b.code from employees e join branches b on b.id = e.branch_id where e.id = %s",
            (int(body["employee_id"]),),
        )
        if not emp:
            raise HTTPException(status_code=404, detail="сотрудник не найден")
        doc, fmt = load_file(path)
        doc.update({"branch_code": emp["code"], "employee_public_id": emp["public_id"], "desk_no": emp["desk_no"]})
        if body.get("client_id"):
            doc["client_id"] = int(body["client_id"])
        if body.get("deal_product"):
            doc["deal_product"] = body["deal_product"]
        run_id, sim_time = await run_context(request, conn)
        tr = await create_transcript(
            conn, doc, run_id=run_id, sim_time=sim_time, source="scenario", fmt=fmt, filename=path.name
        )
    pacing = body.get("pacing") or "realtime"
    asyncio.create_task(
        analyze_in_background(request, int(tr["id"]), pacing_delay_s=1.5 if pacing == "realtime" else 0.0)
    )
    # ждём появления сессии (создаётся в начале анализа)
    for _ in range(40):
        await asyncio.sleep(0.1)
        async with db() as conn:
            row = await fetch_one(
                conn,
                f"select {SESSION_COLS} {SESSION_FROM} where s.transcript_id = %s order by s.id desc limit 1",
                (tr["id"],),
            )  # noqa: S608
        if row:
            return JSONResponse(
                _json({**row, "audio_ws_url": None, "sample_rate": 16000, "channels": 1}), status_code=201
            )
    raise HTTPException(status_code=500, detail="сессия не создана — см. transcripts.error")


@router.get("/api/compliance/sessions/{id}", summary="Сессия с репликами, триггерами и алертами")
async def get_compliance_sessions_id(request: Request, id: int) -> Any:
    async with db() as conn:
        s = await fetch_one(conn, f"select {SESSION_COLS} {SESSION_FROM} where s.id = %s", (id,))  # noqa: S608
        if not s:
            raise HTTPException(status_code=404, detail="сессия не найдена")
        utt = await fetch_all(
            conn,
            "select id, seq, speaker, speaker_confidence, speaker_source, text, t0_ms, t1_ms, is_final, stt_confidence, latency_ms from utterances where session_id = %s order by seq",
            (id,),
        )
        trig = await fetch_all(
            conn,
            "select ct.id, ct.session_id, ct.utterance_id, ct.pattern_code, mp.name_ru as pattern_name_ru, mp.family, ct.confidence, ct.quote, ct.explanation_ru, ct.detected_by, ct.status, ct.agent_run_id, ct.latency_ms, ct.recommendation_ru, ct.fact_check "
            "from compliance_triggers ct join misselling_patterns mp on mp.code = ct.pattern_code where ct.session_id = %s order by ct.id",
            (id,),
        )
        alerts = await fetch_all(conn, f"select {ALERT_COLS} {ALERT_FROM} where a.session_id = %s order by a.id", (id,))  # noqa: S608
    by_utt = {t["utterance_id"]: t for t in trig if t["status"] == "confirmed"}
    return {
        **s,
        "utterances": [{**u, "trigger": by_utt.get(u["id"])} for u in utt],
        "triggers": trig,
        "alerts": alerts,
        "stt_metrics": {"partial_latency_p50_ms": None, "final_latency_p50_ms": None},
    }


@router.post(
    "/api/compliance/sessions/{id}/role",
    summary="Ручное переключение активной роли (режим manual, пробел на экране)",
    status_code=204,
    response_class=Response,
)
async def post_compliance_sessions_id_role(request: Request, id: int, body: dict[str, Any]) -> None:
    async with db() as conn:
        row = await fetch_one(conn, "select source from audio_sessions where id = %s", (id,))
        if not row:
            raise HTTPException(status_code=404, detail="сессия не найдена")
        if row["source"] == "file":
            set_file_speaker(id, str(body.get("speaker") or "employee"))
            return None
        # для транскриптов роли известны заранее: переключение применяем к последней реплике (ручная правка диаризации)
        await conn.execute(
            "update utterances set speaker = %s, speaker_source = 'manual' where id = (select id from utterances where session_id = %s order by seq desc limit 1)",
            (body.get("speaker") or "employee", id),
        )
    return None


@router.post("/api/compliance/sessions/{id}/stop", summary="Завершить сессию")
async def post_compliance_sessions_id_stop(request: Request, id: int) -> Any:
    async with db() as conn:
        row = await fetch_one(conn, "select id from audio_sessions where id = %s", (id,))
        if not row:
            raise HTTPException(status_code=404, detail="сессия не найдена")
        await conn.execute(
            "update audio_sessions set status = 'closed', finished_at = coalesce(finished_at, now()), updated_at = now() where id = %s",
            (id,),
        )
        updated = await fetch_one(conn, f"select {SESSION_COLS} {SESSION_FROM} where s.id = %s", (id,))  # noqa: S608
    request_stop(id)
    return updated


@router.get(
    "/api/compliance/sessions/{id}/utterances",
    summary="Финальные реплики сессии (для дозагрузки после разрыва WebSocket)",
)
async def get_compliance_sessions_id_utterances(request: Request, id: int, since_seq: int = 0) -> Any:
    async with db() as conn:
        return await fetch_all(
            conn,
            "select id, seq, speaker, speaker_confidence, speaker_source, text, t0_ms, t1_ms, is_final, stt_confidence, latency_ms from utterances where session_id = %s and seq > %s order by seq",
            (id, since_seq),
        )


@router.post(
    "/api/compliance/triggers/{id}", summary="Подтвердить или отклонить триггер вручную (руководитель/комплаенс)"
)
async def post_compliance_triggers_id(request: Request, id: int, body: dict[str, Any]) -> Any:
    status = body.get("status")
    if status not in ("confirmed", "dismissed"):
        raise HTTPException(status_code=422, detail="status: confirmed | dismissed")
    async with db() as conn:
        row = await fetch_one(
            conn,
            "update compliance_triggers set status = %s, updated_at = now() where id = %s returning session_id",
            (status, id),
        )
        if not row:
            raise HTTPException(status_code=404, detail="триггер не найден")
        await conn.execute(
            "update audio_sessions set trigger_count = (select count(*) from compliance_triggers where session_id = %s and status = 'confirmed'), updated_at = now() where id = %s",
            (row["session_id"], row["session_id"]),
        )
        return await fetch_one(
            conn,
            "select ct.id, ct.session_id, ct.utterance_id, ct.pattern_code, mp.name_ru as pattern_name_ru, ct.confidence, ct.quote, ct.explanation_ru, ct.detected_by, ct.status, ct.agent_run_id, ct.latency_ms from compliance_triggers ct join misselling_patterns mp on mp.code = ct.pattern_code where ct.id = %s",
            (id,),
        )


@router.get("/api/compliance/alerts", summary="Лента алертов для устройства руководителя (/manager)")
async def get_compliance_alerts(
    request: Request,
    q: str | None = Query(None, max_length=200),
    run_id: str | None = None,
    branch_code: str | None = None,
    unacknowledged: bool | None = None,
    limit: int = Query(default=50, ge=1, le=500),
) -> Any:
    where: list[str] = ["true"]
    args: list[Any] = []
    async with db() as conn:
        rid = await resolve_run_id(conn, run_id)
        predicate, values = await entity_filter(conn, q, "alert")
        where.append(predicate)
        args.extend(values)
        if rid is not None:
            where.append("s.run_id = %s")
            args.append(rid)
        if branch_code:
            where.append("(b.code = %s or b.code = regexp_replace(%s, '^VSP-', ''))")
            args += [branch_code, branch_code]
        if unacknowledged:
            where.append("a.acknowledged_at is null")
        return await fetch_all(
            conn,
            f"select {ALERT_COLS} {ALERT_FROM} where {' and '.join(where)} order by a.id desc limit %s",
            [*args, limit],
        )  # noqa: S608


@router.post("/api/compliance/alerts/{id}/ack", summary="Решение руководителя по алерту")
async def post_compliance_alerts_id_ack(request: Request, id: int, body: dict[str, Any]) -> Any:
    decision = body.get("decision")
    if decision not in ("go", "false_positive", "open_incident"):
        raise HTTPException(status_code=422, detail="decision: go | false_positive | open_incident")
    by = request.headers.get("x-role") or "branch_manager"
    async with db() as conn, conn.transaction():
        run_id, sim_time = await run_context(request, conn)
        svc = ComplianceService(
            conn,
            run_id=run_id,
            sim_time=sim_time,
            chain=request.app.state.llm_chain,
            profile=request.app.state.llm_chain.profile_for("fast", request.app.state.llm_profile),
        )
        res = await svc.ack_alert(id, decision=decision, by=by, comment=body.get("comment"))
        if not res:
            raise HTTPException(status_code=404, detail="алерт не найден")
        from app.demo.execution import compliance_customer_case, configuration

        if (
            not res.get("deduplicated")
            and res["decision"] in ("go", "open_incident")
            and (await configuration(conn, run_id)).get("enabled")
        ):
            await compliance_customer_case(
                conn,
                request.app,
                run_id,
                id,
                sim_time,
                {"source": "mock", "model": None, "usage": {}, "fallback": False},
            )
        return await fetch_one(conn, f"select {ALERT_COLS} {ALERT_FROM} where a.id = %s", (id,))  # noqa: S608


@router.get("/api/compliance/patterns", summary="Таксономия мисселлинга")
async def get_compliance_patterns(request: Request) -> Any:
    async with db() as conn:
        return await fetch_all(
            conn,
            "select code, name_ru, name_en, family, coalesce(description_ru, '') as description_ru, examples, counter_examples, keywords, weight, is_active, alert_policy, immediate_threshold, recommendation_ru, training_module from misselling_patterns order by family, code",
        )


@router.put("/api/compliance/patterns", summary="Обновить таксономию (включение паттернов, ключевые слова, веса)")
async def put_compliance_patterns(request: Request, body: list[dict[str, Any]]) -> Any:
    async with db() as conn:
        for p in body:
            await conn.execute(
                "update misselling_patterns set is_active = coalesce(%s, is_active), keywords = coalesce(%s, keywords), weight = coalesce(%s, weight), examples = coalesce(%s, examples), counter_examples = coalesce(%s, counter_examples), updated_at = now() where code = %s",
                (
                    p.get("is_active"),
                    p.get("keywords"),
                    p.get("weight"),
                    p.get("examples"),
                    p.get("counter_examples"),
                    p["code"],
                ),
            )
    taxonomy.invalidate()
    return {"updated": len(body)}


@router.get("/api/compliance/stats", summary="Статистика по сотрудникам/отделениям (v_compliance_by_employee)")
async def get_compliance_stats(request: Request, run_id: str | None = None, branch_code: str | None = None) -> Any:
    async with db() as conn:
        rid = await resolve_run_id(conn, run_id)
        where: list[str] = ["true"]
        args: list[Any] = []
        if rid is not None:
            where.append("run_id = %s")
            args.append(rid)
        if branch_code:
            where.append("branch_code = %s")
            args.append(branch_code)
        return await fetch_all(
            conn,
            f"select * from v_compliance_by_employee where {' and '.join(where)} order by triggers_confirmed desc, display_name",
            args,
        )  # noqa: S608


@router.get(
    "/api/compliance/transcripts/{id}/report",
    summary="[ДТЗ FR-4.2–4.3] Отчёт пакетного анализа транскрипта: находки с цитатами, соблюдение скрипта, рекомендации руководителю",
)
async def get_compliance_transcripts_id_report(request: Request, id: int, format: str = "json") -> Any:
    async with db() as conn:
        row = await fetch_one(
            conn,
            "select t.id, t.public_id, t.status, t.report, t.audio_session_id, b.code as branch_code, e.public_id as employee_public_id, e.display_name, t.error from transcripts t left join branches b on b.id = t.branch_id left join employees e on e.id = t.employee_id where t.id = %s",
            (id,),
        )
        if not row:
            raise HTTPException(status_code=404, detail="транскрипт не найден")
        if row["status"] != "done" or not row["report"]:
            return JSONResponse(
                {
                    "type": "about:blank",
                    "title": "Анализ ещё не завершён",
                    "status": 409,
                    "detail": row["error"] or row["status"],
                },
                status_code=409,
                media_type="application/problem+json",
            )
        alerts = (
            await fetch_all(
                conn,
                f"select {ALERT_COLS} {ALERT_FROM} where a.session_id = %s order by a.id",
                (row["audio_session_id"],),
            )
            if row["audio_session_id"]
            else []
        )  # noqa: S608
    report = {
        **row["report"],
        "transcript_id": id,
        "audio_session_id": row["audio_session_id"],
        "employee_public_id": row["employee_public_id"],
        "branch_code": row["branch_code"],
        "alerts": alerts,
    }
    if format == "md":
        return PlainTextResponse(
            report_markdown(report, row["public_id"], row["display_name"]), media_type="text/markdown; charset=utf-8"
        )
    return report


@router.post(
    "/api/compliance/transcripts/{id}/send",
    summary="[ДТЗ FR-4.3] Отправить отчёт руководителю: карточка на /manager, запись в notifications, опционально Telegram",
    status_code=202,
)
async def post_compliance_transcripts_id_send(request: Request, id: int, body: dict[str, Any] | None = None) -> Any:
    body = body or {}
    async with db() as conn:
        row = await fetch_one(
            conn,
            "select t.run_id, t.status, t.report, t.audio_session_id, t.public_id, s.incident_id, e.display_name, b.code from transcripts t left join audio_sessions s on s.id = t.audio_session_id left join employees e on e.id = t.employee_id left join branches b on b.id = t.branch_id where t.id = %s",
            (id,),
        )
        if not row:
            raise HTTPException(status_code=404, detail="транскрипт не найден")
        if row["status"] != "done" or not row["report"]:
            raise HTTPException(status_code=409, detail="анализ ещё не завершён")
        rep = row["report"]
        run_id, sim_time = await run_context(request, conn)
        n = len(rep.get("findings") or [])
        to_role = body.get("to_role") or "branch_manager"
        notif = await fetch_one(
            conn,
            "insert into notifications (run_id, recipient_type, team_code, incident_id, channel_code, template_code, subject, body, status, sent_sim, sent_at) values (%s, 'team', %s, %s, %s, 'compliance_report', %s, %s, 'sent', %s, now()) returning id",
            (
                run_id,
                "team_branch_network" if to_role == "branch_manager" else "team_cx",
                row["incident_id"] if body.get("attach_to_incident") else None,
                "telegram" if body.get("telegram") else "manager_ui",
                f"Отчёт по встрече {row['public_id']}: нарушений {n}",
                f"{rep.get('overall_ru', '')}\n\nПлан действий: {rep.get('action_plan_ru', '')}",
                sim_time,
            ),
        )
        alert_id = None
        if row["audio_session_id"]:
            a = await fetch_one(
                conn,
                "insert into compliance_alerts (session_id, incident_id, sent_at, channels, latency_ms, recommendation_ru, kind, transcript_id) values (%s, %s, now(), %s, 0, %s, 'report', %s) returning id",
                (
                    row["audio_session_id"],
                    row["incident_id"] if body.get("attach_to_incident") else None,
                    ["manager_ui"] + (["telegram"] if body.get("telegram") else []),
                    (rep.get("action_plan_ru") or "")[:500],
                    id,
                ),
            )
            alert_id = a["id"] if a else None
            await conn.execute(
                "select pg_notify('compliance', %s)",
                (
                    dumps(
                        {
                            "type": "compliance.report_sent",
                            "payload": {
                                "transcript_id": id,
                                "alert_id": alert_id,
                                "session_id": row["audio_session_id"],
                                "employee_display_name": row["display_name"],
                                "branch_code": row["code"],
                            },
                        }
                    ),
                ),
            )
    return JSONResponse(
        {"notification_id": notif["id"] if notif else None, "alert_id": alert_id, "incident_id": row["incident_id"]},
        status_code=202,
    )


@router.get(
    "/api/compliance/scripts", summary="Эталонные скрипты обслуживания (service_scripts) для проверки script_violation"
)
async def get_compliance_scripts(request: Request) -> Any:
    async with db() as conn:
        return await fetch_all(
            conn,
            "select code, kind, name_ru, steps, version, is_active from service_scripts order by kind, version desc",
        )


def report_markdown(rep: dict[str, Any], public_id: str, employee: str | None) -> str:
    lines = [
        f"# Отчёт по встрече {public_id}",
        "",
        f"Сотрудник: {employee or '—'} · Отделение: {rep.get('branch_code') or '—'} · Уверенность: {rep.get('confidence', 0):.2f}",
        "",
        rep.get("overall_ru", ""),
        "",
        "## Находки",
    ]
    for f in rep.get("findings") or []:
        fc = f.get("fact_check") or {}
        facts = "; ".join(f"{x.get('claim')} → {x.get('truth')}" for x in (fc.get("facts") or []) if x.get("is_false"))
        lines.append(
            f"- **{f['pattern_code']}** ({f['family']}, {f['confidence']:.2f}), реплика {f['turn_seq']}: «{f['quote']}» — {f['explanation_ru']}"
            + (f" Факты: {facts}." if facts else "")
            + f" Рекомендация: {f['recommendation_ru']}"
        )
    if not rep.get("findings"):
        lines.append("- нарушений не выявлено")
    lines += ["", f"## Скрипт {rep.get('script_compliance', {}).get('script_code', '')}"]
    for st in rep.get("script_compliance", {}).get("steps") or []:
        lines.append(
            f"- {st['code']}: {st['status']}"
            + (f" (реплика {st['evidence_turn_seq']})" if st.get("evidence_turn_seq") else "")
        )
    lines += ["", "## План действий", rep.get("action_plan_ru", ""), ""]
    return "\n".join(lines)


def _json(obj: Any) -> Any:
    from fastapi.encoders import jsonable_encoder

    return jsonable_encoder(obj)
