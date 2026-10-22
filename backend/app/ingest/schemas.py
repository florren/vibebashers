"""Pydantic-модели контрактов contracts/events/ingest (реэкспорт; генерируется scripts/gen_schemas.py)."""
from __future__ import annotations

from app.contracts.events.ingest.ingest_event import IngestEvent
from app.contracts.events.ingest.transcript import Transcript
from app.contracts.events.ingest.unified_message import UnifiedMessage

__all__ = ["IngestEvent", "Transcript", "UnifiedMessage"]
