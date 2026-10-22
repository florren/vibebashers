"""Единый интерфейс LLM-провайдеров (AGENTS §6.3): complete_structured / stream, профиль, usage, ошибки."""

from __future__ import annotations

from collections.abc import AsyncIterator
from dataclasses import dataclass, field
from typing import Any, Literal, Protocol, TypedDict

ProviderKind = Literal["gigachat", "openai_compatible", "replay", "mock"]
ErrorKind = Literal["auth", "rate_limit", "quota", "timeout", "network", "bad_output", "miss", "unavailable"]
Context = Literal["fast_path", "detector", "default"]
TIMEOUTS_S: dict[str, float] = {"fast_path": 8.0, "detector": 2.0, "default": 30.0}


class Message(TypedDict):
    role: Literal["system", "user", "assistant"]
    content: str


@dataclass(slots=True)
class Usage:
    prompt_tokens: int = 0
    completion_tokens: int = 0
    latency_ms: int = 0
    cost_rub: float = 0.0
    provider: str = ""
    model: str = ""
    source: Literal["live", "replay", "mock"] = "live"
    key_label: str | None = None

    @property
    def total_tokens(self) -> int:
        return self.prompt_tokens + self.completion_tokens

    def as_dict(self) -> dict[str, Any]:
        return {
            "prompt_tokens": self.prompt_tokens,
            "completion_tokens": self.completion_tokens,
            "total_tokens": self.total_tokens,
            "latency_ms": self.latency_ms,
            "cost_rub": round(self.cost_rub, 6),
            "provider": self.provider,
            "model": self.model,
            "source": self.source,
            "key_label": self.key_label,
        }


@dataclass(slots=True)
class LLMProfile:
    """Строка llm_profiles (или значения по умолчанию из .env)."""

    code: str
    provider: ProviderKind
    model: str
    role: Literal["main", "fast", "twin", "bench_only"] = "main"
    base_url: str | None = None
    temperature: float = 0.0
    rpm_limit: int | None = None
    rpd_limit: int | None = None
    price_in_per_1m: float = 0.0
    price_out_per_1m: float = 0.0
    supports_tools: bool = True
    supports_stream: bool = True
    extra: dict[str, Any] = field(default_factory=dict)

    def cost(self, prompt: int, completion: int) -> float:
        return prompt / 1e6 * self.price_in_per_1m + completion / 1e6 * self.price_out_per_1m


class ProviderError(Exception):
    def __init__(
        self, kind: ErrorKind, detail: str = "", *, retry_after_s: float | None = None, status: int | None = None
    ):
        super().__init__(f"{kind}: {detail}" if detail else kind)
        self.kind: ErrorKind = kind
        self.detail = detail
        self.retry_after_s = retry_after_s
        self.status = status


class Provider(Protocol):
    name: str

    async def complete_structured(
        self, messages: list[Message], schema: dict[str, Any], profile: LLMProfile, *, timeout_s: float
    ) -> tuple[dict[str, Any], Usage, str]: ...

    def stream(self, messages: list[Message], profile: LLMProfile, *, timeout_s: float) -> AsyncIterator[str]: ...


def normalize_messages(messages: list[Message]) -> list[dict[str, str]]:
    """Нормализация для ключа кассеты: роли/тексты без хвостовых пробелов, схлопнутые пробелы."""
    out = []
    for m in messages:
        out.append({"role": m["role"], "content": " ".join(str(m["content"]).split())})
    return out


def extract_json(text: str) -> dict[str, Any]:
    """Достаёт первый JSON-объект из ответа модели (учитывает ```json-блоки и мусор вокруг)."""
    import json

    t = text.strip()
    if t.startswith("```"):
        t = t.split("\n", 1)[1] if "\n" in t else t[3:]
        t = t.rsplit("```", 1)[0]
    try:
        obj = json.loads(t)
        if isinstance(obj, dict):
            return obj
    except json.JSONDecodeError:
        pass
    start = t.find("{")
    depth = 0
    for i in range(start, len(t)) if start >= 0 else []:
        if t[i] == "{":
            depth += 1
        elif t[i] == "}":
            depth -= 1
            if depth == 0:
                try:
                    obj = json.loads(t[start : i + 1])
                except json.JSONDecodeError:
                    break
                if isinstance(obj, dict):
                    return obj
                break
    raise ProviderError("bad_output", f"в ответе нет JSON-объекта: {text[:120]!r}")
