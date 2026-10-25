"""demo_assets kind=cassette: upsert по path без дублирования строк (T-198)."""

from __future__ import annotations

from app.replay.store import upsert_demo_asset


def test_upsert_demo_asset_updates_checksum(conn) -> None:
    row = {
        "kind": "cassette",
        "scenario_id": "qr_fee_public_review",
        "title_ru": "Сценарий 8",
        "path": "data/cassettes/gigachat.jsonl",
        "checksum": "a" * 64,
    }
    id1 = upsert_demo_asset(conn, row)
    row["checksum"] = "b" * 64
    id2 = upsert_demo_asset(conn, row)
    assert id1 == id2
    cur = conn.execute("select count(*) from demo_assets where kind = 'cassette' and path = %s", (row["path"],))
    assert int(cur.fetchone()[0]) == 1
    cur = conn.execute("select checksum from demo_assets where id = %s", (id1,))
    assert cur.fetchone()[0] == "b" * 64
