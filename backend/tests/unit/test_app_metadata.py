"""T-234: готовность metadata до первого HTTP без выполнения зависимостей/данных."""

from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from fastapi import APIRouter, Depends
from fastapi.testclient import TestClient

from app.db.session import get_session
from app.main import create_app


def test_metadata_preparation_never_executes_routes_or_dependencies(monkeypatch):
    calls = []
    router = APIRouter()

    async def dependency():
        calls.append("dependency")
        return "ready"

    @router.get("/api/metadata-probe")
    async def probe(value: str = Depends(dependency)):
        calls.append("handler")
        return {"value": value}

    def include(app):
        app.include_router(router)
        return ["probe"]

    monkeypatch.setattr("app.main.include_api_routers", include)
    app = create_app()
    assert calls == []
    schema = app.openapi_schema
    assert schema and "/api/metadata-probe" in schema["paths"]
    assert app.openapi() is schema
    with TestClient(app) as client:
        assert client.get("/api/metadata-probe").json() == {"value": "ready"}
    assert calls == ["dependency", "handler"]


def test_late_routes_update_schema_and_remain_callable():
    app = create_app()
    previous = app.openapi()

    @app.delete("/api/late-metadata-probe")
    async def late():
        return {"ok": True}

    updated = app.openapi()
    assert updated is not previous
    assert "/api/late-metadata-probe" in updated["paths"]
    with TestClient(app) as client:
        assert client.delete("/api/late-metadata-probe").json() == {"ok": True}


@pytest.mark.parametrize("healthy", [True, False])
def test_health_readiness_and_late_dependency_overrides(healthy, monkeypatch):
    llm = AsyncMock(side_effect=AssertionError("health/metadata must never call LLM"))
    monkeypatch.setattr("app.llm.failover.ProviderChain.complete_structured", llm)
    calls = []

    class Session:
        async def execute(self, query):
            sql = str(query)
            calls.append(sql)
            if not healthy:
                raise RuntimeError("synthetic DB unavailable")
            value = True if "setup_completed" in sql else False
            return SimpleNamespace(
                scalar_one_or_none=lambda: value,
                all=lambda: [SimpleNamespace(code="fixture", is_active=True)],
            )

    async def override():
        yield Session()

    app = create_app()
    assert app.openapi_schema is not None and calls == []
    # Override добавляется после eager compilation и по-прежнему разрешается на запросе.
    app.dependency_overrides[get_session] = override
    with TestClient(app) as client:
        response = client.get("/api/health")
    assert response.status_code == 200
    assert response.json()["db"] is healthy
    assert response.json()["status"] == ("ok" if healthy else "degraded")
    assert len(calls) == (4 if healthy else 1)
    assert llm.call_count == 0
