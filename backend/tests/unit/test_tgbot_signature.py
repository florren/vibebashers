"""T-121: S2S подпись не допускает изменения адреса, тела и времени."""

from __future__ import annotations

import hashlib
import hmac

import pytest

from app.tgbot.signature import BotTransportDisabled, InvalidBotSignature, verify_signature

SECRET = b"public-test-vector-only-000000000000"
BODY = '{"chat_id":123,"text":"тест"}'.encode()
PATH = "/api/internal/tgbot/inbound"
STAMP = "1800000000"


def sign(body: bytes = BODY, timestamp: str = STAMP) -> str:
    payload = "\n".join(("cx-tgbot-v1", timestamp, "POST", PATH, hashlib.sha256(body).hexdigest())).encode()
    return hmac.new(SECRET, payload, hashlib.sha256).hexdigest()


@pytest.mark.parametrize("delta", [-60, 0, 60])
def test_valid_signature_window(delta):
    verify_signature(
        SECRET, method="POST", path=PATH, body=BODY, timestamp=STAMP, signature=sign(), now=int(STAMP) + delta
    )


@pytest.mark.parametrize(
    "changes",
    [
        {"body": BODY + b" "},
        {"body": b"x" * 32_769},
        {"path": PATH + "/other"},
        {"method": "DELETE"},
        {"now": int(STAMP) + 61},
        {"now": int(STAMP) - 61},
        {"now": float("nan")},
        {"now": float("inf")},
        {"signature": None},
        {"signature": "z" * 64},
        {"timestamp": "²"},
        {"timestamp": "١٨٠٠٠٠٠٠٠٠"},
        {"timestamp": "1" * 13},
        {"timestamp": ""},
        {"timestamp": None},
    ],
)
def test_invalid_signature_does_not_echo_input(changes):
    values = dict(method="POST", path=PATH, body=BODY, timestamp=STAMP, signature=sign(), now=int(STAMP))
    values.update(changes)
    with pytest.raises(InvalidBotSignature) as exc:
        verify_signature(SECRET, **values)
    assert str(exc.value) == "invalid_telegram_transport_signature"


@pytest.mark.parametrize("secret", [None, b"", b"x" * 31])
def test_disabled_secret_is_explicit(secret):
    with pytest.raises(BotTransportDisabled, match="^telegram_transport_not_configured$"):
        verify_signature(secret, method="POST", path=PATH, body=BODY, timestamp=STAMP, signature=sign(), now=int(STAMP))
