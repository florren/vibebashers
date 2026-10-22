"""Роутер тега `ingest` (OpenAPI 1.4.0). Реализовано (B04/T-207): POST /api/ingest/messages. Транскрипты и адаптеры — T-207/T-208."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException, Request
from fastapi.encoders import jsonable_encoder
from fastapi.responses import JSONResponse

from app.api.common import db
from app.errors import NotImplementedYet
from app.ingest.normalizer import IngestError, create_signal

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


@router.get("/api/ingest/transcripts", summary="[ДТЗ FR-1.1] Список импортированных транскриптов")
async def get_ingest_transcripts(request: Request) -> Any:
    raise NotImplementedYet("T-207")


@router.post(
    "/api/ingest/transcripts",
    summary="[ДТЗ FR-1.1, FR-4.1] Приём транскрипта: JSON по схеме ingest/transcript или multipart с файлами JSON/TXT; запускает анализы client_signal и/или employee_quality",
)
async def post_ingest_transcripts(request: Request) -> Any:
    raise NotImplementedYet("T-207")


@router.post(
    "/api/ingest/transcripts/import",
    summary="[ДТЗ FR-1.1] Пакетный импорт каталога data/import/transcripts/ (кнопка в настройках)",
)
async def post_ingest_transcripts_import(request: Request) -> Any:
    raise NotImplementedYet("T-207")


@router.get(
    "/api/ingest/transcripts/{id}",
    summary="Транскрипт целиком: реплики, статус анализов, ссылки на сигнал и пакетную сессию, отчёт",
)
async def get_ingest_transcripts_id(request: Request) -> Any:
    raise NotImplementedYet("T-207")


@router.post(
    "/api/ingest/transcripts/{id}/analyze",
    summary="Повторить/дозапустить анализ транскрипта (например, employee_quality для контакт-центра)",
)
async def post_ingest_transcripts_id_analyze(request: Request) -> Any:
    raise NotImplementedYet("T-207")


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
