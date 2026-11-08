"""Снимок ролей внутри bank transaction не должен блокировать отдельный accounting connection."""

import asyncio
import uuid

import psycopg
import pytest

from app.config import get_settings
from app.llm import credentials, run_profiles
from tests.helpers import MOCK_PROFILE, dsn, mock_chain, new_run

pytestmark = pytest.mark.integration


@pytest.mark.parametrize("failure", [None, "error", "cancel"])
async def test_snapshot_releases_catalog_lock_without_committing_bank_work(seeded, monkeypatch, failure):
    monkeypatch.setenv("DATABASE_URL", seeded)
    get_settings.cache_clear()
    async with await psycopg.AsyncConnection.connect(dsn(seeded)) as caller:
        rid = await new_run(caller, "snapshot lock boundary")
        sentinel = "snapshot-pending-" + uuid.uuid4().hex
        await caller.execute("insert into settings(key,value) values(%s,'{}')", (sentinel,))
        txid = (await (await caller.execute("select txid_current()")).fetchone())[0]
        entered = asyncio.Event()

        async def failed_capture(*args, **kwargs):
            entered.set()
            if failure == "error":
                raise ValueError("synthetic snapshot failure")
            await asyncio.Event().wait()

        if failure:
            monkeypatch.setattr(run_profiles, "capture", failed_capture)
        operation = run_profiles.resolve(caller, rid, mock_chain(), MOCK_PROFILE, new=True)
        if failure == "error":
            with pytest.raises(ValueError, match="synthetic"):
                await operation
        elif failure == "cancel":
            task = asyncio.create_task(operation)
            await entered.wait()
            task.cancel()
            with pytest.raises(asyncio.CancelledError):
                await task
        else:
            await operation
        assert (await (await caller.execute("select txid_current()")).fetchone())[0] == txid
        async with await psycopg.AsyncConnection.connect(dsn(seeded), autocommit=True) as observer:
            acquired = (
                await (await observer.execute("select pg_try_advisory_lock(%s)", (credentials.LOCK,))).fetchone()
            )[0]
            try:
                assert acquired, "роль захватила lock до конца bank transaction и блокирует live accounting"
                assert (
                    await (await observer.execute("select 1 from settings where key=%s", (sentinel,))).fetchone()
                    is None
                )
            finally:
                if acquired:
                    await observer.execute("select pg_advisory_unlock(%s)", (credentials.LOCK,))
        await caller.rollback()
