"""T-015: seed каталога и настоящий SQL fallback на изолированной PostgreSQL."""

from __future__ import annotations

import datetime as dt

import psycopg
from psycopg.rows import dict_row

from app.agent.tools.base import ToolContext
from app.agent.tools.write import render_template
from app.economics import dcltv
from tests.helpers import dsn


async def test_seeded_templates_keep_segment_language_and_partner_confirmation(seeded):
    async with await psycopg.AsyncConnection.connect(dsn(seeded)) as connection:
        ctx = ToolContext(connection, run_id=1, agent_run_id=1, sim_time=dt.datetime(2026, 11, 1, tzinfo=dt.UTC))
        values = {
            "name": "TEST_NAME",
            "manager": "TEST_MANAGER",
            "summary": "TEST_SUMMARY",
            "sla_minutes": 10,
            "product_name": "TEST_PRODUCT",
            "eta": "TEST_ETA",
            "progress": "TEST_PROGRESS",
            "resolution": "TEST_RESOLUTION",
            "gift": "TEST_GIFT",
            "question": "TEST_QUESTION",
        }
        codes = (
            "ack_received",
            "proactive_fault",
            "clarify_request",
            "progress_update",
            "resolved",
            "gift_offer",
            "public_reply",
            "dm_invite",
            "closure_ack",
        )
        for lang in ("ru", "en"):
            for segment in ("mass", "premium", "vip", "ultra_vip"):
                for code in codes:
                    subject, body = await render_template(ctx, code, "sms", segment, values, lang)
                    assert body and "{{" not in body, (lang, segment, code)
                _, acknowledgement = await render_template(ctx, "ack_received", "sms", segment, values, lang)
                assert ("TEST_MANAGER" in acknowledgement) == (segment in ("vip", "ultra_vip"))
            for code in ("dm_invite", "closure_ack"):
                row = await (
                    await connection.execute(
                        "select lang from notification_templates where code=%s and channel_code=%s and lang=%s",
                        (code, "csi_survey", lang),
                    )
                ).fetchone()
                assert row == (lang,)
        rows = await (
            await connection.execute(
                "select code, rule->'requires_hitl' from gift_catalog where partner_display_name is not null order by code"
            )
        ).fetchall()
        assert rows == [("business_class_discount", True), ("lounge_pass", True), ("restaurant_special", True)]


async def test_seeded_financial_defaults_and_customizable_misselling(seeded):
    async with await psycopg.AsyncConnection.connect(dsn(seeded), row_factory=dict_row) as connection:
        cfg = await dcltv.load_settings(connection)
        assert cfg["settings"]["misselling_case_cost_rub"] == 4050
        for system in ("notification_gw", "promo_engine", "antifraud", "core_abs"):
            rate = dcltv.pick_rate(cfg["rates"], product=None, system=system, channel=None, segment="mass")
            assert rate.code == "bank_average" and rate.rub == 4050
            # ADR-0012: неизвестный продукт использует среднюю даже при известном канале.
            anonymous = dcltv.pick_rate(
                cfg["rates"], product=None, system=system, channel="chat", segment="mass", unknown_product_average=True
            )
            assert anonymous.code == "bank_average" and anonymous.rub == 4050
        run = await (
            await connection.execute(
                "insert into sim_runs(kind,label,seed,started_sim) values ('free','T015 financial review',42,'2026-11-01T06:00Z') returning id"
            )
        ).fetchone()
        incident = await (
            await connection.execute(
                """insert into incidents(run_id,title,incident_type,team_code,complexity,criticality,priority,status,created_by,created_sim,sla_due_sim,take_due_sim)
               values (%s,'T015 financial review','misselling','team_compliance','easy','low',4,'new','scenario','2026-11-01T06:00Z','2026-11-02T06:00Z','2026-11-01T08:00Z') returning id""",
                (run["id"],),
            )
        ).fetchone()
        result = await dcltv.compute_incident(connection, incident["id"])
        assert result["rate_code"] == "misselling_case"
        assert result["rate_rub"] == result["potential_loss_rub"] == 4050
        stored = await (
            await connection.execute(
                "select rate_rub, potential_loss_rub from incident_economics where incident_id=%s", (incident["id"],)
            )
        ).fetchone()
        assert stored["rate_rub"] == stored["potential_loss_rub"] == 4050
        # ADR-0012/0013 сохраняют настраиваемую стоимость; новый default её не фиксирует навсегда.
        await connection.execute("update economics_settings set misselling_case_cost_rub=%s where id=1", (7777,))
        customized = await dcltv.compute_incident(connection, incident["id"])
        assert customized["rate_rub"] == customized["potential_loss_rub"] == 7777
        await connection.rollback()
