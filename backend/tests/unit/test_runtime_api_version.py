"""Публичная runtime OpenAPI не должна рекламировать старую версию протокола."""

from pathlib import Path

import httpx
import pytest
import yaml

from app.contracts.api_metadata import api_version
from app.main import create_app


def test_runtime_openapi_version_matches_canonical_contract():
    root = Path(__file__).resolve().parents[3]
    spec = yaml.safe_load((root / "contracts/api/openapi.yaml").read_text(encoding="utf-8"))
    assert create_app().openapi()["info"]["version"] == spec["info"]["version"]


@pytest.mark.asyncio
async def test_public_openapi_endpoint_advertises_the_same_contract_version():
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=create_app()), base_url="http://test") as client:
        response = await client.get("/openapi.json")
    assert response.status_code == 200
    assert response.json()["info"]["version"] == api_version()


def test_api_version_accepts_future_contract_without_another_code_constant(tmp_path):
    path = tmp_path / "openapi.yaml"
    path.write_text('info:\n  version: "9.8.7-demo"\n', encoding="utf-8")
    assert api_version(path) == "9.8.7-demo"


@pytest.mark.parametrize("document", ["[]", "info: null", "info: {version: 1}", 'info: {version: " "}'])
def test_missing_or_invalid_contract_version_is_not_replaced_with_old_value(tmp_path, document):
    path = tmp_path / "openapi.yaml"
    path.write_text(document, encoding="utf-8")
    with pytest.raises(ValueError, match="OpenAPI.*info.version"):
        api_version(path)


def test_drift_checker_rejects_stale_version_even_when_routes_match(monkeypatch, capsys):
    from scripts import check_openapi_drift

    from app import main

    app = create_app()
    app.version = "stale"
    monkeypatch.setattr(main, "create_app", lambda: app)
    monkeypatch.setattr("sys.argv", ["check_openapi_drift.py"])
    assert check_openapi_drift.main() == 1
    output = capsys.readouterr().out
    assert "openapi version drift:" in output and "code=stale" in output
    assert "missing=0 extra=0" in output
