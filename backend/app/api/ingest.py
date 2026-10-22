"""Роутер тега `ingest` (OpenAPI 1.4.0). Реализовано: POST /api/ingest/messages (B04), транскрипты (B07/T-208). Адаптеры источников — T-207."""

from __future__ import annotations

import asyncio
import json
from pathlib import Path
from typing import Any

from fastapi import APIRouter, HTTPException, Query, Request, UploadFile
from fastapi.encoders import jsonable_encoder
from fastapi.responses import JSONResponse

from app.api._compliance_support import analyze_in_background, run_context
from app.api.common import db, fetch_all, fetch_one, resolve_run_id
from app.compliance.transcripts import create_transcript, load_file
from app.compliance.txt_parser import TranscriptParseError, parse_txt
from app.errors import NotImplementedYet
from app.ingest.normalizer import IngestError, create_signal
from app.logging import get_logger

log = get_logger(__name__)

router = APIRouter(tags=["ingest"])


@router.post(
    "/api/ingest/messages",
    summary="[ДТЗ FR-1.2–1.3] Приём сообщения (или массива) в единой схеме; нормализация, матчинг клиента, создание сигнала",
)
async def post_ingest_messages(request: Request, body: dict[str, Any] | list[dict[str, Any]]) -> Any:
    """Единая точка входа внешних источников: UnifiedMessage или массив (≤ 500); идемпотентность по (source_code, external_id)."""
    items = body if isinstance(body, list) else [body]
    if len(items) > 500:
        raise HTTPException(status_code=422, detail="не больше 500 сообщений за запрос")
    source = request.headers.get("x-source-code") or "api"
    results = []
    async with db() as conn:
        for msg in items:
            try:
                results.append(await create_signal(conn, dict(msg), source_code=source))
            except IngestError as exc:
                results.append(
                    {"external_id": msg.get("external_id"), "status": "rejected", "signal_id": None, "error": str(exc)}
                )
    return JSONResponse({"items": jsonable_encoder(results)}, status_code=202)


TRANSCRIPT_COLS = (
    "t.id, t.public_id, t.kind, t.source, t.format, t.filename, b.code as branch_code, e.public_id as employee_public_id, t.client_id, "
    "t.turns_count, t.analyses, t.status, t.signal_id, t.audio_session_id, "
    "coalesce(jsonb_array_length(t.report->'findings'), 0) as findings_count, t.received_at, t.analyzed_at, t.error, t.deal_product, t.started_at, t.geo"
)
TRANSCRIPT_FROM = (
    "from transcripts t left join branches b on b.id = t.branch_id left join employees e on e.id = t.employee_id"
)
IMPORT_DIR = Path(__file__).resolve().parents[3] / "data" / "import" / "transcripts"


