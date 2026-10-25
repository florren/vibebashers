"""Живой детектор реплики — 5 с; пакетный отчёт транскрипта — 12 с."""

from app.llm.base import TIMEOUTS_S
from app.llm.failover import ProviderChain
from app.llm.mock import MockProvider


def test_detector_is_five_seconds_batch_is_twelve() -> None:
    assert TIMEOUTS_S["detector"] == 5.0
    assert TIMEOUTS_S["batch"] == 12.0
    chain = ProviderChain([MockProvider()])
    assert chain.timeout_for("detector") == 5.0
    assert chain.timeout_for("batch") == 12.0
