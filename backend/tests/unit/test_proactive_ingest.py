"""Внешний DTO не может назначить себе authority native producer."""

from __future__ import annotations

from unittest.mock import AsyncMock

import pytest
from fastapi import HTTPException
from starlette.requests import Request

from app.api import ingest
from app.ingest import normalizer


class DatabaseBomb:
    def __getattr__(self, name):
        raise AssertionError("reserved origin должен отклоняться до любого SQL/transaction")


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "source,origin",
    [
        ("api", "proactive"),
        ("file_import", "proactive"),
        ("mock_social_polling", "proactive"),
        ("rest_transcripts", "proactive"),
        ("fault_monitor", "api"),
    ],
)
async def test_adapter_cannot_claim_native_origin_before_sql(source, origin):
    with pytest.raises(normalizer.IngestError, match="зарезервированы"):
        await normalizer.create_signal(DatabaseBomb(), {"origin": origin}, source_code=source)


@pytest.mark.asyncio
@pytest.mark.parametrize("source,origin", [("api", "proactive"), ("fault_monitor", "api")])
async def test_http_reserved_source_or_origin_rejected_before_prepare(monkeypatch, source, origin):
    def bomb():
        raise AssertionError("HTTP validation должна предшествовать DB/prepare")

    monkeypatch.setattr(ingest, "db", bomb)
    request = Request({"type": "http", "headers": [(b"x-source-code", source.encode())]})
    with pytest.raises(HTTPException) as rejected:
        await ingest.post_ingest_messages(request, {"origin": origin, "_internal_producer": "fault_monitor"})
    assert rejected.value.status_code == 422


@pytest.mark.asyncio
async def test_legacy_proactive_channel_with_api_origin_remains_external(monkeypatch):
    write = AsyncMock(return_value={"status": "accepted"})
    monkeypatch.setattr(normalizer, "_create_signal", write)
    body = {"channel": "proactive", "origin": "api"}
    assert await normalizer.create_signal(DatabaseBomb(), body, source_code="api") == {"status": "accepted"}
    assert write.call_args.args[1] == body


@pytest.mark.asyncio
async def test_only_native_caller_keyword_enables_existing_compliance_origin(monkeypatch):
    write = AsyncMock(return_value={"status": "accepted"})
    monkeypatch.setattr(normalizer, "_create_signal", write)
    assert await normalizer.create_signal(
        DatabaseBomb(),
        {"channel": "branch", "origin": "proactive"},
        source_code="api",
        _internal_producer="compliance",
    ) == {"status": "accepted"}
