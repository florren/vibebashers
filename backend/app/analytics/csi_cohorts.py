"""T-248: атомарная регистрация только явно синтетического sample через normalizer.

Нет commits, LLM/HTTP и исправления чужих signals. Caller владеет транзакцией;
неизвестный/частичный provenance не превращается в известный denominator.
"""

from __future__ import annotations

import datetime as dt
import hashlib
import json
from typing import Any

import psycopg
from psycopg.pq import TransactionStatus

from app.api.common import fetch_all, fetch_one
from app.ingest.csi import Row, import_rows, validate_row
from app.sim.behavior.runtime import require_run
from app.sim.csi_scoped_corpus import generate_scoped

Conn = psycopg.AsyncConnection[dict[str, Any]]


class CohortRegistrationError(ValueError):
    pass


def digest(value: Any) -> str:
    return hashlib.sha256(
        json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()


def visits_fingerprint(rows: list[dict[str, Any]]) -> str:
    return digest(sorted((r["wait_bucket"], r["redirects_bucket"], r["visits"]) for r in rows))


def members_fingerprint(rows: list[dict[str, Any]]) -> str:
    return digest(
        sorted(
            (
                r["signal_id"],
                r["response_at"].astimezone(dt.UTC).isoformat(timespec="microseconds"),
                r["wait_bucket"],
                r["redirects_bucket"],
            )
            for r in rows
        )
    )


def cohort_status(header: dict[str, Any], visits: list[dict[str, Any]], members: list[dict[str, Any]]) -> str | None:
    """Reader и installer одинаково отличают полный snapshot от утраты данных."""
    if visits_fingerprint(visits) != header["visits_digest"]:
        return "visits_digest_mismatch"
    if len(members) != header["member_count"] or members_fingerprint(members) != header["members_digest"]:
        return "members_digest_mismatch"
    return None


def buckets(payload: dict[str, Any]) -> tuple[str, str]:
    wait = float(payload["wait_min"])
    wait_bucket = next(
        label for boundary, label in [(5, "0-5"), (15, "5-15"), (30, "15-30"), (float("inf"), "30+")] if wait < boundary
    )
    redirects = payload["redirects"]
    return wait_bucket, str(redirects) if redirects < 2 else "2+"


async def _preflight(conn: Conn, corpus: dict[str, Any]) -> tuple[int, dict[str, int]]:
    state = await fetch_one(conn, "SELECT current_run_id,sim_time,running FROM sim_state WHERE id=1 FOR SHARE")
    if not state or not state["current_run_id"] or state["running"]:
        raise CohortRegistrationError("CSI sample требует собственного текущего запуска с остановленными часами")
    run_id = int(state["current_run_id"])
    run = await fetch_one(conn, "SELECT kind,status FROM sim_runs WHERE id=%s FOR SHARE", (run_id,))
    if not run or run["kind"] not in ("free", "scenario", "live") or run["status"] not in ("running", "paused"):
        raise CohortRegistrationError("CSI sample не изменяет baseline или завершённый/неизвестный запуск")
    await require_run(conn, run_id)
    if dt.datetime.fromisoformat(corpus["metadata"]["observation_window"]["end"]) > state["sim_time"]:
        raise CohortRegistrationError("CSI sample observation window ещё не завершено в native SimTime")
    directory = await fetch_one(conn, "SELECT value FROM settings WHERE key='branch_directory'")
    expected_anchor = dt.datetime.fromisoformat(corpus["metadata"]["seed_anchor"])
    if not directory or not isinstance(directory["value"], dict):
        raise CohortRegistrationError("Неизвестное происхождение branch directory")
    origin = directory["value"]
    if (
        origin.get("mode") != "synthetic"
        or origin.get("is_synthetic") is not True
        or origin.get("as_of_sim") != expected_anchor.isoformat()
    ):
        raise CohortRegistrationError("CSI sample требует исходного synthetic directory snapshot")
    expected = {r["branch_code"]: r for r in corpus["directory_snapshot"]}
    branches = await fetch_all(
        conn, "SELECT id,code,product_line_codes FROM branches WHERE code=ANY(%s) FOR SHARE", (list(expected),)
    )
    if len(branches) != len(expected) or any(
        sorted(b["product_line_codes"]) != expected[b["code"]]["product_line_codes"] for b in branches
    ):
        raise CohortRegistrationError("CSI branch direction snapshot не совпадает")
    rows = await fetch_all(
        conn,
        "SELECT b.code,e.desk_no,e.public_id,e.position,e.hired_sim,e.position_since_sim FROM branches b JOIN employees e ON e.branch_id=b.id WHERE b.code=ANY(%s) FOR SHARE OF e",
        (list(expected),),
    )
    staff = {(r["code"], r["desk_no"]): r for r in rows}
    as_of = dt.datetime.fromisoformat(corpus["metadata"]["as_of"])
    for employee in corpus["employees"]:
        actual = staff.get((employee["branch_code"], employee["desk_no"]))
        if (
            not actual
            or actual["public_id"] != employee["employee_public_id"]
            or actual["position"] != employee["position"]
        ):
            raise CohortRegistrationError("CSI fixture roster mismatch")
        if (
            not actual["hired_sim"]
            or not actual["position_since_sim"]
            or (as_of - actual["hired_sim"]).days != employee["tenure_org_days"]
            or (as_of - actual["position_since_sim"]).days != employee["tenure_position_days"]
        ):
            raise CohortRegistrationError("CSI fixture tenure mismatch")
    return run_id, {b["code"]: b["id"] for b in branches}


async def _native_members(conn: Conn, corpus: dict[str, Any], run_id: int) -> dict[str, dict[str, Any]]:
    expected = {r["csi_no"]: validate_row(r) for r in corpus["complaints"]}
    rows = await fetch_all(
        conn,
        "SELECT im.external_id,im.run_id AS ingest_run_id,im.payload->'meta'->'csi_meta' AS payload,s.id,s.run_id,"
        "to_jsonb(cr) AS detail,b.code AS branch_code,e.public_id AS employee_public_id "
        "FROM ingest_messages im JOIN signals s ON s.id=im.signal_id JOIN csi_responses cr ON cr.signal_id=s.id "
        "JOIN branches b ON b.id=cr.branch_id LEFT JOIN employees e ON e.id=cr.employee_id "
        "WHERE im.source_code='csi' AND im.status='accepted' AND im.external_id=ANY(%s) FOR SHARE OF s,cr",
        (list(expected),),
    )
    if len(rows) != len(expected):
        raise CohortRegistrationError("CSI sample имеет неполные native accepted records")
    for row in rows:
        wanted = expected[row["external_id"]]
        if row["run_id"] != run_id or row["ingest_run_id"] != run_id or row["payload"] != wanted:
            raise CohortRegistrationError("CSI sample совпадает с чужим run или иным accepted payload")
        if row["branch_code"] != wanted["branch_code"] or row["employee_public_id"] != wanted["employee_public_id"]:
            raise CohortRegistrationError("CSI sample native branch/employee linkage изменён")
        for key in (
            "csi_no",
            "complaint_ru",
            "ticket_code",
            "waiting_count",
            "serving_count",
            "out_of_order_count",
            "wait_min",
            "service_min",
            "redirects",
            "products",
            "position",
            "tenure_position_days",
            "tenure_org_days",
        ):
            if row["detail"].get(key) != wanted.get(key):
                raise CohortRegistrationError("CSI sample native details не совпадают с принятым corpus")
    return {r["external_id"]: r for r in rows}


async def install_scoped_sample(conn: Conn, *, seed: int = 42, id_base: int = 30000) -> dict[str, Any]:
    if conn.info.transaction_status != TransactionStatus.INTRANS:
        raise CohortRegistrationError("CSI sample требует активной caller transaction")
    corpus = generate_scoped(seed, id_base=id_base)
    metadata = corpus["metadata"]
    fingerprint = digest(corpus)
    directory_digest = digest(corpus["directory_snapshot"])
    async with conn.transaction():
        run_id, branches = await _preflight(conn, corpus)
        await conn.execute("SELECT pg_advisory_xact_lock(hashtext('csi_cohort_import'))")
        old = await fetch_all(
            conn,
            "SELECT * FROM csi_cohorts WHERE run_id=%s AND dataset_code=%s ORDER BY branch_id FOR UPDATE",
            (run_id, metadata["dataset_code"]),
        )
        if old and (
            {r["branch_id"] for r in old} != set(branches.values())
            or any(r["dataset_digest"] != fingerprint or r["directory_digest"] != directory_digest for r in old)
        ):
            raise CohortRegistrationError("CSI cohort snapshot частичный или имеет другой digest; overwrite запрещён")
        report = await import_rows(conn, [Row(i, value, {}) for i, value in enumerate(corpus["complaints"], 1)])
        if report["rejected"]:
            raise CohortRegistrationError("CSI normalizer отклонил sample; весь import откатывается")
        native = await _native_members(conn, corpus, run_id)
        headers = {r["branch_id"]: r for r in old}
        window = metadata["observation_window"]
        for code, branch_id in branches.items():
            members = [r for r in corpus["complaints"] if r["branch_code"] == code]
            visits = [r for r in corpus["visits"] if r["branch_code"] == code]
            member_snapshot = [
                {
                    "signal_id": native[r["csi_no"]]["id"],
                    "response_at": dt.datetime.fromisoformat(r["received_at"]),
                    "wait_bucket": buckets(r)[0],
                    "redirects_bucket": buckets(r)[1],
                }
                for r in members
            ]
            wanted_header = {
                "run_id": run_id,
                "dataset_code": metadata["dataset_code"],
                "dataset_digest": fingerprint,
                "directory_digest": directory_digest,
                "visits_digest": visits_fingerprint(visits),
                "members_digest": members_fingerprint(member_snapshot),
                "branch_id": branch_id,
                "product_line_code": metadata["branch_lines"][code],
                "window_start": dt.datetime.fromisoformat(window["start"]),
                "window_end": dt.datetime.fromisoformat(window["end"]),
                "is_synthetic": True,
                "member_count": len(members),
            }
            header = headers.get(branch_id)
            if header is not None:
                if any(header[key] != value for key, value in wanted_header.items()):
                    raise CohortRegistrationError("CSI cohort header изменён")
                cohort_id = header["id"]
            else:
                result = await fetch_one(
                    conn,
                    "INSERT INTO csi_cohorts(run_id,dataset_code,dataset_digest,directory_digest,visits_digest,members_digest,branch_id,product_line_code,window_start,window_end,is_synthetic,member_count) VALUES(%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s) RETURNING id",
                    list(wanted_header.values()),
                )
                assert result is not None
                cohort_id = result["id"]
                for visit in visits:
                    await conn.execute(
                        "INSERT INTO csi_cohort_visits(cohort_id,run_id,wait_bucket,redirects_bucket,visits) VALUES(%s,%s,%s,%s,%s)",
                        (cohort_id, run_id, visit["wait_bucket"], visit["redirects_bucket"], visit["visits"]),
                    )
                for member in members:
                    wait, redirects = buckets(member)
                    await conn.execute(
                        "INSERT INTO csi_cohort_members(signal_id,cohort_id,run_id,branch_id,response_at,wait_bucket,redirects_bucket) VALUES(%s,%s,%s,%s,%s,%s,%s)",
                        (
                            native[member["csi_no"]]["id"],
                            cohort_id,
                            run_id,
                            branch_id,
                            dt.datetime.fromisoformat(member["received_at"]),
                            wait,
                            redirects,
                        ),
                    )
            actual_visits = await fetch_all(
                conn,
                "SELECT wait_bucket,redirects_bucket,visits FROM csi_cohort_visits WHERE cohort_id=%s",
                (cohort_id,),
            )
            actual_members = await fetch_all(
                conn,
                "SELECT signal_id,response_at,wait_bucket,redirects_bucket FROM csi_cohort_members WHERE cohort_id=%s",
                (cohort_id,),
            )
            status = cohort_status(wanted_header, actual_visits, actual_members)
            if status == "visits_digest_mismatch":
                raise CohortRegistrationError("CSI cohort denominator snapshot изменён")
            if status is not None:
                raise CohortRegistrationError("CSI cohort membership snapshot изменён")
        return {
            "run_id": run_id,
            "dataset_code": metadata["dataset_code"],
            "digest": fingerprint,
            "cohorts": len(branches),
            "members": len(native),
            "visits": sum(r["visits"] for r in corpus["visits"]),
            "accepted": report["accepted"],
            "duplicates": report["duplicates"],
            "status": "existing" if old else "registered",
            "synthetic": True,
        }
