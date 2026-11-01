"""Калькулятор использует единственную формулу dCLTV и не пишет в БД."""

from contextlib import asynccontextmanager
from unittest.mock import AsyncMock

from fastapi.testclient import TestClient

from app.api import metrics
from app.main import create_app


def test_preview_matches_spec_and_zero(monkeypatch):
    @asynccontextmanager
    async def database():
        yield object()

    monkeypatch.setattr(metrics, "db", database)
    monkeypatch.setattr(
        metrics.dcltv,
        "load_settings",
        AsyncMock(
            return_value={
                "settings": {},
                "rates": [
                    {"code": "deposit", "rate_rub": 961, "maps_to": {"products": ["deposit"]}},
                    {"code": "premium_service", "rate_rub": 91.53, "maps_to": {}},
                ],
            }
        ),
    )
    with TestClient(create_app()) as client:
        response = client.get(
            "/api/metrics/economics/preview", params={"affected": 12, "product": "deposit", "segment": "vip"}
        )
        assert response.status_code == 200, response.text
        assert response.json()["potential_loss_rub"] == 631.52
        assert client.get("/api/metrics/economics/preview", params={"affected": 0}).json()["potential_loss_rub"] == 0
        assert client.get("/api/metrics/economics/preview", params={"affected": -1}).status_code == 422
        assert client.get("/api/metrics/economics/preview", params={"detractor_share": 2}).status_code == 422
