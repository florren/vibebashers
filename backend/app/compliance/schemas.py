"""Pydantic-модели контрактов contracts/events/compliance (реэкспорт; генерируется scripts/gen_schemas.py)."""
from __future__ import annotations

from app.contracts.events.compliance.misselling_verdict import MissellingVerdict
from app.contracts.events.compliance.session_event import SessionEvent
from app.contracts.events.compliance.speaker_attribution import SpeakerAttribution
from app.contracts.events.compliance.stt_result import SttResult
from app.contracts.events.compliance.transcript_report import TranscriptReport

__all__ = ["MissellingVerdict", "SessionEvent", "SpeakerAttribution", "SttResult", "TranscriptReport"]
