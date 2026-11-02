"""T-229: проверка трёх записанных путей; никаких запусков агента или записей."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any
from urllib.parse import quote

import httpx
import psycopg
from scripts.read_model_check import safe_text

from app.contracts.registry import validate
from app.trace.journey import STAGES
from app.trace.privacy import mask

SOURCES = {
    "qr_fee_public_review": "autonomous",
    "deposit_promo_rate": "human",
    "social_sarcasm_escalation": "escalation",
}


@dataclass(frozen=True)
class RecordedPath:
    source: str
    trajectory: str
    ref: str
    run_id: int
    clarification_recorded: bool = False


async def recorded_paths(conn: Any, scenario: dict[str, Any]) -> tuple[list[RecordedPath], list[str]]:
    paths, missing = [], []
    declared = {item.get("source"): item.get("trajectory") for item in scenario.get("paths", [])}
    if declared != SOURCES or len(scenario.get("paths", [])) != len(SOURCES):
        return [], ["manifest:paths"]
    for source, trajectory in SOURCES.items():
        # Только настоящее происхождение scenario; seed classification не заменяет graph.
        row = await (
            await conn.execute(
                "SELECT s.public_id,r.id,"
                "EXISTS(SELECT 1 FROM agent_runs a JOIN agent_steps st ON st.run_id=a.id "
                "WHERE a.signal_id=s.id AND st.node='decide' AND st.status='ok' "
                "AND st.output->'client_action'->>'kind'='request_data') "
                "AND (EXISTS(SELECT 1 FROM notifications n WHERE n.signal_id=s.id "
                "AND n.run_id=r.id AND n.recipient_type='client' AND n.template_code='clarify_request' "
                "AND n.status IN ('sent','delivered') AND n.sent_at IS NOT NULL) "
                "OR EXISTS(SELECT 1 FROM external_replies e WHERE e.post_id=s.external_post_id "
                "AND e.run_id=r.id AND e.author IN ('agent','human') AND e.published_at IS NOT NULL)) "
                "FROM sim_runs r JOIN signals s ON s.run_id=r.id "
                "WHERE r.kind='scenario' AND r.scenario_id=%s "
                "AND EXISTS(SELECT 1 FROM agent_runs a WHERE a.signal_id=s.id) "
                "ORDER BY r.id DESC,s.id LIMIT 1",
                (source,),
            )
        ).fetchone()
        if row is None:
            missing.append(f"{trajectory}:recording")
        else:
            paths.append(RecordedPath(source, trajectory, row[0], int(row[1]), bool(row[2])))
    return paths, missing


def path_errors(payload: Any, case: RecordedPath, *, expected_source: str = "replay") -> list[str]:
    if validate(payload, "trace/journey"):
        return ["dto"]
    if payload["subject"]["kind"] != "signal" or payload["subject"]["ref"] != case.ref:
        return ["subject"]
    errors = []
    if tuple(stage["stage"] for stage in payload["stages"]) != STAGES:
        errors.append("stages")
    if not safe_text(payload) or any(
        mask(m["text_ru"], len(m["text_ru"]) + 1) != m["text_ru"] for m in payload["client_lane"]
    ):
        errors.append("contacts")
    if payload["summary"]["llm_source"] != expected_source:
        errors.append("llm_source")
    stages = {stage["stage"]: stage for stage in payload["stages"]}
    lane = payload["client_lane"]
    if case.trajectory == "autonomous":
        if not any(event["kind"] == "refund" for stage in stages.values() for event in stage["events"]):
            errors.append("refund")
        if not any(message["kind"] == "public_reply" for message in lane):
            errors.append("public_reply")
        if not any(message["channel_code"] not in {"social_reply", "client_reaction"} for message in lane):
            errors.append("private_notification")
    elif case.trajectory == "human":
        if stages.get("decision", {}).get("status") != "waiting_human":
            errors.append("waiting_human")
        if lane:
            errors.append("premature_client_message")
    elif case.trajectory == "escalation":
        kinds = {event["kind"] for stage in stages.values() for event in stage["events"]}
        if "escalation" not in kinds:
            errors.append("escalation")
        # Социальный уточняющий ответ имеет kind=public_reply, цель подтверждается
        # сохранённым decide и фактом публикации, а не придумывается по тексту.
        if not ((case.clarification_recorded and lane) or any(message["kind"] == "clarification" for message in lane)):
            errors.append("clarification")
    return errors


async def check_path(http: httpx.AsyncClient, case: RecordedPath, *, expected_source: str = "replay") -> list[str]:
    try:
        response = await http.get(
            f"/api/journey/{quote(case.ref, safe='')}", params={"run_id": str(case.run_id), "presenter": "true"}
        )
        if response.status_code != 200:
            return ["http"]
        payload = response.json()
    except httpx.HTTPError:
        return ["network"]
    except ValueError:
        return ["json"]
    return path_errors(payload, case, expected_source=expected_source)


async def run_journeys(base: str, dsn: str, scenario: dict[str, Any]) -> bool:
    expected_source = scenario.get("_recording_source", "replay")
    if expected_source not in {"replay", "live"}:
        return False
    async with await psycopg.AsyncConnection.connect(dsn) as conn:
        await conn.execute("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ, READ ONLY")
        await conn.execute("SET LOCAL statement_timeout='3000ms'")
        paths, failed = await recorded_paths(conn, scenario)
    async with httpx.AsyncClient(base_url=base, timeout=10) as http:
        for case in paths:
            failed.extend(
                f"{case.trajectory}:{error}" for error in await check_path(http, case, expected_source=expected_source)
            )
    # Только фиксированные коды: без текста клиента, контактов и URL capability.
    print(  # noqa: T201
        f"  [{scenario['number']:>2}] {'FAIL' if failed else 'OK'} {scenario['title_ru']}: "
        f"{len(paths)} записанных траекторий ({expected_source}); ошибки: {', '.join(failed) or 'нет'}"
    )
    return not failed
