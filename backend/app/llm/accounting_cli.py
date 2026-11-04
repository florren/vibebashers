"""T-050: operator reconciliation / metadata-only GigaChat connect; no raw credentials in argv/output."""

from __future__ import annotations

import argparse
import asyncio
import datetime as dt
import json
import sys
import uuid
from dataclasses import replace
from typing import Any, Never

import psycopg
from psycopg.rows import dict_row

from app.config import get_settings
from app.db.session import psycopg_dsn
from app.llm import accounting, credentials
from app.llm.base import LLMProfile, ProviderError
from app.llm.openai_compat import OpenAICompatProvider
from app.sim.maintenance import MaintenanceBusy


class SafeParser(argparse.ArgumentParser):
    def error(self, message: str) -> Never:
        # argparse normally echoes the rejected value, which may be a mistyped key.
        self.exit(2, "Неверные параметры. Используйте --help; ввод не выводится.\n")


def parser() -> argparse.ArgumentParser:
    cli = SafeParser(description="Учёт LLM: status/reconcile; connect-gigachat читает OAuth/balance, без inference.")
    cli.add_argument("action", choices=("status", "reconcile", "connect-gigachat"))
    cli.add_argument("--profile-id", type=int, required=True)
    source = cli.add_mutually_exclusive_group(required=True)
    source.add_argument("--key-id", type=int)
    source.add_argument("--env-slot", choices=("gigachat1", "gigachat2", "openrouter", "local"))
    cli.add_argument("--reconciliation-id", type=uuid.UUID)
    cli.add_argument("--as-of", type=dt.datetime.fromisoformat)
    cli.add_argument("--tokens-used", type=int)
    cli.add_argument("--requests-today", type=int)
    cli.add_argument("--profile-requests-today", type=int)
    cli.add_argument("--confirm", action="store_true")
    cli.add_argument("--reviewed-unknown-origin", action="store_true")
    cli.add_argument("--acknowledge-orphans", action="store_true")
    return cli


async def selection(args: argparse.Namespace) -> tuple[LLMProfile, accounting.KeyFacts]:
    if args.profile_id < 1 or (args.key_id is not None and args.key_id < 1):
        raise ProviderError("bad_output", "configuration ID должен быть положительным")
    async with await psycopg.AsyncConnection.connect(psycopg_dsn(), autocommit=True, row_factory=dict_row) as conn:
        row = await (
            await conn.execute("select * from llm_profiles where id=%s and is_active", (args.profile_id,))
        ).fetchone()
        if row is None:
            raise ProviderError("quota", "активный профиль отсутствует")
        profile = LLMProfile(**{name: row[name] for name in LLMProfile.__dataclass_fields__ if name in row})
        if profile.provider not in ("gigachat", "openai_compatible"):
            raise ProviderError("bad_output", "offline profile не нуждается в physical wire reconciliation")
        base = credentials.endpoint(profile.base_url or credentials.default_endpoint(profile.provider))
        if args.key_id is not None:
            if profile.api_key_id not in (None, args.key_id):
                raise ProviderError("auth", "explicit profile binding не совпадает с выбранным key ID")
            profile = replace(profile, api_key_id=args.key_id)
            item = await credentials.validate_binding(conn, profile, reveal=True)
            assert item is not None
            return profile, accounting.KeyFacts(
                profile.provider,
                item["_secret"],
                base,
                item["tokens_limit"],
                item["rpd_limit"],
                db_id=args.key_id,
                paid=profile.provider == "openai_compatible" and OpenAICompatProvider._paid(profile, base),
            )
        if profile.api_key_id is not None:
            raise ProviderError("auth", "bound profile не допускает env source")
        settings = get_settings()
        slots = {
            "gigachat1": ("gigachat", settings.gigachat_auth_key_1),
            "gigachat2": ("gigachat", settings.gigachat_auth_key_2),
            "openrouter": ("openai_compatible", settings.openrouter_api_key),
            "local": ("openai_compatible", settings.local_llm_api_key),
        }
        provider, secret = slots[args.env_slot]
        if provider != profile.provider or (not secret and args.env_slot != "local"):
            raise ProviderError("auth", "env source отсутствует или не соответствует профилю")
        if args.env_slot == "local":
            local = credentials.endpoint(settings.local_llm_base_url or "")
            if base != local:
                raise ProviderError("auth", "local env source не разрешён для endpoint профиля")
        elif args.env_slot == "openrouter" and base != credentials.endpoint(settings.openrouter_base_url):
            raise ProviderError("auth", "OpenRouter env source не разрешён для endpoint профиля")
        elif provider == "gigachat" and base != credentials.endpoint(settings.gigachat_base_url):
            raise ProviderError("auth", "GigaChat env source не разрешён для endpoint профиля")
        from app.llm.keys import DEFAULT_LIMIT

        return profile, accounting.KeyFacts(
            profile.provider,
            secret,
            base,
            tokens_limit=DEFAULT_LIMIT if provider == "gigachat" else None,
            paid=profile.provider == "openai_compatible" and OpenAICompatProvider._paid(profile, base),
        )


