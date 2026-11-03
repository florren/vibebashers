"""Плановое событие и момент наблюдения сохранённой экономики — разные часы."""

from typing import Any

from app.agent import proactive
from app.agent.tools.base import ToolContext
from app.economics import dcltv


async def observe_incident_economics(ctx: ToolContext, incident_id: int) -> dict[str, Any] | None:
    at = max(ctx.sim_time, ctx.economics_time) if ctx.economics_time is not None else ctx.sim_time
    native_time = await proactive.refresh_service_impacts(ctx.conn, ctx.run_id, at, incident_id=incident_id)
    if native_time is not None:
        ctx.economics_time = native_time
        at = native_time
    return await dcltv.compute_incident(ctx.conn, incident_id, sim_time=at)
