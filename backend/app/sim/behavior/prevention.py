"""Read model отмен: modelled resolution credit, не эффект доставки/денежная экономия."""

from __future__ import annotations

import datetime as dt
from dataclasses import dataclass
from typing import Any

import psycopg

from app.sim.behavior.cancellation import complaint_observation
from app.sim.behavior.cancellation_details import CancellationDetails
from app.sim.behavior.facts import rows
from app.sim.behavior.store import positive_ids


@dataclass(frozen=True)
class PreventionSummary:
    modelled_prevented_by_resolution: int | None
    recorded_eligible_count: int
    unknown_cancelled_work_count: int
    recorded_cancellation_count: int
    pending_primary_count: int
    quality: str


def eligible(details: CancellationDetails) -> bool:
    """Кандидат из logical snapshot; summarize ещё проверяет observation fence."""
    return (
        details.work_kind == "complaint"
        and details.action == "cancelled_by_resolution"
        and details.complaint_observation_complete
        and details.first_complaint_sim_at_cancellation is None
        and details.resolution_sim is not None
        and details.resolution_sim < details.due_sim
    )


async def summarize(conn: psycopg.AsyncConnection[Any], *, run_id: int) -> PreventionSummary:
    """Run-scoped: SQL NULL/неполная provenance сохраняют nullable общий результат."""
    positive_ids(run_id)
    marker = await rows(conn, "select 1 from behavior_runs where run_id=%s", (run_id,))
    work = await rows(
        conn,
        "select w.*,r.action receipt_action,r.consumed_sim receipt_sim,r.details "
        "from behavior_work w left join behavior_receipts r "
        "on r.run_id=w.run_id and r.client_id=w.client_id and r.source_kind='work' and r.source_id=w.id "
        "and r.action in ('cancelled_by_resolution','already_complained') "
        "where w.run_id=%s and w.status='cancelled' order by w.id,r.action",
        (run_id,),
    )
    unknown = count = recorded = 0
    seen: set[int] = set()
    for timer in work:
        if timer["id"] in seen:
            # Несогласованные две причины одного work не дают два credit.
            raise ValueError("work имеет несколько cancellation причин; требуется проверка истории")
        seen.add(timer["id"])
        try:
            details = CancellationDetails.from_json(timer["details"])
        except ValueError:
            unknown += 1
            continue
        evidence = await rows(
            conn,
            "select 1 from behavior_evidence where id=%s and run_id=%s and client_id=%s "
            "and source_kind=%s and source_id=%s",
            (details.evidence_id, run_id, timer["client_id"], details.evidence_kind, details.evidence_source_id),
        )
        if (
            not evidence
            or details.episode_no != timer["episode_no"]
            or details.work_kind != timer["kind"]
            or details.due_sim != timer["due_sim"]
            or details.action != timer["receipt_action"]
            or details.cancellation_sim != timer["consumed_sim"]
            or details.cancellation_sim != timer["receipt_sim"]
        ):
            unknown += 1
            continue
        recorded += 1
        if (
            details.action == "cancelled_by_resolution"
            and details.work_kind == "complaint"
            and (not details.complaint_observation_complete or details.resolution_sim is None)
        ):
            unknown += 1
        elif eligible(details):
            # Snapshot receipt не отменяет позже поступившие native факты.
            # История ограничена конкретным episode/cause; старые/foreign сигналы
            # без этой связи не считаются новой жалобой этого таймера.
            first, complete = await complaint_observation(
                conn,
                {
                    "run_id": run_id,
                    "client_id": timer["client_id"],
                    "episode_no": timer["episode_no"],
                    "opened_sim": dt.datetime.min.replace(tzinfo=dt.UTC),
                    "first_complaint_sim": details.first_complaint_sim_at_cancellation,
                },
                details.cancellation_observed_sim,
            )
            if not complete:
                unknown += 1
            elif first is None:
                count += 1
    pending = await rows(
        conn,
        "select count(*) n from behavior_work where run_id=%s and kind='complaint' and status='pending'",
        (run_id,),
    )
    quality = "no_behavior_marker" if not marker else "incomplete" if unknown else "complete"
    return PreventionSummary(
        count if quality == "complete" else None, count, unknown, recorded, int(pending[0]["n"]), quality
    )
