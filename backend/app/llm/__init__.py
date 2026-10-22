"""LLM-слой (AGENTS §6.3): base, mock, gigachat, openai_compat, keys, ratelimit, failover; replay — в app/replay."""

from app.llm.base import LLMProfile, Message, Provider, ProviderError, Usage
from app.llm.failover import ChainResult, ProviderChain, build_chain, default_profile

__all__ = [
    "ChainResult",
    "LLMProfile",
    "Message",
    "Provider",
    "ProviderError",
    "ProviderChain",
    "Usage",
    "build_chain",
    "default_profile",
]
