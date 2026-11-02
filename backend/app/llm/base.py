"""Единый интерфейс LLM-провайдеров (AGENTS §6.3): complete_structured / stream, профиль, usage, ошибки."""

from __future__ import annotations

from collections.abc import AsyncIterator
from dataclasses import dataclass, field
from typing import Any, Literal, Protocol, TypedDict

ProviderKind = Literal["gigachat", "openai_compatible", "replay", "mock"]
ErrorKind = Literal["auth", "rate_limit", "quota", "timeout", "network", "bad_output", "miss", "unavailable"]
Context = Literal["normalization", "fast_path", "detector", "batch", "default"]
TIMEOUTS_S: dict[str, float] = {
    "normalization": 10.0,
    "fast_path": 8.0,
    "detector": 5.0,
    "batch": 12.0,
    "default": 30.0,
}


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
    # Внутренний учёт benchmark; публичная схема usage.as_dict не меняется.
    request_count: int = 1
    structured_retries: int = 0
    json_valid_first_try: bool = True

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


def binding_fields(api_key_id: int | None, extra: dict[str, Any]) -> tuple[int | None, dict[str, Any]]:
    """Read compatibility старого bench extra.api_key_id; новые writes используют поле API."""
    if api_key_id is not None and (type(api_key_id) is not int or api_key_id < 1):
        raise ValueError("api_key_id должен быть положительным целым числом")
    if not isinstance(extra, dict):
        raise ValueError("extra должен быть объектом")
    if "api_key_id" not in extra:
        return api_key_id, extra
    legacy = extra["api_key_id"]
    if (
        isinstance(legacy, bool)
        or not isinstance(legacy, int)
        or legacy < 1
        or (api_key_id is not None and api_key_id != legacy)
    ):
        raise ValueError("неоднозначная legacy credential binding")
    return legacy, {key: value for key, value in extra.items() if key != "api_key_id"}


@dataclass(slots=True)
class LLMProfile:
    """Строка llm_profiles (или значения по умолчанию из .env)."""

    code: str
    provider: ProviderKind
    model: str
    role: Literal["main", "fast", "twin", "bench_only"] = "main"
    base_url: str | None = None
    api_key_id: int | None = None
    temperature: float = 0.0
    rpm_limit: int | None = None
    rpd_limit: int | None = None
    price_in_per_1m: float = 0.0
    price_out_per_1m: float = 0.0
    supports_tools: bool = True
    supports_stream: bool = True
    extra: dict[str, Any] = field(default_factory=dict)
    id: int | None = None  # Стабильный public config ID для live quota, не credential identity.

    def __post_init__(self) -> None:
        if self.id is not None and (type(self.id) is not int or self.id < 1):
            raise ValueError("ID профиля должен быть положительным целым числом")
        self.api_key_id, self.extra = binding_fields(self.api_key_id, self.extra)

    def cost(self, prompt: int, completion: int) -> float:
        return prompt / 1e6 * self.price_in_per_1m + completion / 1e6 * self.price_out_per_1m


class ProviderError(Exception):
    def __init__(
        self,
        kind: ErrorKind,
        detail: str = "",
        *,
        retry_after_s: float | None = None,
        status: int | None = None,
        usage: Usage | None = None,
        request_count: int = 0,
    ):
        super().__init__(f"{kind}: {detail}" if detail else kind)
        self.kind: ErrorKind = kind
        self.detail = detail
        self.retry_after_s = retry_after_s
        self.status = status
        self.usage = usage
        # Существующий adapter generation-attempt counter, не all-HTTP ledger.
        self.request_count = request_count


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
