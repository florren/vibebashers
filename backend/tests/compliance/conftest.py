"""Тесты B07: общая засеянная БД из tests/integration/conftest.py + маркер integration."""

from __future__ import annotations

import pytest

from tests.integration.conftest import conn, db_url, migrated_db, seeded  # noqa: F401  (реэкспорт фикстур)


def pytest_collection_modifyitems(items: list[pytest.Item]) -> None:
    for item in items:
        if "tests/compliance" in str(item.fspath).replace("\\", "/"):
            item.add_marker(pytest.mark.integration)
