"""Сценарные тесты (T-142): общая засеянная БД из tests/integration/conftest.py + маркер scenario."""

from __future__ import annotations

import pytest

from tests.integration.conftest import conn, db_url, migrated_db, seeded  # noqa: F401  (реэкспорт фикстур)


def pytest_collection_modifyitems(items: list[pytest.Item]) -> None:
    for item in items:
        if "tests/scenarios" in str(item.fspath).replace("\\", "/"):
            item.add_marker(pytest.mark.scenario)
            item.add_marker(pytest.mark.integration)
