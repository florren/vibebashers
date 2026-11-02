"""Ephemeral poll proof: restart/rotation/timeout требуют нового signed heartbeat."""

from __future__ import annotations

import hashlib
import hmac
import json
import re
import time
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from app.tgbot.configuration import TransportConfiguration, configured

POLL_FRESH_SECONDS = 90.0
USERNAME = re.compile(r"[A-Za-z][A-Za-z0-9_]{4,31}\Z")


def valid_username(value: str) -> bool:
    return USERNAME.fullmatch(value) is not None and value.lower().endswith("bot")


def credential_ref(config: TransportConfiguration) -> str:
    return hmac.new(config.secret, b"cx-tgbot-credential-v1:" + config.token.encode(), hashlib.sha256).hexdigest()


def identity(config: TransportConfiguration) -> bytes:
    # Любое изменение transport config требует нового proof; digest не публикуется.
    material = json.dumps(
        [config.bot_id, config.token, config.secret.hex(), config.app_secret, config.public_origin],
        separators=(",", ":"),
    ).encode()
    return hashlib.sha256(material).digest()


@dataclass(frozen=True)
class PollProof:
    identity: bytes
    username: str
    received: float


class BotLiveness:
    def __init__(self, *, clock: Callable[[], float] = time.monotonic) -> None:
        self.clock = clock
        self.proof: PollProof | None = None

    def observe(self, config: TransportConfiguration, username: str) -> None:
        if not valid_username(username):
            raise ValueError("telegram_bot_username_invalid")
        self.proof = PollProof(identity(config), username, self.clock())

    def username(self, config: TransportConfiguration) -> str | None:
        proof = self.proof
        if proof is None or proof.identity != identity(config):
            return None
        elapsed = self.clock() - proof.received
        return proof.username if 0 <= elapsed < POLL_FRESH_SECONDS else None


def running_username(app: Any, settings: Any) -> str | None:
    try:
        config = configured(settings)
    except ValueError:
        return None
    worker = getattr(app.state, "tgbot_task", None)
    proof = getattr(app.state, "tgbot_liveness", None)
    if config is None or worker is None or worker.done() or not isinstance(proof, BotLiveness):
        return None
    return proof.username(config)
