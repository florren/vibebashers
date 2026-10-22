"""GET /api/health — готовность: БД, мастер настройки, LLM-профили, бот, симуляция (OpenAPI 1.4.0, тег health)."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app import __version__
from app.config import get_settings
from app.db.session import get_session
from app.logging import get_logger

router = APIRouter(tags=["health"])
log = get_logger(__name__)


@router.get("/api/health", summary="Проверка готовности (db, llm, tgbot, sim)")
async def get_health(session: AsyncSession = Depends(get_session)) -> dict[str, Any]:
    s = get_settings()
    db_ok, setup_completed, sim_running = False, False, False
    llm: dict[str, str] = {}
    try:
        await session.execute(text("select 1"))
        db_ok = True
        row = (
            await session.execute(text("select value from settings where key = 'setup_completed'"))
        ).scalar_one_or_none()
        setup_completed = bool(row in (True, "true", {"value": True}))
        st = (await session.execute(text("select is_running from sim_state limit 1"))).scalar_one_or_none()
        sim_running = bool(st)
        profiles = (await session.execute(text("select name, provider, is_enabled from llm_profiles"))).all()
        llm = {p.name: ("ok" if p.is_enabled else "disabled") for p in profiles}
    except Exception as exc:  # БД ещё не мигрирована — health всё равно отвечает
        log.warning("health_db", error=str(exc)[:200])
    if not llm:
        llm = {s.llm_provider: "ok"}
    return {
        "status": "ok" if db_ok else "degraded",
        "db": db_ok,
        "setup_completed": setup_completed,
        "llm": llm,
        "tgbot": "disabled" if not s.telegram_bot_token else "running",
        "sim_running": sim_running,
        "version": __version__,
    }
