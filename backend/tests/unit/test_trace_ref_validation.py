"""Некорректные внутренние ссылки не должны превращаться в SQL/Python 500."""

from __future__ import annotations

import pytest
from fastapi import HTTPException

from app.trace.store import resolve


@pytest.mark.parametrize("kind", ["operation", "ingest", "alert"])
@pytest.mark.parametrize(
    "ref", ["²", "①", "abc", "0", "-1", "9223372036854775808", pytest.param("1" * 5000, id="integer-parser-limit")]
)
async def test_invalid_numeric_reference_is_rejected_before_database(kind, ref):
    class NoDatabase:
        async def execute(self, *args, **kwargs):
            raise AssertionError("invalid ref must not access database")

    with pytest.raises(HTTPException) as error:
        await resolve(NoDatabase(), kind, ref)
    assert error.value.status_code == 422


async def test_correlation_uuid_cannot_select_nonexistent_column_on_another_kind():
    class NoDatabase:
        async def execute(self, *args, **kwargs):
            raise AssertionError("invalid UUID kind must not access database")

    with pytest.raises(HTTPException) as error:
        await resolve(NoDatabase(), "operation", "00000000-0000-0000-0000-000000000235")
    assert error.value.status_code == 422
