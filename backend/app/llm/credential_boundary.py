"""Credential отражённый upstream не становится model response/публичной диагностикой."""

from __future__ import annotations

import json
import math
from collections.abc import Iterable
from typing import Any

from app.llm.base import ProviderError

REFLECTION = "провайдер отразил credential; ответ отклонён"


def reject_reflection(value: Any, secrets: Iterable[str | None]) -> None:
    selected = tuple(secret for secret in secrets if secret)
    if not selected:
        return
    pending = [(value, 0)]
    while pending:
        item, depth = pending.pop()
        if isinstance(item, str):
            if any(secret in item for secret in selected):
                raise ProviderError("bad_output", REFLECTION, status=200)
            # JSON escaping внутри content не должен обходить exact-secret проверку.
            if depth < 8 and item.lstrip().startswith(("{", "[", '"')):
                try:
                    decoded = json.loads(item)
                except ValueError:
                    continue
                pending.append((decoded, depth + 1))
        elif isinstance(item, dict):
            pending.extend((child, depth + 1) for child in item.values())
            pending.extend((key, depth + 1) for key in item)
        elif isinstance(item, list | tuple):
            pending.extend((child, depth + 1) for child in item)


class CredentialStreamGuard:
    """Не выдаёт префикс известного credential, пока следующий chunk не снимет неоднозначность."""

    def __init__(self, secrets: Iterable[str | None]) -> None:
        self.secrets = tuple(secret for secret in secrets if secret)
        self.pending = ""

    def feed(self, chunk: str) -> str:
        value = self.pending + chunk
        reject_reflection(value, self.secrets)
        keep = max(
            (
                size
                for secret in self.secrets
                for size in range(1, min(len(secret), len(value) + 1))
                if value.endswith(secret[:size])
            ),
            default=0,
        )
        self.pending = value[-keep:] if keep else ""
        return value[:-keep] if keep else value

    def finish(self) -> str:
        value, self.pending = self.pending, ""
        reject_reflection(value, self.secrets)
        return value


def retry_after(value: str | None) -> float:
    try:
        parsed = float(value) if value is not None else 20.0
    except ValueError:
        return 20.0
    return parsed if math.isfinite(parsed) and parsed >= 0 else 20.0
