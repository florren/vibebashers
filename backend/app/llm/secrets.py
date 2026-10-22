"""Шифрование API-ключей в `settings` (T-009): HMAC-SHA256 в режиме счётчика + HMAC-тег поверх, ключ выводится из APP_SECRET.

Без внешних зависимостей (в проекте нет `cryptography`); для демо-стенда достаточно, в проде заменить на Fernet/KMS.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import os

_PREFIX = "enc1:"


def _kdf(secret: str) -> bytes:
    return hashlib.pbkdf2_hmac("sha256", secret.encode(), b"cx-pulse-llm-keys", 50_000, dklen=32)


def _stream(key: bytes, nonce: bytes, n: int) -> bytes:
    out = bytearray()
    ctr = 0
    while len(out) < n:
        out += hmac.new(key, nonce + ctr.to_bytes(4, "big"), hashlib.sha256).digest()
        ctr += 1
    return bytes(out[:n])


def encrypt(plain: str, secret: str) -> str:
    key = _kdf(secret)
    nonce = os.urandom(12)
    data = plain.encode()
    ct = bytes(a ^ b for a, b in zip(data, _stream(key, nonce, len(data)), strict=True))
    tag = hmac.new(key, nonce + ct, hashlib.sha256).digest()[:16]
    return _PREFIX + base64.urlsafe_b64encode(nonce + tag + ct).decode()


def decrypt(token: str, secret: str) -> str:
    if not token.startswith(_PREFIX):
        raise ValueError("не зашифрованный токен")
    raw = base64.urlsafe_b64decode(token[len(_PREFIX) :])
    nonce, tag, ct = raw[:12], raw[12:28], raw[28:]
    key = _kdf(secret)
    if not hmac.compare_digest(tag, hmac.new(key, nonce + ct, hashlib.sha256).digest()[:16]):
        raise ValueError("повреждённый ключ или другой APP_SECRET")
    return bytes(a ^ b for a, b in zip(ct, _stream(key, nonce, len(ct)), strict=True)).decode()


def hint(plain: str) -> str:
    return f"…{plain[-4:]}" if len(plain) >= 8 else "…"