@router.get("/api/ingest/transcripts", summary="[ДТЗ FR-1.1] Список импортированных транскриптов")
async def get_ingest_transcripts(
    request: Request,
    run_id: str | None = None,
    kind: str | None = None,
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
            where.append("t.run_id = %s")
            args.append(rid)
        for col, val in (("t.kind", kind), ("t.status", status), ("t.employee_id", employee_id)):
            if val is not None:
                where.append(f"{col} = %s")
                args.append(val)
        if cursor and cursor.isdigit():
            where.append("t.id < %s")
            args.append(int(cursor))
        rows = await fetch_all(
            conn,
            f"select {TRANSCRIPT_COLS} {TRANSCRIPT_FROM} where {' and '.join(where)} order by t.id desc limit %s",  # noqa: S608
            [*args, limit + 1],
        )
    items = rows[:limit]
    return {"items": items, "next_cursor": str(items[-1]["id"]) if len(rows) > limit else None}


async def _accept_docs(
    request: Request,
    docs: list[tuple[dict[str, Any], str, str | None]],
    *,
    source: str,
    analyses: list[str] | None,
    pacing_delay_s: float = 0.0,
) -> list[dict[str, Any]]:
    out = []
    async with db() as conn:
        run_id, sim_time = await run_context(request, conn)
        for doc, fmt, filename in docs:
            if analyses:
                doc["analyses"] = analyses
            try:
                out.append(
                    await create_transcript(
                        conn, doc, run_id=run_id, sim_time=sim_time, source=source, fmt=fmt, filename=filename
                    )
                )
            except (ValueError, TranscriptParseError) as exc:
                out.append({"filename": filename, "status": "failed", "error": str(exc)[:300]})
    for t in out:
        if t.get("id"):
            asyncio.create_task(analyze_in_background(request, int(t["id"]), pacing_delay_s=pacing_delay_s))
    return out


@router.post(
    "/api/ingest/transcripts",
    summary="[ДТЗ FR-1.1, FR-4.1] Приём транскрипта: JSON по схеме ingest/transcript или multipart с файлами JSON/TXT; запускает анализы client_signal и/или employee_quality",
)
async def post_ingest_transcripts(request: Request, analyses: str | None = None) -> Any:
    wanted = [a for a in (analyses or "").split(",") if a] or None
    ctype = request.headers.get("content-type", "")
    docs: list[tuple[dict[str, Any], str, str | None]] = []
    if ctype.startswith("multipart/form-data"):
        form = await request.form()
        for key in ("files", "file"):
            for up in form.getlist(key):
                if not isinstance(up, UploadFile):
                    continue
                raw = (await up.read()).decode("utf-8", errors="replace")
                name = up.filename or "upload"
                if name.lower().endswith(".json"):
                    doc = json.loads(raw)
                    docs.append((doc.get("transcript", doc) if isinstance(doc, dict) else doc, "json", name))
                else:
                    try:
                        docs.append(
                            (
                                parse_txt(
                                    raw,
                                    defaults={
                                        "kind": form.get("kind") or "branch_retail",
                                        "branch_code": form.get("branch_code"),
                                    },
                                ),
                                "txt",
                                name,
                            )
                        )
                    except TranscriptParseError as exc:
                        raise HTTPException(status_code=422, detail=f"{name}: {exc}") from exc
        if not docs:
            raise HTTPException(status_code=422, detail="нет файлов в поле files")
    else:
        body = await request.json()
        for d in body if isinstance(body, list) else [body]:
            docs.append((dict(d), "json", None))
    items = await _accept_docs(
        request, docs, source="file" if ctype.startswith("multipart") else "api", analyses=wanted
    )
    return JSONResponse({"items": jsonable_encoder(items)}, status_code=202)


@router.post(
    "/api/ingest/transcripts/import",
    summary="[ДТЗ FR-1.1] Пакетный импорт каталога data/import/transcripts/ (кнопка в настройках)",
)
async def post_ingest_transcripts_import(request: Request) -> Any:
    files = (
        sorted([p for p in IMPORT_DIR.glob("*") if p.suffix.lower() in (".json", ".txt")])
        if IMPORT_DIR.exists()
        else []
    )
    docs: list[tuple[dict[str, Any], str, str | None]] = []
    rejected = 0
    async with db() as conn:
        known = {
            r["filename"]
            for r in await fetch_all(
                conn, "select filename from transcripts where source = 'import' and filename is not null"
            )
        }
    duplicates = 0
    for p in files:
        if p.name in known:
            duplicates += 1
            continue
        try:
            doc, fmt = load_file(p)
            docs.append((doc, fmt, p.name))
        except (ValueError, TranscriptParseError) as exc:
            rejected += 1
            log.warning("transcript_import_rejected", file=p.name, error=str(exc)[:200])
    items = await _accept_docs(request, docs, source="import", analyses=None)
    accepted = sum(1 for i in items if i.get("id"))
    rejected += sum(1 for i in items if not i.get("id"))
    return JSONResponse(
        {"files_found": len(files), "accepted": accepted, "duplicates": duplicates, "rejected": rejected},
        status_code=202,
    )


@router.get(
    "/api/ingest/transcripts/{id}",
    summary="Транскрипт целиком: реплики, статус анализов, ссылки на сигнал и пакетную сессию, отчёт",
)
async def get_ingest_transcripts_id(request: Request, id: int) -> Any:
    async with db() as conn:
        row = await fetch_one(
            conn, f"select {TRANSCRIPT_COLS}, t.turns, t.report {TRANSCRIPT_FROM} where t.id = %s", (id,)
        )  # noqa: S608
        if not row:
            raise HTTPException(status_code=404, detail="транскрипт не найден")
        trig = (
            await fetch_all(
                conn,
                "select u.seq, ct.pattern_code, mp.family, ct.confidence, ct.status from compliance_triggers ct join utterances u on u.id = ct.utterance_id join misselling_patterns mp on mp.code = ct.pattern_code where u.session_id = %s",
                (row["audio_session_id"],),
            )
            if row["audio_session_id"]
            else []
        )
        signal = (
            await fetch_one(
                conn,
                "select id, public_id, status, classification, decision, text from signals where id = %s",
                (row["signal_id"],),
            )
            if row["signal_id"]
            else None
        )
    by_seq: dict[int, list[dict[str, Any]]] = {}
    for t in trig:
        if t["status"] == "confirmed":
            by_seq.setdefault(int(t["seq"]), []).append(
                {"pattern_code": t["pattern_code"], "family": t["family"], "confidence": float(t["confidence"])}
            )
    turns = [{**t, "findings": by_seq.get(int(t.get("seq") or 0), [])} for t in (row.pop("turns") or [])]
    return {**row, "turns": turns, "signal": signal}


@router.post(
    "/api/ingest/transcripts/{id}/analyze",
    summary="Повторить/дозапустить анализ транскрипта (например, employee_quality для контакт-центра)",
)
async def post_ingest_transcripts_id_analyze(request: Request, id: int, body: dict[str, Any] | None = None) -> Any:
    async with db() as conn:
        row = await fetch_one(conn, "select id, status from transcripts where id = %s", (id,))
        if not row:
            raise HTTPException(status_code=404, detail="транскрипт не найден")
        if body and body.get("analyses"):
            await conn.execute("update transcripts set analyses = %s where id = %s", (list(body["analyses"]), id))
    asyncio.create_task(analyze_in_background(request, id))
    return JSONResponse({"id": id, "status": "analyzing"}, status_code=202)


@router.get("/api/ingest/sources", summary="[ДТЗ FR-1.2] Адаптеры источников (REST / polling / file) и их статистика")
async def get_ingest_sources(request: Request) -> Any:
    raise NotImplementedYet("T-207")


@router.put("/api/ingest/sources/{code}", summary="Создать/обновить адаптер (enabled, interval_s, config.url)")
async def put_ingest_sources_code(request: Request) -> Any:
    raise NotImplementedYet("T-207")


@router.post(
    "/api/ingest/sources/{code}/poll", summary="Внеочередной опрос polling-адаптера (кнопка «Опросить сейчас»)"
)
async def post_ingest_sources_code_poll(request: Request) -> Any:
    raise NotImplementedYet("T-207")
