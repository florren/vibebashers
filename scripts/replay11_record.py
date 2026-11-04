# ruff: noqa: E402, T201
"""Prepare offline plan or execute one separately approved bounded live recording.

Uses existing ledger/profile/caps and a fresh dedicated synthetic bank. No reset,
reconciliation, provider fallback or automatic publication of staging responses.
"""

from __future__ import annotations

import argparse
import asyncio
import datetime as dt
import json
import os
import sys
import time
import uuid
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT / "backend"), str(ROOT)]

import httpx
import psycopg
from app.config import get_settings
from app.contracts.registry import deref
from app.db.session import psycopg_dsn
from app.llm.accounting import KeyFacts, PostgresAccounting
from app.llm.accounting_cli import selection
from app.llm.base import LLMProfile
from app.llm.gigachat import GigaChatProvider
from app.llm.keys import ApiKey, KeyPool
from app.llm.mock import MockProvider
from app.llm.tls import context as tls_context
from app.replay.scenario11_record import (
    BASE,
    MODEL,
    OAUTH,
    SCHEMAS,
    BoundedTransport,
    digest,
    manifest,
    record,
    recording_profile,
)
from psycopg.conninfo import conninfo_to_dict

from scripts.replay11_bank import configure_profile, seed_bank


def parser() -> argparse.ArgumentParser:
    cli = argparse.ArgumentParser(description=__doc__)
    cli.add_argument("action", choices=("prepare", "live"))
    cli.add_argument("--bank-dsn-file", type=Path, required=True)
    cli.add_argument("--output", type=Path, required=True)
    cli.add_argument("--plan", type=Path)
    cli.add_argument("--approved-plan-sha256")
    cli.add_argument("--profile-id", type=int)
    return cli


async def warm_recording_provider(provider: GigaChatProvider, profile: LLMProfile) -> None:
    """Штатный startup греет OAuth и API host; фон не получает дополнительных HTTP."""
    if len(provider.pool.keys) != 1:
        raise ValueError("reviewed_single_key_required")
    try:
        ready = await provider.prepare([profile], timeout_s=12)
    finally:
        await provider.stop_auth_refresh()
    key = provider.pool.keys[0]
    if not ready or not key.access_token or key.token_expires_at <= time.time() + 180:
        raise ValueError("bounded_provider_startup_failed")


