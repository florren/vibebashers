"""Версионированный care snapshot для durable storage без скрытых defaults."""

from __future__ import annotations

import datetime as dt
from dataclasses import asdict
from typing import Any

from app.sim.behavior.care import COMPONENTS, CareComponents, CareState


def dump_care(state: CareState) -> dict[str, Any]:
    return {
        "version": 1,
        "components": asdict(state.components),
        "first_reply_at": state.first_reply_at.isoformat() if state.first_reply_at else None,
        "tone_violated": state.tone_violated,
        "sla_breached": state.sla_breached,
    }


def load_care(raw: object) -> CareState:
    expected = {"version", "components", "first_reply_at", "tone_violated", "sla_breached"}
    if not isinstance(raw, dict) or set(raw) != expected or type(raw["version"]) is not int or raw["version"] != 1:
        raise ValueError("неподдерживаемый или неполный care snapshot")
    values = raw["components"]
    if not isinstance(values, dict) or set(values) != COMPONENTS:
        raise ValueError("нужны ровно шесть typed care components")
    at = raw["first_reply_at"]
    if at is not None and not isinstance(at, str):
        raise ValueError("first_reply_at должен быть ISO timestamp или null")
    return CareState(
        CareComponents(**values),
        dt.datetime.fromisoformat(at) if at is not None else None,
        raw["tone_violated"],
        raw["sla_breached"],
    )
