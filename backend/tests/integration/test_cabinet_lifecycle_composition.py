"""T-241 composition: T121 lease должен сработать до T161 composite metadata."""

from __future__ import annotations

import psycopg
import pytest

from app.sim import run_lifecycle
from app.tgbot.storage import lock_id


@pytest.mark.asyncio
async def test_run_lease_rejects_purge_before_any_fk_metadata(
    migrated_db: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    dsn = migrated_db.replace("postgresql+psycopg:", "postgresql:")
    calls = []

    async def forbidden_metadata(conn: object) -> list[object]:
        calls.append("foreign_keys")
        raise AssertionError("lease must guard before FK metadata")

    monkeypatch.setattr(run_lifecycle, "_foreign_keys", forbidden_metadata)
    async with (
        await psycopg.AsyncConnection.connect(dsn) as owner,
        await psycopg.AsyncConnection.connect(dsn) as contender,
    ):
        await owner.execute("select pg_advisory_xact_lock(%s)", (lock_id("run", 0, 987654321),))
        with pytest.raises(run_lifecycle.RunConflict, match="Telegram"):
            await run_lifecycle._lock_and_guard(contender, 987654321)
        assert calls == []
