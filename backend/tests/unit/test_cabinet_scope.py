"""T-241: границы preset/run до SQL и различие unknown/all/current."""

from __future__ import annotations

import datetime as dt
from unittest.mock import AsyncMock

import pytest
from fastapi import HTTPException
from starlette.requests import Request

from app.analytics.cabinet_scope import ROLES, actor_role, resolve_scope, validate_run


def request(role: str = "cx_lead", line: str | None = None) -> Request:
    headers = [(b"x-cx-role", role.encode())]
    if line is not None:
        headers.append((b"x-cx-product-line", line.encode()))
    return Request({"type": "http", "headers": headers})


@pytest.mark.parametrize(
    "value", ["", "0", "-1", "²", "٢", "99999999999999999999", "9223372036854775808", "1;select 1"]
)
def test_invalid_run_rejected(value: str) -> None:
    with pytest.raises(HTTPException) as exc:
        validate_run(value)
    assert exc.value.status_code == 422


@pytest.mark.parametrize("value", ["current", "all", "1", "9223372036854775807"])
def test_run_bounds(value: str) -> None:
    validate_run(value)


def test_default_and_known_roles() -> None:
    assert actor_role(Request({"type": "http", "headers": []})) == "cx_lead"
    for role in ROLES:
        assert actor_role(request(role)) == role
    with pytest.raises(HTTPException):
        actor_role(request("operator"))


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "visibility,role,line,chosen,expected",
    [
        ("soft", "product_manager", "deposits", None, ["deposits"]),
        ("soft", "product_manager", "deposits", "all", None),
        ("soft", "product_manager", "deposits", "cards", ["cards"]),
        ("strict", "product_manager", "deposits", None, ["deposits"]),
        ("strict", "product_head", None, None, ["deposits", "cards"]),
        ("strict", "cx_lead", None, None, None),
    ],
)
async def test_scope_presets(
    monkeypatch: pytest.MonkeyPatch,
    visibility: str,
    role: str,
    line: str | None,
    chosen: str | None,
    expected: list[str] | None,
) -> None:
    now = dt.datetime(2026, 11, 9, tzinfo=dt.UTC)
    fetch = AsyncMock(
        side_effect=[
            [{"key": "cabinet", "value": {"visibility": visibility, "product_head_lines": ["deposits", "cards"]}}],
            [{"code": "deposits"}, {"code": "cards"}, {"code": "insurance"}],
            [{"id": 1}],
        ]
    )
    monkeypatch.setattr("app.analytics.cabinet_scope.fetch_all", fetch)
    monkeypatch.setattr(
        "app.analytics.cabinet_scope.fetch_one", AsyncMock(return_value={"sim_time": now, "current_run_id": None})
    )
    scope = await resolve_scope(None, request(role, line), chosen, "week", "current")  # type: ignore[arg-type]
    assert scope.lines == expected
    assert scope.run_ids == [1]  # Нет current — только baseline, не fallback all.
    assert scope.since == now - dt.timedelta(days=7)
    if visibility == "strict" and role.startswith("product_"):
        assert {x["code"] for x in scope.available_lines} <= {"deposits", "cards"}
    sql, args = scope.predicate("s")
    assert "s.run_id = ANY(%s)" in sql and [1] in args


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "role,line,chosen",
    [
        ("product_manager", "deposits", "cards"),
        ("product_manager", "deposits", "all"),
        ("product_manager", None, None),
        ("product_head", None, "insurance"),
    ],
)
async def test_strict_forbidden(
    monkeypatch: pytest.MonkeyPatch, role: str, line: str | None, chosen: str | None
) -> None:
    monkeypatch.setattr(
        "app.analytics.cabinet_scope.fetch_all",
        AsyncMock(
            side_effect=[
                [{"key": "cabinet", "value": {"visibility": "strict", "product_head_lines": ["deposits"]}}],
                [{"code": "deposits"}, {"code": "cards"}, {"code": "insurance"}],
            ]
        ),
    )
    with pytest.raises(HTTPException) as exc:
        await resolve_scope(None, request(role, line), chosen, "week", "current")  # type: ignore[arg-type]
    assert exc.value.status_code == 403


@pytest.mark.parametrize(
    "path,headers",
    [
        ("/api/cabinet/overview?run_id=²", {}),
        ("/api/cabinet/signals?run_id=9223372036854775808", {}),
        ("/api/cabinet/signals?sort=free_sql", {}),
        ("/api/cabinet/overview", {"X-Cx-Role": "unknown"}),
        ("/api/cabinet/report?product_line=deposits&run_id=", {}),
    ],
)
def test_invalid_boundaries_never_open_db_or_llm(
    monkeypatch: pytest.MonkeyPatch, path: str, headers: dict[str, str]
) -> None:
    from collections.abc import AsyncIterator
    from contextlib import asynccontextmanager

    from fastapi.testclient import TestClient

    from app.main import create_app

    counters = {"db": 0, "llm": 0}

    @asynccontextmanager
    async def bomb_db() -> AsyncIterator[None]:
        counters["db"] += 1
        raise AssertionError("invalid boundary opened database")
        yield  # pragma: no cover

    class BombAgent:
        def __getattr__(self, name: str) -> None:
            counters["llm"] += 1
            raise AssertionError("read boundary called agent")

    monkeypatch.setattr("app.api.cabinet.read_db", bomb_db)
    app = create_app()
    app.state.agent = BombAgent()
    client = TestClient(app)
    assert client.get(path, headers=headers).status_code == 422
    assert counters == {"db": 0, "llm": 0}


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "settings,role,bound,expected",
    [
        ([{"key": "cabinet", "value": "malformed"}], "cx_lead", None, 409),
        ([{"key": "cabinet", "value": {"visibility": "invalid"}}], "cx_lead", None, 409),
        ([{"key": "cabinet", "value": {"product_head_lines": [{}]}}], "product_head", None, 409),
        ([{"key": "cabinet", "value": {"product_head_lines": ["missing"]}}], "product_head", None, 409),
        ([], "cx_lead", "missing", 422),
    ],
)
async def test_invalid_settings_are_explicit(
    monkeypatch: pytest.MonkeyPatch, settings: list[dict[str, object]], role: str, bound: str | None, expected: int
) -> None:
    monkeypatch.setattr(
        "app.analytics.cabinet_scope.fetch_all", AsyncMock(side_effect=[settings, [{"code": "deposits"}]])
    )
    with pytest.raises(HTTPException) as error:
        await resolve_scope(None, request(role, bound), None, "week", "current")  # type: ignore[arg-type]
    assert error.value.status_code == expected