async def execute(args: argparse.Namespace) -> dict[str, Any]:
    os.umask(0o077)
    bank_dsn = json.loads(args.bank_dsn_file.read_text())["dsn"]
    if args.output.exists():
        raise ValueError("output_already_exists")
    if args.action == "prepare":
        # Private fake-only maintenance namespace; never alter the running application's marker.
        control = args.output.parent / (args.output.name + ".fake-maintenance")
        control.mkdir(parents=True, exist_ok=False)
        os.environ["MAINTENANCE_CONTROL_DIR"] = str(control)
        os.environ["ENV_FILE"] = "/dev/null"
        os.environ["DATABASE_URL"] = bank_dsn.replace("postgresql://", "postgresql+psycopg://", 1)
        os.environ["LLM_PROVIDER"] = "gigachat"
        get_settings.cache_clear()
        from app.sim.maintenance_control import MaintenanceControl

        MaintenanceControl().write("idle")
    reviewed = manifest()
    if args.action == "live":
        if not args.plan or not args.approved_plan_sha256 or not args.profile_id:
            raise ValueError("reviewed_plan_and_profile_required")
        plan = json.loads(args.plan.read_text())
        if digest(plan) != args.approved_plan_sha256 or plan["manifest"] != reviewed:
            raise ValueError("reviewed_plan_changed")
        profile, facts = await selection(
            argparse.Namespace(profile_id=args.profile_id, key_id=None, env_slot="gigachat1")
        )
        assert facts.secret
        secret = facts.secret
        settings = get_settings()
        if settings.gigachat_oauth_url != OAUTH or settings.gigachat_base_url.rstrip("/") != BASE:
            raise ValueError("reviewed_endpoints_changed")
        inner = httpx.AsyncHTTPTransport(verify=tls_context(settings.gigachat_ca_bundle_file))
        key = ApiKey("gigachat_env_1", secret, tokens_limit=facts.tokens_limit)
    else:
        # No network transport exists in prepare. Fake files stay in FAKE-DO-NOT-PUBLISH.
        secret = "synthetic-offline-replay11-" + uuid.uuid4().hex
        profile = LLMProfile(
            code="replay11-fake-" + uuid.uuid4().hex,
            provider="gigachat",
            model=MODEL,
            base_url=BASE,
            temperature=0,
            rpd_limit=6,
        )
        key = ApiKey("fake", secret, tokens_limit=100000)
        calls = 0

        async def handler(request: httpx.Request) -> httpx.Response:
            nonlocal calls
            if str(request.url) == OAUTH:
                return httpx.Response(
                    200,
                    json={
                        "access_token": "synthetic-replay11-token",
                        "expires_at": int((dt.datetime.now(dt.UTC).timestamp() + 3600) * 1000),
                    },
                )
            if str(request.url) == BASE + "/models":
                return httpx.Response(200, json={"data": [{"id": MODEL}]})
            if request.method == "GET":
                return httpx.Response(200, json={"balance": [{"usage": "GigaChat-Pro", "value": 100000}]})
            body = json.loads(request.content)
            schema = deref(SCHEMAS[calls])
            calls += 1
            obj, _, _ = await MockProvider().complete_structured(body["messages"], schema, profile, timeout_s=5)
            return httpx.Response(
                200,
                json={
                    "model": MODEL,
                    "choices": [
                        {
                            "message": {
                                "role": "assistant",
                                "content": json.dumps(obj, ensure_ascii=False),
                            }
                        }
                    ],
                    "usage": {
                        "prompt_tokens": 10,
                        "completion_tokens": 20,
                        "total_tokens": 30,
                    },
                },
            )

        inner = httpx.MockTransport(handler)
    async with await psycopg.AsyncConnection.connect(bank_dsn) as bank:
        row = await (await bank.execute("select current_database()")).fetchone()
        if not row or not row[0].startswith("cx_replay11_"):
            raise ValueError("dedicated_cx_replay11_bank_required")
        await seed_bank(bank, bank_dsn)
        profile = await configure_profile(bank, recording_profile(profile))
        if args.action == "live" and conninfo_to_dict(psycopg_dsn()).get("dbname") == row[0]:
            raise ValueError("bank_must_differ_from_durable_accounting_database")
        if args.action == "prepare":
            os.environ["DATABASE_URL"] = bank_dsn.replace("postgresql://", "postgresql+psycopg://", 1)
            os.environ["LLM_PROVIDER"] = "gigachat"
            get_settings.cache_clear()
            await PostgresAccounting().connect_gigachat(
                profile, KeyFacts("gigachat", secret, BASE, 100000), {"GigaChat-Pro": 100000}, confirmed=True
            )
        transport = BoundedTransport(inner, secret=secret)
        provider = GigaChatProvider(KeyPool([key]), oauth_url=OAUTH, base_url=BASE, transport=transport)
        try:
            if args.action == "live":
                marker = args.plan.with_name(".replay11-" + args.approved_plan_sha256 + ".started.json")
                descriptor = os.open(marker, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
                with os.fdopen(descriptor, "w") as stream:
                    json.dump(
                        {
                            "approved_plan_sha256": args.approved_plan_sha256,
                            "started_at": dt.datetime.now(dt.UTC).isoformat(),
                            "retry_requires_new_approval": True,
                        },
                        stream,
                    )
            async with asyncio.timeout(120):
                await warm_recording_provider(provider, profile)
                proof = await record(
                    bank,
                    provider,
                    transport,
                    profile,
                    args.output,
                    fake_transport=args.action == "prepare",
                )
        finally:
            await provider.aclose()
    if args.action == "prepare":
        result = {
            "manifest": reviewed,
            "preview_transport": "FAKE; dependent requests are previews, NOT live fingerprints",
            "preview_requests": proof["requests"],
            "preview_payloads": proof["payloads"],
            "http_counts": proof["http_counts"],
        }
        (args.output / "plan.json").write_text(json.dumps(result, ensure_ascii=False, indent=2, default=str))
        return {
            "status": "PASS",
            "fake_http_only": True,
            "plan_sha256": digest(result),
            "plan_file": str(args.output / "plan.json"),
            "http_counts": proof["http_counts"],
        }
    return {
        "status": "PASS",
        "fake_http_only": False,
        "http_counts": proof["http_counts"],
        "staging": str(args.output),
    }


def main() -> int:
    args = parser().parse_args()
    try:
        result = asyncio.run(execute(args))
    except Exception as exc:  # noqa: BLE001 - CLI privacy boundary; raw PG/provider errors never printed.
        print(json.dumps({"status": "FAIL", "error_type": type(exc).__name__}))
        return 1
    print(json.dumps(result, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
