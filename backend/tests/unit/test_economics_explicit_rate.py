"""T243: явная ставка меняет только выбор из каталога, не формулу/побочные эффекты."""

from contextlib import asynccontextmanager
from unittest.mock import AsyncMock

import pytest
from fastapi.testclient import TestClient

from app.api import metrics
from app.main import create_app


@pytest.fixture
def preview(monkeypatch):
    counters = {"db": 0}

    @asynccontextmanager
    async def database():
        counters["db"] += 1
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
                    {"code": "bank_average", "rate_rub": 4050, "maps_to": {"fallback": True}},
                    {"code": "premium_service", "rate_rub": 91.53, "maps_to": {}},
                ],
            }
        ),
    )
    with TestClient(create_app()) as client:
        yield client, counters


def test_explicit_rate_uses_the_single_compute_and_keeps_legacy_mapping(preview):
    client, _ = preview
    params = {"affected": 12, "segment": "vip"}
    automatic = client.get("/api/metrics/economics/preview", params={**params, "product": "deposit"}).json()
    explicit = client.get("/api/metrics/economics/preview", params={**params, "rate_code": "deposit"}).json()
    assert automatic["potential_loss_rub"] == explicit["potential_loss_rub"] == 631.52
    for key in automatic.keys() - {"rate_reason"}:
        assert explicit[key] == automatic[key], key
    assert (
        client.get("/api/metrics/economics/preview", params={"affected": 0, "rate_code": "deposit"}).json()[
            "affected_count"
        ]
        == 0
    )
    assert (
        client.get("/api/metrics/economics/preview", params={"affected": 0, "rate_code": "deposit"}).json()[
            "potential_loss_rub"
        ]
        == 0
    )
    response = client.get(
        "/api/metrics/economics/preview",
        params={"affected": 3, "rate_code": "premium_service", "detractor_share": 0.17, "no_return_share": 0.21},
    )
    expected = metrics.dcltv.compute(
        affected=3,
        detractor_share=0.17,
        no_return_share=0.21,
        rate=metrics.dcltv.Rate("premium_service", 91.53, "explicit"),
        premium_addon=0,
        retention_factor=0,
        outcome_class="open",
    )
    assert response.status_code == 200
    assert response.json()["potential_loss_rub"] == expected["potential_loss_rub"]
    assert response.json()["premium_addon_rub"] == 0


@pytest.mark.parametrize("extra", [{"product": "deposit"}, {"system": "online"}, {"product": ""}, {"system": ""}])
def test_ambiguous_rate_input_rejected_before_database(preview, extra):
    client, counters = preview
    response = client.get("/api/metrics/economics/preview", params={"rate_code": "deposit", **extra})
    assert response.status_code == 422
    assert counters["db"] == 0


@pytest.mark.parametrize(
    "params",
    [
        {"rate_code": ""},
        {"rate_code": "a" * 121},
        {"affected": -1},
        {"affected": 1.5},
        {"detractor_share": "NaN"},
        {"no_return_share": "Infinity"},
    ],
)
def test_invalid_query_has_no_database_calls(preview, params):
    client, counters = preview
    assert client.get("/api/metrics/economics/preview", params=params).status_code == 422
    assert counters["db"] == 0


def test_unknown_code_does_not_fall_back_to_bank_average(preview, monkeypatch):
    client, counters = preview

    def forbidden(**kwargs):
        raise AssertionError("Unknown rate must not reach compute")

    monkeypatch.setattr(metrics.dcltv, "compute", forbidden)
    assert client.get("/api/metrics/economics/preview", params={"rate_code": "unknown"}).status_code == 422
    assert counters["db"] == 1
