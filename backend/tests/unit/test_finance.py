"""Границы периода и валидация финансового среза без внешних сервисов."""

import datetime as dt

import pytest
from fastapi.testclient import TestClient

from app.economics.impact import bounds, money, scope
from app.errors import Problem
from app.main import create_app

NOW = dt.datetime(2026, 10, 29, 14, tzinfo=dt.UTC)


def test_period_bounds_and_money() -> None:
    assert bounds("live", NOW, None, None) == (None, None)
    for period, days in (("day", 1), ("week", 7), ("month", 30)):
        start, end = bounds(period, NOW, None, None)
        assert start is not None and end is not None
        assert end - start == dt.timedelta(days=days)
        assert end == NOW.replace(hour=0) + dt.timedelta(days=1)
    assert money("458.465") == 458.47
    assert money("-83.235") == -83.24


@pytest.mark.parametrize(
    "start,end",
    [
        (NOW, None),
        (None, NOW),
        (NOW, NOW),
        (NOW, NOW - dt.timedelta(days=1)),
        (NOW, NOW + dt.timedelta(days=367)),
        (NOW.replace(tzinfo=None), NOW),
    ],
)
def test_invalid_bounds(start: dt.datetime | None, end: dt.datetime | None) -> None:
    with pytest.raises(Problem) as exc:
        bounds("custom", NOW, start, end)
    assert exc.value.status == 422


def test_missing_run_never_removes_scope() -> None:
    sql, args = scope(None, NOW, NOW + dt.timedelta(days=1))
    assert "i.run_id = %s" in sql
    assert args == [None, NOW, NOW + dt.timedelta(days=1)]
    assert "i.closed_sim) < %s" in sql


@pytest.mark.parametrize(
    "query",
    [
        "probability_percent=-1",
        "probability_percent=101",
        "probability_percent=nan",
        "fine_per_case_rub=-1",
        "fine_per_case_rub=inf",
        "period=year",
        "offset=-1",
        "limit=101",
        "period=custom",
        "start_date=bad",
    ],
)
def test_invalid_queries_are_422(query: str) -> None:
    with TestClient(create_app()) as client:
        response = client.get("/api/v1/finance/impact/total?" + query)
    assert response.status_code == 422, response.text
