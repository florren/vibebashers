"""T-015: seed каталога и настоящий SQL fallback на изолированной PostgreSQL."""

from __future__ import annotations

import datetime as dt

import psycopg

from app.agent.tools.base import ToolContext
from app.agent.tools.write import render_template
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
