"""Роутер тега `compliance` (OpenAPI 1.4.0). Заглушки 501 — реализация: карточка T-184."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Request

from app.errors import NotImplementedYet

router = APIRouter(tags=["compliance"])


@router.get("/api/compliance/branches", summary="Отделения с сотрудниками (для выбора на экране /compliance)")
async def get_compliance_branches(request: Request) -> Any:
    raise NotImplementedYet("T-184")


@router.get("/api/compliance/sessions", summary="Аудиосессии")
async def get_compliance_sessions(request: Request) -> Any:
    raise NotImplementedYet("T-184")


@router.post("/api/compliance/sessions", summary="Начать сессию (микрофон, файл или транскрипт)")
async def post_compliance_sessions(request: Request) -> Any:
    raise NotImplementedYet("T-184")


@router.get("/api/compliance/sessions/{id}", summary="Сессия с репликами, триггерами и алертами")
async def get_compliance_sessions_id(request: Request) -> Any:
    raise NotImplementedYet("T-184")


@router.post(
    "/api/compliance/sessions/{id}/role", summary="Ручное переключение активной роли (режим manual, пробел на экране)"
)
async def post_compliance_sessions_id_role(request: Request) -> Any:
    raise NotImplementedYet("T-184")


@router.post("/api/compliance/sessions/{id}/stop", summary="Завершить сессию")
async def post_compliance_sessions_id_stop(request: Request) -> Any:
    raise NotImplementedYet("T-184")


@router.get(
    "/api/compliance/sessions/{id}/utterances",
    summary="Финальные реплики сессии (для дозагрузки после разрыва WebSocket)",
)
async def get_compliance_sessions_id_utterances(request: Request) -> Any:
    raise NotImplementedYet("T-184")


@router.post(
    "/api/compliance/triggers/{id}", summary="Подтвердить или отклонить триггер вручную (руководитель/комплаенс)"
)
async def post_compliance_triggers_id(request: Request) -> Any:
    raise NotImplementedYet("T-184")


@router.get("/api/compliance/alerts", summary="Лента алертов для устройства руководителя (/manager)")
async def get_compliance_alerts(request: Request) -> Any:
    raise NotImplementedYet("T-184")


@router.post(
    "/api/compliance/alerts/{id}/ack",
    summary="Реакция руководителя («Иду» / ложное / открыть инцидент) — пишется в HITL инцидента misselling",
)
async def post_compliance_alerts_id_ack(request: Request) -> Any:
    raise NotImplementedYet("T-184")


@router.get("/api/compliance/patterns", summary="Таксономия мисселлинга")
async def get_compliance_patterns(request: Request) -> Any:
    raise NotImplementedYet("T-184")


@router.put("/api/compliance/patterns", summary="Обновить таксономию (включение паттернов, ключевые слова, веса)")
async def put_compliance_patterns(request: Request) -> Any:
    raise NotImplementedYet("T-184")


@router.get("/api/compliance/stats", summary="Статистика по сотрудникам/отделениям (v_compliance_by_employee)")
async def get_compliance_stats(request: Request) -> Any:
    raise NotImplementedYet("T-184")


@router.get(
    "/api/compliance/transcripts/{id}/report",
    summary="[ДТЗ FR-4.2–4.3] Отчёт пакетного анализа транскрипта: находки с цитатами, соблюдение скрипта, рекомендации руководителю",
)
async def get_compliance_transcripts_id_report(request: Request) -> Any:
    raise NotImplementedYet("T-184")


@router.post(
    "/api/compliance/transcripts/{id}/send",
    summary="[ДТЗ FR-4.3] Отправить отчёт руководителю: карточка на /manager, запись в notifications, опционально Telegram",
)
async def post_compliance_transcripts_id_send(request: Request) -> Any:
    raise NotImplementedYet("T-184")


@router.get(
    "/api/compliance/scripts", summary="Эталонные скрипты обслуживания (service_scripts) для проверки script_violation"
)
async def get_compliance_scripts(request: Request) -> Any:
    raise NotImplementedYet("T-184")
