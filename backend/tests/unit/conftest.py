"""Protocol unit tests isolate storage; PG wire accounting is integration-tested."""

import pytest

from app.llm import accounting
from tests.fixtures.accounting_protocol import ProtocolAccounting


@pytest.fixture(autouse=True)
def isolated_accounting_storage(monkeypatch):
    # Only tests/unit: every production APP_ENV still defaults to PostgreSQL.
    monkeypatch.setattr(accounting, "service", ProtocolAccounting)
