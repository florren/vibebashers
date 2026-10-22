"""Роутер тега `ingest` (OpenAPI 1.4.0). Заглушки 501 — реализация: карточка T-207."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Request

from app.errors import NotImplementedYet

router = APIRouter(tags=["ingest"])


@router.post(
    "/api/ingest/messages",
    summary="[ДТЗ FR-1.2–1.3] Приём сообщения (или массива) в единой схеме; нормализация, матчинг клиента, создание сигнала",
)
async def post_ingest_messages(request: Request) -> Any:
    raise NotImplementedYet("T-207")


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
