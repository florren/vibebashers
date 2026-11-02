"""Credential отражённый upstream не становится model response/публичной диагностикой."""

from __future__ import annotations

import json
import math
from collections.abc import Iterable
from typing import Any

from app.llm.base import LLMProfile, ProviderError, Usage, extract_json

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
            # Те же JSON/codefence форматы, которые разбирает model output boundary.
            if depth < 8:
                candidate = item.strip()
                if candidate.startswith("```"):
                    candidate = candidate.split("\n", 1)[1] if "\n" in candidate else candidate[3:]
                    candidate = candidate.rsplit("```", 1)[0]
                try:
                    decoded = json.loads(candidate)
                except ValueError:
                    try:
                        decoded = extract_json(candidate)
                    except ProviderError:
                        continue
                pending.append((decoded, depth + 1))
        elif isinstance(item, dict):
            pending.extend((child, depth + 1) for child in item.values())
            pending.extend((key, depth + 1) for key in item)
        elif isinstance(item, list | tuple):
            pending.extend((child, depth + 1) for child in item)


STRUCTURED_STREAM_LIMIT = 64 * 1024


class CredentialStreamGuard:
    """Plain text: rolling prefix; JSON/codefence: bounded buffer до безопасного complete."""

    def __init__(self, secrets: Iterable[str | None]) -> None:
        self.secrets = tuple(secret for secret in secrets if secret)
        self.pending = ""
        self.structured: str | None = None
        self.structured_bytes = 0

    def _hold(self, value: str) -> int:
        return max(
            [
                size
                for secret in self.secrets
                for size in range(1, min(len(secret), len(value) + 1))
                if value.endswith(secret[:size])
            ]
            + [size for size in (1, 2) if value.endswith("`" * size)],
            default=0,
        )

    def _append(self, chunk: str) -> None:
        try:
            size = len(chunk.encode("utf-8"))
        except UnicodeError:
            raise ProviderError("bad_output", "stream содержит некорректный UTF-8") from None
        if self.structured_bytes + size > STRUCTURED_STREAM_LIMIT:
            raise ProviderError("bad_output", "structured stream превышает 64KiB")
        self.structured_bytes += size
        overlap = max((len(secret) for secret in self.secrets), default=1) - 1
        probe = ((self.structured or "")[-overlap:] if overlap else "") + chunk
        if any(secret in probe for secret in self.secrets):
            raise ProviderError("bad_output", REFLECTION, status=200)
        self.structured = (self.structured or "") + chunk

    @staticmethod
    def _marker(value: str) -> int | None:
        found = []
        fence = value.find("```")
        if fence >= 0:
            found.append(fence)
        for index, char in enumerate(value):
            if char not in '{["':
                continue
            if char == '"':
                found.append(index)
                break
            rest = value[index + 1 :].lstrip()
            allowed = '"}' if char == "{" else '"{}[]-0123456789'
            if (
                not rest
                or rest[0] in allowed
                or (
                    char == "["
                    and any(word.startswith(rest) or rest.startswith(word) for word in ("true", "false", "null"))
                )
            ):
                found.append(index)
                break
        return min(found) if found else None

    def feed(self, chunk: str) -> str:
        if not self.secrets:
            return chunk
        if self.structured is not None:
            self._append(chunk)
            return ""
        value = self.pending + chunk
        marker = self._marker(value)
        if marker is not None:
            prefix = value[:marker]
            reject_reflection(prefix, self.secrets)
            keep = self._hold(prefix)
            before = prefix[:-keep] if keep else prefix
            self.pending = ""
            self.structured = ""
            self._append((prefix[-keep:] if keep else "") + value[marker:])
            return before
        reject_reflection(value, self.secrets)
        keep = self._hold(value)
        self.pending = value[-keep:] if keep else ""
        return value[:-keep] if keep else value

    def finish(self) -> str:
        value = self.structured if self.structured is not None else self.pending
        self.pending, self.structured, self.structured_bytes = "", None, 0
        reject_reflection(value, self.secrets)
        return value


def observe_stream_usage(
    previous: Usage | None, raw: Any, profile: LLMProfile, provider: str, key_label: str | None = None
) -> Usage | None:
    """Сохраняет только подтверждённые cumulative counts; отсутствующее usage не становится нулём."""
    if not isinstance(raw, dict) or any(
        type(raw.get(key)) is not int or raw[key] < 0 for key in ("prompt_tokens", "completion_tokens")
    ):
        return previous
    prompt = max(previous.prompt_tokens if previous else 0, raw["prompt_tokens"])
    completion = max(previous.completion_tokens if previous else 0, raw["completion_tokens"])
    return Usage(
        prompt_tokens=prompt,
        completion_tokens=completion,
        cost_rub=profile.cost(prompt, completion),
        provider=provider,
        model=profile.model,
        key_label=key_label,
    )


def retry_after(value: str | None) -> float:
    try:
        parsed = float(value) if value is not None else 20.0
    except ValueError:
        return 20.0
    return parsed if math.isfinite(parsed) and parsed >= 0 else 20.0
