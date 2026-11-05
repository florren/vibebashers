"""Неизменный маленький synthetic bank для bounded replay11; никаких reset/drop."""

from __future__ import annotations

import datetime as dt
import random
from typing import Any

import psycopg
from app.replay.scenario11_record import fixture


async def seed_bank(conn: psycopg.AsyncConnection[Any], dsn: str) -> None:
    """Fresh isolated bank only. Caller owns schema/migrations; never drop/reset here."""
    from scripts.seed.refs import seed_all_refs

    empty = await (
        await conn.execute(
            "select (select count(*) from clients)+(select count(*) from signals)+(select count(*) from sim_runs)"
        )
    ).fetchone()
    if empty is None or empty[0]:
        raise ValueError("fresh_empty_synthetic_bank_required")
    data = fixture()
    now = dt.datetime.fromisoformat(data["sim_time"])
    # Reference seeding has a synchronous implementation; same explicitly supplied bank.
    with psycopg.connect(dsn) as sync_conn:
        seed_all_refs(sync_conn.cursor(), random.Random(42), seed=42, sim_time=now)
    client = data["client"]
    city = await (
        await conn.execute(
            "select id from cities where name_ru=%s and region_code=%s",
            (client["city"], client["region_code"]),
        )
    ).fetchone()
    assert city
    await conn.execute(
        "insert into clients(display_name,segment_code,psychotype_code,region_code,city_id,churn_risk,clv_estimate_rub) values('Клиент replay11',%s,%s,%s,%s,%s,100000)",
        (
            client["segment"],
            client["psychotype"],
            client["region_code"],
            city[0],
            client["churn_risk"],
        ),
    )
    await conn.execute(
        "insert into client_products(client_id,product_code,status,card_last4) values(1,'debit_card','active','0000')"
    )
    await conn.execute("insert into sim_state(id,sim_time,seed,running) values(1,%s,42,false)", (now,))
    await conn.commit()


async def configure_profile(conn: psycopg.AsyncConnection[Any], profile: Any) -> Any:
    """Only fresh dedicated fixture DB. Mirror the reviewed profile, never its ledger."""
    from dataclasses import replace

    from psycopg import sql
    from psycopg.types.json import Jsonb

    row = await (
        await conn.execute("select current_database(),(select count(*) from signals),(select count(*) from agent_runs)")
    ).fetchone()
    if not row or not row[0].startswith("cx_replay11_") or row[1] or row[2]:
        raise ValueError("dedicated_empty_replay11_bank_required")
    profile = replace(profile, id=profile.id or 1)
    # These are reference profiles in the dedicated empty synthetic DB; no canonical DB is used.
    await conn.execute("delete from llm_profiles")
    columns = [
        name
        for name in profile.__dataclass_fields__
        if name
        in {
            "id",
            "code",
            "provider",
            "model",
            "role",
            "base_url",
            "temperature",
            "rpm_limit",
            "rpd_limit",
            "price_in_per_1m",
            "price_out_per_1m",
            "supports_tools",
            "supports_stream",
            "extra",
            "api_key_id",
        }
    ]
    await conn.execute(
        sql.SQL("insert into llm_profiles ({}) overriding system value values ({})").format(
            sql.SQL(",").join(map(sql.Identifier, columns)),
            sql.SQL(",").join(sql.Placeholder() * len(columns)),
        ),
        [Jsonb(getattr(profile, c)) if c == "extra" else getattr(profile, c) for c in columns],
    )
    await conn.execute(
        "insert into settings(key,value) values('setup_payload',%s) on conflict(key) do update set value=excluded.value",
        (Jsonb({"llm": {f"{role}_profile_id": profile.id for role in ("main", "fast", "twin")}}),),
    )
    await conn.commit()
    return profile
