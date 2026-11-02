"""T243: actual30rates, сохранённый producer fixture и readonly HTTP без LLM."""

from __future__ import annotations

import asyncio
import csv
from pathlib import Path
from typing import Any

import psycopg
from fastapi.testclient import TestClient
from psycopg.rows import dict_row

from app.economics import dcltv
from app.main import create_app
from tests.helpers import dsn
from tests.integration.test_cabinet_api import fingerprint


def test_all_catalog_rates_and_persisted_incident_match_without_writes(seeded: str, monkeypatch: Any) -> None:
    # Только подготовка fixture вызывает реальный write-producer, HTTP preview ниже — readonly.
    async def prepare() -> tuple[dict[str, Any], str | None]:
        async with await psycopg.AsyncConnection.connect(dsn(seeded), row_factory=dict_row) as conn:
            incident = await (
                await conn.execute(
                    "select i.id,c.segment_code from incidents i left join clients c on c.id=i.primary_client_id where i.incident_type not in ('fee_refund','misselling') order by i.id limit 1"
                )
            ).fetchone()
            assert incident
            result = await dcltv.compute_incident(conn, incident["id"])
            assert result
            saved = await (
                await conn.execute(
                    "select potential_loss_rub from incident_economics where incident_id=%s", (incident["id"],)
                )
            ).fetchone()
            assert saved and float(saved["potential_loss_rub"]) == result["potential_loss_rub"]
            return result, incident["segment_code"]

    expected, segment = asyncio.run(prepare())
    attempts = {"llm": 0, "write_producer": 0}

    async def bomb_llm(*args: Any, **kwargs: Any) -> None:
        attempts["llm"] += 1
        raise AssertionError("No LLM in calculator")

    async def bomb_write(*args: Any, **kwargs: Any) -> None:
        attempts["write_producer"] += 1
        raise AssertionError("No materialization in preview")

    from app.llm.failover import ProviderChain

    monkeypatch.setattr(ProviderChain, "complete_structured", bomb_llm)
    monkeypatch.setattr(dcltv, "compute_incident", bomb_write)
    monkeypatch.setattr(dcltv, "recompute", bomb_write)
    with psycopg.connect(dsn(seeded), autocommit=True) as sql:
        rates = sql.execute("select code,rate_rub from dcltv_rates order by code").fetchall()
        with (Path(__file__).resolve().parents[3] / "data/dcltv_rates.csv").open() as source:
            catalog_codes = {row["code"] for row in csv.DictReader(source)}
        assert len(rates) == len(catalog_codes) == 31
        assert {code for code, _ in rates} == catalog_codes
        before = fingerprint(sql)
        with TestClient(create_app()) as client:
            for code, rub in rates:
                response = client.get(
                    "/api/metrics/economics/preview",
                    params={"rate_code": code, "affected": 3, "detractor_share": 0.1, "no_return_share": 0.5},
                )
                assert response.status_code == 200
                result = response.json()
                reference = dcltv.compute(
                    affected=3,
                    detractor_share=0.1,
                    no_return_share=0.5,
                    rate=dcltv.Rate(code, float(rub), "fixture"),
                    premium_addon=0,
                    retention_factor=0,
                    outcome_class="open",
                )
                assert result["rate_code"] == code
                assert result["potential_loss_rub"] == reference["potential_loss_rub"]
            params = {
                "rate_code": expected["rate_code"],
                "affected": expected["affected_count"],
                "detractor_share": expected["detractor_share"],
                "no_return_share": expected["no_return_share"],
            }
            if segment:
                params["segment"] = segment
            actual = client.get("/api/metrics/economics/preview", params=params)
            assert actual.status_code == 200
            assert actual.json()["potential_loss_rub"] == expected["potential_loss_rub"]
            assert actual.json()["premium_addon_rub"] == expected["premium_addon_rub"]
            assert (
                client.get("/api/metrics/economics/preview", params={"rate_code": "untrusted-code"}).status_code == 422
            )
        assert fingerprint(sql) == before
    assert attempts == {"llm": 0, "write_producer": 0}
