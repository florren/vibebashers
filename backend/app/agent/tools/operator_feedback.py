"""T-268: применяем только новый план работы, без старого act/refund/gift."""

from __future__ import annotations

from typing import Any

from app.agent.tools.base import ToolContext, tool
from app.sim.events import dumps


@tool("apply_operator_feedback")
async def apply_operator_feedback(
    ctx: ToolContext, feedback_id: int, incident_ids: list[int], review: dict[str, Any], signal_id: int | None = None
) -> dict[str, Any]:
    applied = []
    if not incident_ids:
        await ctx.conn.execute(
            "insert into tasks(run_id,kind,payload,created_sim) values (%s,'manual_review',%s::jsonb,%s)",
            (ctx.run_id, dumps({"feedback_id": feedback_id, "signal_id": signal_id, **review}), ctx.sim_time),
        )
    for iid in incident_ids:
        row = await ctx.fetchone(
            "select status,priority,team_code from incidents where id=%s and run_id=%s for update", (iid, ctx.run_id)
        )
        if not row:
            continue
        status, priority, team = row
        terminal = status in ("closed", "resolved", "rejected", "duplicate")
        if not terminal:
            await ctx.conn.execute(
                "update incidents set priority=%s where id=%s", (min(int(priority), int(review["priority"])), iid)
            )
        # Новые сведения требуют адресного дальнейшего шага, а не переисполнения старого решения.
        task_kind = (
            "closure_review"
            if terminal
            else ("clarify_client" if review["next_step"] == "request_clarification" else "manual_review")
        )
        task_id = None
        if terminal or review["next_step"] != "continue_monitoring":
            inserted = await (
                await ctx.conn.execute(
                    "insert into tasks(run_id,kind,incident_id,assignee,payload,created_sim) values (%s,%s,%s,%s,%s::jsonb,%s) returning id",
                    (
                        ctx.run_id,
                        task_kind,
                        iid,
                        team,
                        dumps(
                            {
                                "feedback_id": feedback_id,
                                "summary_ru": review["summary_ru"],
                                "agent_run_id": ctx.agent_run_id,
                            }
                        ),
                        ctx.sim_time,
                    ),
                )
            ).fetchone()
            if inserted is None:
                raise RuntimeError("Не удалось создать задачу разбора")
            task_id = inserted[0]
        await ctx.conn.execute(
            "insert into incident_artifacts(run_id,incident_id,kind,title,body_md,meta,author_team,generated_by,published_sim) values (%s,%s,'progress_report','Новые сведения оператора',%s,%s::jsonb,%s,'llm',%s)",
            (
                ctx.run_id,
                iid,
                review["summary_ru"],
                dumps(
                    {
                        "operator_feedback_id": feedback_id,
                        "agent_run_id": ctx.agent_run_id,
                        **review,
                        "task_id": task_id,
                    }
                ),
                team,
                ctx.sim_time,
            ),
        )
        applied.append({"incident_id": iid, "task_id": task_id, "terminal_preserved": terminal})
        await ctx.notify("incidents", "operator_update", {"incident_id": iid, "feedback_id": feedback_id})
    return {"incidents": applied, "feedback_id": feedback_id}
