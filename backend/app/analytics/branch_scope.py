"""Общие read-only фильтры справочника ВСП и CSI, без обращения к SimClock."""

from __future__ import annotations

import datetime as dt
from typing import Any

from app.api.common import fetch_one
from app.trace.store import Conn


def branch_predicate(
    lines: list[str] | None, region: str | None, *, status: str | None = None, alias: str = "b"
) -> tuple[str, list[Any]]:
    # alias задают только внутренние литералы, фильтры идут в params.
    parts = ["TRUE"]
    args: list[Any] = []
    if lines is not None:
        parts.append(f"{alias}.product_line_codes && %s::text[]")
        args.append(lines)
    if region is not None:
        parts.append(f"{alias}.region_code=%s")
        args.append(region)
    if status is not None:
        parts.append(f"{alias}.branch_status=%s")
        args.append(status)
    return " AND ".join(parts), args


async def directory_metadata(conn: Conn) -> dict[str, Any]:
    row = await fetch_one(conn, "SELECT value FROM settings WHERE key='branch_directory'")
    value = row["value"] if row and isinstance(row["value"], dict) else {}
    stamp = value.get("as_of_sim")
    try:
        parsed = dt.datetime.fromisoformat(stamp) if isinstance(stamp, str) else None
    except ValueError:
        parsed = None
    return {
        "mode": value.get("mode") if value.get("mode") in ("synthetic", "snapshot_file") else None,
        "synthetic": value.get("is_synthetic") if type(value.get("is_synthetic")) is bool else None,
        "as_of_sim": parsed if parsed and parsed.tzinfo is not None else None,
        "scope": "global_directory_snapshot",
    }
