"""T-021: явный plan/apply upgrade логического набора с сохранением старых ID/результатов."""

from __future__ import annotations

import hashlib
import json
from typing import Any

from app.bench.datasets import load_rows

from scripts.seed.bench import seed_dataset, source_metadata

FAMILIES = ("golden_v1", "lite_v1")


def digest(value: Any) -> str:
    return hashlib.sha256(
        json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()


def stored_cases(cur: Any, dataset_id: int) -> list[tuple[Any, ...]]:
    cur.execute(
        "select channel_code,segment_code,text,gold,tags from bench_cases where dataset_id=%s order by id",
        (dataset_id,),
    )
    return cur.fetchall()


def source_cases(code: str) -> list[tuple[Any, ...]]:
    return [
        (
            row["channel"],
            row.get("segment"),
            row["text"],
            row["gold"],
            [*row.get("tags", []), f"dataset-case:{row['id']}"],
        )
        for row in load_rows(code)
    ]


def build_plan(cur: Any, *, lock: bool = False) -> dict[str, Any]:
    entries = []
    for family in FAMILIES:
        metadata = source_metadata(family)
        query = "select id,description from bench_datasets where code=%s" + (" for update" if lock else "")
        cur.execute(query, (family,))
        existing = cur.fetchone()
        entry: dict[str, Any] = {
            "family": family,
            "target": metadata,
            "existing_id": None,
            "action": "create",
            "archive_code": None,
            "blocked": [],
            "cases": 0,
            "runs": 0,
            "results": 0,
        }
        if existing:
            dataset_id, description = existing
            previous = stored_cases(cur, dataset_id)
            old_hash = digest(previous)
            entry.update(
                existing_id=dataset_id,
                existing_content_sha256=old_hash,
                description_sha256=digest(description),
                cases=len(previous),
            )
            cur.execute(
                "select count(*),count(*) filter(where status in ('queued','running')) from bench_runs where dataset_id=%s",
                (dataset_id,),
            )
            runs, active = cur.fetchone()
            cur.execute(
                "select count(*) from bench_results r join bench_runs b on b.id=r.run_id where b.dataset_id=%s",
                (dataset_id,),
            )
            entry.update(runs=runs, results=cur.fetchone()[0])
            try:
                old_metadata = json.loads(description or "null")
            except json.JSONDecodeError:
                old_metadata = None
            if previous == source_cases(family) and old_metadata == metadata:
                entry["action"] = "unchanged"
            else:
                entry.update(action="archive_and_create", archive_code=f"{family}@legacy-{dataset_id}-{old_hash[:12]}")
                if active:
                    entry["blocked"].append("queued/running benchmark")
                cur.execute("select id from bench_datasets where code=%s", (entry["archive_code"],))
                if cur.fetchone() is not None:
                    entry["blocked"].append("archive code collision")
        entries.append(entry)
    plan = {"version": 1, "datasets": entries, "blocked": any(entry["blocked"] for entry in entries)}
    return {**plan, "plan_sha256": digest(plan)}


def apply_plan(cur: Any, expected_sha256: str) -> dict[str, Any]:
    """Все переименования/создания — одна transaction; никаких DELETE/UPDATE bench_cases/results."""
    with cur.connection.transaction():
        # Один порядок семей и advisory lock также защищают отсутствующие canonical rows.
        for family in FAMILIES:
            cur.execute("select pg_advisory_xact_lock(hashtextextended(%s,0))", (f"bench-dataset-upgrade:{family}",))
        plan = build_plan(cur, lock=True)
        if plan["blocked"]:
            raise ValueError("upgrade заблокирован активным benchmark либо коллизией кода; выполните новый --plan")
        if all(entry["action"] == "unchanged" for entry in plan["datasets"]):
            return {**plan, "applied": False, "already_current": True}
        if plan["plan_sha256"] != expected_sha256:
            raise ValueError("план устарел: состояние БД/корпус изменились, повторите --plan")
        for entry in plan["datasets"]:
            family = entry["family"]
            if entry["action"] == "unchanged":
                continue
            if entry["action"] == "archive_and_create":
                cur.execute("select description from bench_datasets where id=%s", (entry["existing_id"],))
                old_description = cur.fetchone()[0]
                provenance = {
                    "family": family,
                    "role": "legacy",
                    "archived_from": family,
                    "content_sha256": entry["existing_content_sha256"],
                    "previous_description": old_description,
                }
                cur.execute(
                    "update bench_datasets set code=%s,description=%s where id=%s and code=%s",
                    (entry["archive_code"], json.dumps(provenance, ensure_ascii=False), entry["existing_id"], family),
                )
                if cur.rowcount != 1:
                    raise ValueError("canonical dataset изменился во время upgrade")
            seed_dataset(cur, family, load_rows(family))
            if source_metadata(family) != entry["target"]:
                raise ValueError("корпус изменился во время upgrade")
        return {**plan, "applied": True, "already_current": False}
