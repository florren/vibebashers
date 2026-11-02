"""Подготовка explicit Telegram profile без shell-source .env и без вывода credentials."""

from __future__ import annotations

import argparse
import os
import re
import secrets
import sys
import tempfile
from pathlib import Path
from urllib.parse import urlsplit

LINE = re.compile(r"^\s*([A-Za-z_][A-Za-z0-9_]*)\s*=\s*(.*)$")


def values(text: str) -> dict[str, str]:
    result = {}
    for line in text.splitlines():
        match = LINE.match(line)
        if match:
            raw = match[2].strip()
            if len(raw) >= 2 and raw[0] in {"'", '"'} and raw.endswith(raw[0]):
                raw = raw[1:-1]
            else:
                raw = re.split(r"\s+#", raw, maxsplit=1)[0].strip()
            result[match[1]] = raw
    return result


def prepare(path: Path, *, enable: bool) -> None:
    if path.is_symlink():
        raise ValueError("telegram_env_symlink_not_supported")
    source = path.read_text()
    env = values(source)
    updates = {"TGBOT_ENABLED": "true" if enable else "false"}
    if enable:
        token = env.get("TELEGRAM_BOT_TOKEN", "")
        if re.fullmatch(r"[1-9][0-9]{0,18}:[A-Za-z0-9_-]{20,200}", token) is None:
            raise ValueError("telegram_token_missing_or_invalid")
        if len(env.get("APP_SECRET", "").encode()) < 32:
            raise ValueError("telegram_storage_secret_not_configured")
        origin = env.get("TGBOT_PUBLIC_BASE_URL", "").rstrip("/")
        try:
            url = urlsplit(origin)
            valid = (
                url.scheme in {"https", "http"}
                and bool(url.hostname)
                and not url.username
                and not url.password
                and not url.path
                and not url.query
                and not url.fragment
                and url.port != 0
            )
        except ValueError:
            valid = False
        if not valid:
            raise ValueError("telegram_public_origin_missing_or_invalid")
        secret = env.get("TGBOT_INTERNAL_SECRET", "")
        if not secret:
            updates["TGBOT_INTERNAL_SECRET"] = secrets.token_urlsafe(32)
        elif len(secret.encode()) < 32:
            raise ValueError("telegram_internal_secret_too_short")
    output, seen = [], set()
    for line in source.splitlines():
        match = LINE.match(line)
        key = match[1] if match else None
        if key in updates:
            if key not in seen:
                output.append(f"{key}={updates[key]}")
                seen.add(key)
        else:
            output.append(line)
    output.extend(f"{key}={value}" for key, value in updates.items() if key not in seen)
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w", dir=path.parent, delete=False
        ) as stream:
            temporary = Path(stream.name)
            os.chmod(temporary, 0o600)
            stream.write("\n".join(output) + "\n")
            stream.flush()
            os.fsync(stream.fileno())
        temporary.replace(path)
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--env-file", type=Path, default=Path(".env"))
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--enable", action="store_true")
    mode.add_argument("--disable", action="store_true")
    args = parser.parse_args()
    try:
        prepare(args.env_file, enable=args.enable)
    except (ValueError, OSError) as exc:
        code = (
            str(exc) if isinstance(exc, ValueError) else "telegram_env_file_unavailable"
        )
        sys.stderr.write(code + "\n")
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
