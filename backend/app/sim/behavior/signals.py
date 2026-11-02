"""Already-complained evidence только от canonical classifier, не gold/intent."""

from __future__ import annotations

from typing import Any

import psycopg
from psycopg.rows import dict_row

from app.agent.tools.base import ClientStateIntent, ToolContext
from app.contracts.registry import validate
from app.economics.calibration import PIPELINE


async def canonical(conn: psycopg.AsyncConnection[Any], run: int, client: int, signal: int) -> dict[str, Any] | None:
    async with conn.cursor(row_factory=dict_row) as cur:
        await cur.execute(
            "select s.*,st.node canonical_node,st.output canonical_output from signals s "
            "join agent_runs a on a.signal_id=s.id and a.sim_run_id=s.run_id and a.kind='agent' "
            "join agent_steps st on st.run_id=a.id and st.node in ('classify','instant_decide') and st.status in ('ok','fallback') "
            "where s.id=%s and s.run_id=%s and s.client_id=%s and s.origin<>'proactive' order by st.id desc limit 1",
            (signal, run, client),
        )
        row = await cur.fetchone()
    if row is None:
        return None
    classification = row["classification"]
    output = row["canonical_output"]
    if not isinstance(classification, dict) or validate(classification, "agent/classification"):
        return None
    if not isinstance(output, dict) or output.get("score_pipeline") != PIPELINE:
        return None
    if row["canonical_node"] == "classify":
        if any(output.get(key) != classification.get(key) for key in classification):
            return None
    elif output.get("classification_snapshot") != classification:
        return None
    flags = classification.get("flags") or []
    if classification.get("sentiment") != "negative" and not ({"churn_intent", "repeat"} & set(flags)):
        return None
    return row


async def record_classified(ctx: ToolContext, signal_id: int) -> None:
    """Вызывается после record_step внутри той же checkpoint transaction."""
    sink = getattr(ctx, "state_evidence_sink", None)
    if getattr(ctx, "dry_run", False) or sink is None:
        return
    async with ctx.conn.cursor(row_factory=dict_row) as cur:
        await cur.execute("select client_id from signals where id=%s and run_id=%s", (signal_id, ctx.run_id))
        row = await cur.fetchone()
    if (
        row is None
        or row["client_id"] is None
        or await canonical(ctx.conn, ctx.run_id, row["client_id"], signal_id) is None
    ):
        return
    await sink(
        ctx.conn,
        ClientStateIntent(
            ctx.run_id,
            ctx.agent_run_id,
            row["client_id"],
            "complaining",
            "classifier:complaint",
            ctx.sim_time,
            signal_id,
            None,
        ),
    )