async def execute(args: argparse.Namespace) -> dict[str, Any]:
    if args.action == "reconcile":
        required = (
            args.reconciliation_id,
            args.as_of,
            args.tokens_used,
            args.requests_today,
            args.profile_requests_today,
        )
        if any(item is None for item in required) or not args.confirm or not args.reviewed_unknown_origin:
            raise ProviderError(
                "bad_output", "reconcile требует всех observation fields, --confirm и --reviewed-unknown-origin"
            )
    profile, facts = await selection(args)
    service = accounting.service()
    if args.action == "connect-gigachat":
        if not args.confirm or facts.provider != "gigachat" or not facts.secret:
            raise ProviderError("bad_output", "connect-gigachat требует GigaChat credential и --confirm")
        from app.llm.gigachat import GigaChatProvider
        from app.llm.keys import ApiKey, KeyPool

        settings = get_settings()
        key = ApiKey(label="connect", secret=facts.secret)
        provider = GigaChatProvider(
            KeyPool([key]),
            oauth_url=settings.gigachat_oauth_url,
            base_url=facts.endpoint or settings.gigachat_base_url,
            scope=settings.gigachat_scope,
            ca_bundle_file=settings.gigachat_ca_bundle_file,
        )
        try:
            async with asyncio.timeout(20):
                balances = await provider.fetch_balance(key, profile, timeout_s=15)
                return await service.connect_gigachat(profile, facts, balances, confirmed=True)
        finally:
            await provider.aclose()
    if args.action == "status":
        snapshot = await service.snapshot(profile, facts, timeout_s=20)
        return {
            **snapshot.public(),
            "admission_allowed": snapshot.refusal is None,
            "refusal_kind": snapshot.refusal.kind if snapshot.refusal else None,
        }
    return await service.reconcile(
        profile,
        facts,
        reconciliation_id=args.reconciliation_id,
        as_of=args.as_of,
        tokens_used=args.tokens_used,
        requests_today=args.requests_today,
        profile_requests={f"id:{profile.id}": args.profile_requests_today},
        confirmed=args.confirm,
        acknowledge_unknown_origin=args.reviewed_unknown_origin,
        acknowledge_orphans=args.acknowledge_orphans,
    )


def main() -> int:
    args = parser().parse_args()
    try:
        result = asyncio.run(execute(args))
    except (ProviderError, credentials.CredentialBindingError, MaintenanceBusy) as exc:
        # Only reviewed constant diagnostics; no SQL/credential/DSN/request values.
        result = {"ok": False, "error": exc.kind if isinstance(exc, ProviderError) else "configuration_or_maintenance"}
        status = 2
    except Exception:
        result, status = {"ok": False, "error": "accounting_unavailable"}, 2
    else:
        status = 0
    sys.stdout.write(json.dumps(result, ensure_ascii=False, default=str) + "\n")
    return status


if __name__ == "__main__":
    raise SystemExit(main())
