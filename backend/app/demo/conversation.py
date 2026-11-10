"""Диалог только своего Journey-case или собственной personal-сессии."""

from __future__ import annotations

from typing import Any

from psycopg.rows import dict_row


async def messages(conn: Any, signal_id: int, run_id: int, *, before: bool = False) -> list[dict[str, Any]]:
    """Один Journey run — один case; personal использует явную membership сессии."""
    async with conn.cursor(row_factory=dict_row) as cur:
        await cur.execute(
            "with anchor as (select a.*,r.settings_snapshot->>'created_by' as owner,"
            "(select session_id from personal_chat_messages where signal_id=a.id) as session_id "
            "from signals a join sim_runs r on r.id=a.run_id where a.id=%s and a.run_id=%s) "
            "select s.*,coalesce((select jsonb_agg(n.body order by n.sent_at,n.id) from notifications n "
            "where n.signal_id=s.id and n.run_id=s.run_id and n.client_id is not distinct from s.client_id "
            "and n.recipient_type='client' and n.status in ('sent','delivered') and n.sent_at is not null),"
            "'[]'::jsonb) as client_answers "
            "from signals s,anchor a where s.run_id=a.run_id and s.client_id is not distinct from a.client_id "
            "and (not %s or s.id<a.id) and ("
            "(a.session_id is not null and exists(select 1 from personal_chat_messages m "
            "where m.signal_id=s.id and m.session_id=a.session_id)) or "
            "(a.owner='journey_demo' and a.origin='jury' and s.origin='jury' and exists("
            "select 1 from ingest_messages im where im.signal_id=s.id and im.source_code='journey' "
            "and im.status='accepted'))) order by s.id desc limit 200",
            (signal_id, run_id, before),
        )
        return list(reversed(await cur.fetchall()))


async def incident(conn: Any, signals: list[dict[str, Any]]) -> dict[str, Any] | None:
    """Исходный инцидент Journey или последняя обсуждаемая проблема personal."""
    if not signals:
        return None
    personal = signals[-1].get("channel_subtype") == "ui_pers_demo"
    root = (
        signals[-1]
        if personal
        else next((signal for signal in signals if signal.get("parent_signal_id") is None), None)
    )
    if root is None:
        return None
    async with conn.cursor(row_factory=dict_row) as cur:
        await cur.execute(
            "select i.id as incident_id,i.public_id,i.title,i.incident_type,i.product_code as product,"
            "i.system_code as system,i.error_code,i.team_code as team,i.priority,i.co_team_codes as co_teams,i.status,i.mass_impact,i.created_sim,"
            "true as is_clients,false as same_error,"
            "case when original.decision#>>'{route,team}'=i.team_code then original.decision#>'{route,rule_id}' end as route_rule_id "
            "from incidents i join incident_signals x on x.incident_id=i.id "
            "left join agent_runs a on a.id=i.agent_run_id left join signals original on original.id=a.signal_id "
            "where x.signal_id=any(%s) and i.run_id=%s order by x.signal_id desc,(x.link_type='primary') desc,i.id limit 1",
            ([signal["id"] for signal in signals] if personal else [root["id"]], root["run_id"]),
        )
        row = await cur.fetchone()
        return dict(row) if row is not None else None
