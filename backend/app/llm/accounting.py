"""T-050: private operational inference ledger; bank restore never refunds quota.

No prompts/responses/credential bytes are stored. Identity uses a private keyed
verifier; changing APP_SECRET requires reviewed migration, never a silent reset.
"""

from __future__ import annotations

import asyncio
import contextlib
import datetime as dt
import hmac
import time
import uuid
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from dataclasses import dataclass, field
from typing import Any

import psycopg
from psycopg.rows import dict_row
from psycopg.types.json import Jsonb

from app.config import get_settings
from app.db.session import psycopg_dsn
from app.llm import credentials
from app.llm.base import LLMProfile, ProviderError
from app.llm.credential_boundary import reject_reflection
from app.logging import get_logger
from app.sim.maintenance import MaintenanceBusy
from app.sim.maintenance_db import public_operation

log = get_logger(__name__)
MAX_COUNTER = 2**63 - 1
SOURCE = "operator_declared_app_usage"


class AdmissionRefused(ProviderError):
    """Local accounting refusal is not an upstream auth/quota health observation."""


def _counter(value: Any) -> int:
    if type(value) is not int or not 0 <= value <= MAX_COUNTER:
        raise AdmissionRefused("bad_output", "счётчик расхода должен быть неотрицательным bigint")
    return value


def _mac(domain: bytes, value: str) -> bytes:
    return hmac.digest(get_settings().app_secret.encode(), domain + b"\0" + value.encode(), "sha256")


def _profile_scope(profile: LLMProfile) -> str:
    return f"id:{profile.id}" if profile.id is not None else f"code:{profile.code}"


async def _resolve_profile_scope(conn: psycopg.AsyncConnection[Any], ref: str) -> str:
    if ref.startswith("id:"):
        raw = ref[3:]
        if not raw.isascii() or not raw.isdigit() or int(raw) < 1:
            raise AdmissionRefused("bad_output", "неверный profile reference")
        row = await (await conn.execute("select quota_uid from llm_profiles where id=%s", (int(raw),))).fetchone()
        if row is None:
            raise AdmissionRefused("quota", "configuration профиля отсутствует")
        return f"quota:{row['quota_uid']}"
    if not ref.startswith("code:") or not ref[5:] or len(ref) > 100:
        raise AdmissionRefused("bad_output", "неверный profile reference")
    return ref


async def _utc_now(conn: psycopg.AsyncConnection[Any]) -> dt.datetime:
    row = await (await conn.execute("select clock_timestamp() as value")).fetchone()
    assert row is not None
    value: dt.datetime = row["value"]
    return value.astimezone(dt.UTC)


def _minimum(*values: int | None) -> int | None:
    present = [_counter(value) for value in values if value is not None]
    return min(present) if present else None


def _unavailable(exc: Exception) -> ProviderError:
    # Raw PG diagnostics can contain verifier/UID values; never log str(exc).
    log.warning("llm_accounting_unavailable", error_type=type(exc).__name__)
    return AdmissionRefused("quota", "учёт лимита недоступен; новый вызов запрещён")


@dataclass(frozen=True)
class KeyFacts:
    provider: str
    secret: str | None = field(repr=False)
    endpoint: str | None
    tokens_limit: int | None = None
    rpd_limit: int | None = None
    db_id: int | None = None
    paid: bool = False

    def verifier(self) -> bytes:
        if not self.secret and not self.endpoint:
            raise AdmissionRefused("auth", "для anonymous accounting требуется endpoint")
        identity = self.secret if self.secret else f"anonymous:{credentials.endpoint(self.endpoint or '')}"
        return _mac(b"cx.llm.credential.v1", f"{self.provider}\0{identity}")


@dataclass(frozen=True)
class BudgetSnapshot:
    tokens_used: int
    usage_known: bool
    requests_today: int
    requests_known: bool
    requests_day: dt.date
    usage_source: str
    usage_as_of: dt.datetime | None
    tokens_remaining: int | None
    requests_remaining: int | None
    refusal: ProviderError | None = field(default=None, repr=False)

    def public(self) -> dict[str, Any]:
        return {
            "tokens_used": self.tokens_used,
            "usage_known": self.usage_known,
            "requests_today": self.requests_today,
            "requests_known": self.requests_known,
            "requests_day": self.requests_day,
            "usage_source": self.usage_source,
            "usage_as_of": self.usage_as_of,
            "tokens_remaining": self.tokens_remaining,
            "requests_remaining": self.requests_remaining,
        }


class PostgresAccounting:
    durable = True

    async def _identity(self, conn: psycopg.AsyncConnection[Any], facts: KeyFacts) -> dict[str, Any]:
        tag = _mac(b"cx.llm.identity-key.v1", "stable")
        await conn.execute(
            "insert into llm_runtime.identity_settings(singleton,secret_tag) values(true,%s) on conflict do nothing",
            (tag,),
        )
        meta = await (
            await conn.execute("select secret_tag from llm_runtime.identity_settings where singleton")
        ).fetchone()
        if meta is None or not hmac.compare_digest(bytes(meta["secret_tag"]), tag):
            raise AdmissionRefused("quota", "APP_SECRET изменён: необходим reviewed identity migration")
        verifier = facts.verifier()
        await conn.execute(
            "insert into llm_runtime.credentials(provider,verifier) values(%s,%s) on conflict(verifier) do nothing",
            (facts.provider, verifier),
        )
        row = await (
            await conn.execute("select * from llm_runtime.credentials where verifier=%s", (verifier,))
        ).fetchone()
        assert row is not None
        return dict(row)

    async def _facts(
        self, conn: psycopg.AsyncConnection[Any], profile: LLMProfile, original: KeyFacts, account: dict[str, Any]
    ) -> tuple[int | None, int | None, int | None]:
        key_id = profile.api_key_id or original.db_id
        key_limit, day_limit = original.tokens_limit, original.rpd_limit
        active_limits: set[tuple[int | None, int | None]] = set()
        if key_id is not None:
            from dataclasses import replace

            item = await credentials.validate_binding(conn, replace(profile, api_key_id=key_id), reveal=True)
            assert item is not None
            if original.secret is None or not hmac.compare_digest(item["_secret"], original.secret):
                raise AdmissionRefused("auth", "credential wire не соответствует выбранной configuration")
        if original.secret:
            aliases = await (
                await conn.execute(
                    "select credential_uid,tokens_limit,rpd_limit,is_active,deleted_at,tokens_used "
                    "from llm_api_keys where provider=%s and pgp_sym_decrypt(encrypted_key,%s)=%s",
                    (original.provider, get_settings().app_secret, original.secret),
                )
            ).fetchall()
            for alias in aliases:
                await conn.execute(
                    "insert into llm_runtime.credential_aliases(config_uid,credential_uid) values(%s,%s) "
                    "on conflict(config_uid) do nothing",
                    (alias["credential_uid"], account["uid"]),
                )
                linked = await (
                    await conn.execute(
                        "select credential_uid from llm_runtime.credential_aliases where config_uid=%s",
                        (alias["credential_uid"],),
                    )
                ).fetchone()
                if linked is None or linked["credential_uid"] != account["uid"]:
                    raise AdmissionRefused("quota", "private credential identity conflict")
                await conn.execute(
                    "update llm_runtime.credentials set legacy_tokens_hint=greatest(legacy_tokens_hint,%s) where uid=%s",
                    (_counter(alias["tokens_used"]), account["uid"]),
                )
                if alias["is_active"] and alias["deleted_at"] is None:
                    active_limits.add((alias["tokens_limit"], alias["rpd_limit"]))
            if len(active_limits) > 1:
                raise AdmissionRefused("quota", "active aliases physical credential имеют конфликтующие лимиты")
            if active_limits:
                key_limit, day_limit = next(iter(active_limits))
        profile_limit = profile.rpd_limit
        if profile.id is not None:
            current = await (
                await conn.execute("select rpd_limit from llm_profiles where id=%s", (profile.id,))
            ).fetchone()
            if current is None:
                raise AdmissionRefused("quota", "текущая quota configuration профиля отсутствует")
            profile_limit = current["rpd_limit"]
        return _minimum(key_limit), _minimum(day_limit), _minimum(profile_limit)

    async def snapshot(self, profile: LLMProfile, facts: KeyFacts, *, timeout_s: float) -> BudgetSnapshot:
        # Read selection state without waiting behind another key's network lease.
        reject_reflection({"endpoint": facts.endpoint, "model": profile.model, "profile": profile.code}, [facts.secret])
        try:
            async with asyncio.timeout(timeout_s), public_operation():
                async with await psycopg.AsyncConnection.connect(
                    psycopg_dsn(), autocommit=True, row_factory=dict_row, connect_timeout=3
                ) as conn:
                    account = await self._identity(conn, facts)
                    scope = KeyScope(self, conn, profile, facts, account["uid"], time.monotonic() + timeout_s)
                    return await scope.snapshot()
        except (ProviderError, credentials.CredentialBindingError, MaintenanceBusy):
            raise
        except TimeoutError:
            raise AdmissionRefused("timeout", "deadline чтения quota исчерпан") from None
        except Exception as exc:
            raise _unavailable(exc) from None

    async def reconcile(
        self,
        profile: LLMProfile,
        facts: KeyFacts,
        *,
        reconciliation_id: uuid.UUID,
        as_of: dt.datetime,
        tokens_used: int,
        requests_today: int,
        profile_requests: dict[str, int] | None = None,
        confirmed: bool = False,
        source: str = SOURCE,
        acknowledge_orphans: bool = False,
        acknowledge_unknown_origin: bool = False,
    ) -> dict[str, Any]:
        if not confirmed or source != SOURCE or as_of.tzinfo is None or as_of.utcoffset() is None:
            raise AdmissionRefused("quota", "нужны явные confirmation/source/as_of с timezone")
        tokens_used, requests_today = _counter(tokens_used), _counter(requests_today)
        claims = {key: _counter(value) for key, value in (profile_requests or {}).items()}
        if any(not key.startswith(("id:", "code:")) or len(key) > 100 for key in claims):
            raise AdmissionRefused("bad_output", "некорректный profile quota reference")
        reject_reflection(claims, [facts.secret])
        as_of = as_of.astimezone(dt.UTC)
        observation = {
            "tokens_used": tokens_used,
            "requests_today": requests_today,
            "profile_requests": claims,
            "as_of": as_of.isoformat(),
            "source": source,
            "confirmed": True,
            "acknowledge_orphans": acknowledge_orphans,
            "acknowledge_unknown_origin": acknowledge_unknown_origin,
        }
        async with self.key_scope(profile, facts, timeout_s=20.0, check_budget=False) as scope:
            conn = scope.conn
            async with conn.transaction():
                await conn.execute("select pg_advisory_xact_lock(%s)", (credentials.LOCK,))
                previous = await (
                    await conn.execute(
                        "select credential_uid,observation from llm_runtime.reconciliations where id=%s",
                        (reconciliation_id,),
                    )
                ).fetchone()
                if previous is not None:
                    if previous["credential_uid"] != scope.uid or previous["observation"].get("request") != observation:
                        raise AdmissionRefused("quota", "reconciliation id уже использован другим observation")
                    return {
                        "id": str(reconciliation_id),
                        "idempotent": True,
                        "source": source,
                        "as_of": as_of.isoformat(),
                    }
                resolved = {await _resolve_profile_scope(conn, ref): value for ref, value in claims.items()}
                # Profile locks are ordered before the account lock, as in admission.
                for ref in sorted(resolved):
                    await conn.execute(
                        "insert into llm_runtime.profile_scopes(scope) values(%s) on conflict do nothing", (ref,)
                    )
                    await conn.execute("select scope from llm_runtime.profile_scopes where scope=%s for update", (ref,))
                account = await (
                    await conn.execute("select * from llm_runtime.credentials where uid=%s for update", (scope.uid,))
                ).fetchone()
                assert account is not None
                await self._facts(conn, profile, facts, account)
                account = await (
                    await conn.execute("select * from llm_runtime.credentials where uid=%s", (scope.uid,))
                ).fetchone()
                assert account is not None
                if not account["usage_known"] and not acknowledge_unknown_origin:
                    raise AdmissionRefused(
                        "quota", "unknown origin требует явного acknowledge после разбора legacy provenance"
                    )
                audit = {
                    "request": observation,
                    "prior_usage_source": account["usage_source"],
                    "legacy_tokens_hint": account["legacy_tokens_hint"],
                    "prior_usage_known": account["usage_known"],
                }
                now = await _utc_now(conn)
                if as_of > now or as_of.date() != now.date():
                    raise AdmissionRefused("quota", "as_of должен относиться к текущим UTC суткам и не быть будущим")
                attempts = await (
                    await conn.execute("select * from llm_runtime.wire_attempts where credential_uid=%s", (scope.uid,))
                ).fetchall()
                if any(
                    row["admitted_at"] > as_of or (row["finished_at"] and row["finished_at"] > as_of)
                    for row in attempts
                ):
                    raise AdmissionRefused("quota", "observation устарел после новой wire attempt")
                orphans = [row for row in attempts if row["state"] == "reserved" and row["reconciliation_id"] is None]
                if orphans and (not acknowledge_orphans or any(row["deadline_at"] > as_of for row in orphans)):
                    raise AdmissionRefused("quota", "незавершённые attempts требуют deadline и явного acknowledge")
                observed = _counter(sum(row["observed_tokens"] for row in attempts))
                if tokens_used < max(account["confirmed_tokens"], observed):
                    raise AdmissionRefused("quota", "reconciliation не может уменьшать подтверждённый token floor")
                counters = [("key", str(scope.uid), requests_today)]
                for ref, value in resolved.items():
                    latest = await (
                        await conn.execute(
                            "select max(admitted_at) as value from llm_runtime.wire_attempts where profile_scope=%s",
                            (ref,),
                        )
                    ).fetchone()
                    if latest and latest["value"] and latest["value"] > as_of:
                        raise AdmissionRefused("quota", "profile observation устарел после нового admission")
                    counters.append(("profile", ref, value))
                for kind, identity, value in counters:
                    current = await (
                        await conn.execute(
                            "select requests_today from llm_runtime.daily_usage where scope_type=%s and scope_id=%s and utc_day=%s for update",
                            (kind, identity, now.date()),
                        )
                    ).fetchone()
                    if current is not None and value < current["requests_today"]:
                        raise AdmissionRefused("quota", "reconciliation не может уменьшать подтверждённый daily floor")
                    await conn.execute(
                        "insert into llm_runtime.daily_usage(scope_type,scope_id,utc_day,requests_today,requests_known,usage_source,usage_as_of) "
                        "values(%s,%s,%s,%s,true,%s,%s) on conflict(scope_type,scope_id,utc_day) do update "
                        "set requests_today=excluded.requests_today,requests_known=true,usage_source=excluded.usage_source,usage_as_of=excluded.usage_as_of",
                        (kind, identity, now.date(), value, source, as_of),
                    )
                await conn.execute(
                    "insert into llm_runtime.reconciliations(id,credential_uid,as_of,source,observation) values(%s,%s,%s,%s,%s)",
                    (reconciliation_id, scope.uid, as_of, source, Jsonb(audit)),
                )
                await conn.execute(
                    "update llm_runtime.wire_attempts set state='reconciled',reconciliation_id=%s "
                    "where credential_uid=%s and admitted_at<=%s",
                    (reconciliation_id, scope.uid, as_of),
                )
                await conn.execute(
                    "update llm_runtime.credentials set confirmed_tokens=%s,usage_known=true,usage_source=%s,usage_as_of=%s,"
                    "updated_at=clock_timestamp() where uid=%s",
                    (tokens_used, source, as_of, scope.uid),
                )
        return {"id": str(reconciliation_id), "idempotent": False, "source": source, "as_of": as_of.isoformat()}

    @asynccontextmanager
    async def key_scope(
        self, profile: LLMProfile, facts: KeyFacts, *, timeout_s: float, check_budget: bool = True
    ) -> AsyncIterator[KeyScope]:
        reject_reflection({"endpoint": facts.endpoint, "model": profile.model, "profile": profile.code}, [facts.secret])
        deadline = time.monotonic() + timeout_s
        try:
            async with asyncio.timeout(timeout_s), contextlib.AsyncExitStack() as stack:
                await stack.enter_async_context(public_operation())
                conn = await stack.enter_async_context(
                    await psycopg.AsyncConnection.connect(
                        psycopg_dsn(), autocommit=True, row_factory=dict_row, connect_timeout=3
                    )
                )
                account = await self._identity(conn, facts)
                lock = int.from_bytes(facts.verifier()[:8], "big", signed=True)
                while True:
                    row = await (await conn.execute("select pg_try_advisory_lock(%s) as locked", (lock,))).fetchone()
                    if row and row["locked"]:
                        break
                    remaining = deadline - time.monotonic()
                    if remaining <= 0:
                        raise AdmissionRefused("rate_limit", "ожидание credential admission превысило deadline")
                    await asyncio.sleep(min(0.02, remaining))
                # Session lease serializes budgeted usage uncertainty, not a SQL transaction across HTTP.
                try:
                    scope = KeyScope(self, conn, profile, facts, account["uid"], deadline)
                    if check_budget:
                        await scope.check()
                    yield scope
                finally:
                    await conn.execute("select pg_advisory_unlock(%s)", (lock,))
        except (ProviderError, credentials.CredentialBindingError, MaintenanceBusy):
            raise
        except TimeoutError:
            raise AdmissionRefused("timeout", "deadline inference admission исчерпан") from None
        except psycopg.Error as exc:
            raise _unavailable(exc) from None


@dataclass
class KeyScope:
    service: PostgresAccounting
    conn: psycopg.AsyncConnection[Any]
    profile: LLMProfile
    facts: KeyFacts = field(repr=False)
    uid: uuid.UUID = field(repr=False)
    deadline: float

    @asynccontextmanager
    async def _state(self) -> AsyncIterator[dict[str, Any]]:
        async with self.conn.transaction():
            await self.conn.execute("select pg_advisory_xact_lock(%s)", (credentials.LOCK,))
            profile_scope = await _resolve_profile_scope(self.conn, _profile_scope(self.profile))
            await self.conn.execute(
                "insert into llm_runtime.profile_scopes(scope) values(%s) on conflict do nothing", (profile_scope,)
            )
            registered = await (
                await self.conn.execute(
                    "select * from llm_runtime.profile_scopes where scope=%s for update", (profile_scope,)
                )
            ).fetchone()
            account = await (
                await self.conn.execute("select * from llm_runtime.credentials where uid=%s for update", (self.uid,))
            ).fetchone()
            assert account is not None and registered is not None
            limits = await self.service._facts(self.conn, self.profile, self.facts, account)
            # DB clock is deliberately read AFTER all contended locks, never SimClock.
            now = await _utc_now(self.conn)
            day = now.date()
            rows = []
            for kind, identity, created in (
                ("key", str(self.uid), account["created_at"]),
                ("profile", profile_scope, registered["created_at"]),
            ):
                rollover = created.astimezone(dt.UTC).date() < day
                await self.conn.execute(
                    "insert into llm_runtime.daily_usage(scope_type,scope_id,utc_day,requests_known,usage_source) "
                    "values(%s,%s,%s,%s,%s) on conflict do nothing",
                    (kind, identity, day, rollover, "utc_rollover_app_observed" if rollover else "unknown"),
                )
                row = await (
                    await self.conn.execute(
                        "select * from llm_runtime.daily_usage where scope_type=%s and scope_id=%s and utc_day=%s for update",
                        (kind, identity, day),
                    )
                ).fetchone()
                assert row is not None
                rows.append(row)
            unresolved = await (
                await self.conn.execute(
                    "select exists(select 1 from llm_runtime.wire_attempts where credential_uid=%s "
                    "and state in ('reserved','unknown') and reconciliation_id is null) as value",
                    (self.uid,),
                )
            ).fetchone()
            assert unresolved is not None
            yield {
                "account": account,
                "key_day": rows[0],
                "profile_day": rows[1],
                "limits": limits,
                "now": now,
                "day": day,
                "profile_scope": profile_scope,
                "unresolved": unresolved["value"],
            }

    def _validate(self, state: dict[str, Any]) -> None:
        tokens, key_rpd, profile_rpd = state["limits"]
        budgeted = self.facts.paid or any(value is not None for value in state["limits"])
        if budgeted and (
            not state["account"]["usage_known"]
            or state["unresolved"]
            or not state["key_day"]["requests_known"]
            or (profile_rpd is not None and not state["profile_day"]["requests_known"])
        ):
            raise AdmissionRefused("quota", "расход не подтверждён: требуется operator reconciliation")
        if tokens is not None and state["account"]["confirmed_tokens"] >= tokens:
            raise AdmissionRefused("quota", "подтверждённый token budget исчерпан")
        for maximum, counter in ((key_rpd, state["key_day"]), (profile_rpd, state["profile_day"])):
            if maximum is not None and counter["requests_today"] >= maximum:
                next_day = dt.datetime.combine(state["day"] + dt.timedelta(days=1), dt.time(), dt.UTC)
                raise AdmissionRefused(
                    "rate_limit",
                    "суточный inference budget исчерпан",
                    retry_after_s=(next_day - state["now"]).total_seconds(),
                )

    async def snapshot(self) -> BudgetSnapshot:
        async with self._state() as state:
            account, day = state["account"], state["key_day"]
            known = bool(account["usage_known"] and not state["unresolved"])
            requests_known = bool(day["requests_known"])
            token_limit, request_limit, _ = state["limits"]
            refusal = None
            try:
                self._validate(state)
            except ProviderError as exc:
                refusal = exc
            return BudgetSnapshot(
                tokens_used=account["confirmed_tokens"],
                usage_known=known,
                requests_today=day["requests_today"],
                requests_known=requests_known,
                requests_day=state["day"],
                usage_source=account["usage_source"],
                usage_as_of=account["usage_as_of"],
                tokens_remaining=max(0, token_limit - account["confirmed_tokens"])
                if known and token_limit is not None
                else None,
                requests_remaining=max(0, request_limit - day["requests_today"])
                if requests_known and request_limit is not None
                else None,
                refusal=refusal,
            )

    async def check(self) -> None:
        async with self._state() as state:
            self._validate(state)

    @asynccontextmanager
    async def inference(self) -> AsyncIterator[Ticket]:
        ticket = await self.admit()
        try:
            yield ticket
        except BaseException as exc:
            kind = (
                exc.kind
                if isinstance(exc, ProviderError)
                else "cancelled"
                if isinstance(exc, asyncio.CancelledError)
                else "unavailable"
            )
            try:
                await ticket.unknown(kind)
            except Exception as bookkeeping:
                # Reservation is already durable: failure never refunds it.
                log.warning("llm_usage_unconfirmed", error_type=type(bookkeeping).__name__)
            raise
        else:
            await ticket.unknown()

    async def admit(self, attempt_id: uuid.UUID | None = None) -> Ticket:
        if self.deadline <= time.monotonic():
            raise AdmissionRefused("timeout", "deadline до inference admission исчерпан")
        if not self.facts.endpoint:
            raise AdmissionRefused("auth", "inference endpoint не указан")
        attempt_id = attempt_id or uuid.uuid4()
        async with self._state() as state:
            previous = await (
                await self.conn.execute("select id from llm_runtime.wire_attempts where id=%s", (attempt_id,))
            ).fetchone()
            if previous is not None:
                # DB retry is idempotent; it must NEVER be permission to resend HTTP.
                raise AdmissionRefused("quota", "повтор reservation не разрешает повторный HTTP")
            self._validate(state)
            await self.conn.execute(
                "insert into llm_runtime.wire_attempts(id,credential_uid,profile_scope,profile_id,profile_code,endpoint,model,utc_day,admitted_at,deadline_at) "
                "values(%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)",
                (
                    attempt_id,
                    self.uid,
                    state["profile_scope"],
                    self.profile.id,
                    self.profile.code,
                    self.facts.endpoint,
                    self.profile.model,
                    state["day"],
                    state["now"],
                    state["now"] + dt.timedelta(seconds=max(0.0, self.deadline - time.monotonic())),
                ),
            )
            await self.conn.execute(
                "update llm_runtime.daily_usage set requests_today=requests_today+1,usage_as_of=%s "
                "where utc_day=%s and ((scope_type='key' and scope_id=%s) or (scope_type='profile' and scope_id=%s))",
                (state["now"], state["day"], str(self.uid), state["profile_scope"]),
            )
        return Ticket(self, attempt_id)


@dataclass
class Ticket:
    scope: KeyScope = field(repr=False)
    id: uuid.UUID
    terminal: bool = False

    async def observe(
        self, prompt: int, completion: int, *, total_tokens: int | None = None, final: bool = False
    ) -> None:
        prompt, completion = _counter(prompt), _counter(completion)
        subtotal = _counter(prompt + completion)
        total = subtotal if total_tokens is None else _counter(total_tokens)
        if total < subtotal:
            raise AdmissionRefused("bad_output", "total usage меньше суммы prompt/completion")
        conn = self.scope.conn
        async with conn.transaction():
            account = await (
                await conn.execute("select * from llm_runtime.credentials where uid=%s for update", (self.scope.uid,))
            ).fetchone()
            attempt = await (
                await conn.execute("select * from llm_runtime.wire_attempts where id=%s for update", (self.id,))
            ).fetchone()
            assert account is not None and attempt is not None
            if total < attempt["observed_tokens"] or any(
                old is not None and new < old
                for old, new in ((attempt["prompt_tokens"], prompt), (attempt["completion_tokens"], completion))
            ):
                raise AdmissionRefused("bad_output", "cumulative usage уменьшился")
            delta = total - attempt["observed_tokens"]
            late = attempt["reconciliation_id"] is not None and delta > 0
            await conn.execute(
                "update llm_runtime.wire_attempts set prompt_tokens=%s,completion_tokens=%s,observed_tokens=%s,"
                "state=case when reconciliation_id is not null then state when %s then 'known' else state end,"
                "finished_at=case when %s then clock_timestamp() else finished_at end where id=%s",
                (prompt, completion, total, final, final, self.id),
            )
            if attempt["reconciliation_id"] is None:
                floor = _counter(account["confirmed_tokens"] + delta)
            else:
                observed = await (
                    await conn.execute(
                        "select coalesce(sum(observed_tokens),0) as value from llm_runtime.wire_attempts where credential_uid=%s",
                        (self.scope.uid,),
                    )
                ).fetchone()
                assert observed is not None
                floor = max(account["confirmed_tokens"], _counter(int(observed["value"])))
            known = account["usage_known"] and not late
            source = "operator_reconciled_and_app_observed" if known else "app_observed_incomplete"
            await conn.execute(
                "update llm_runtime.credentials set confirmed_tokens=%s,usage_known=%s,usage_source=%s,"
                "usage_as_of=clock_timestamp(),updated_at=clock_timestamp() where uid=%s",
                (floor, known, source, self.scope.uid),
            )
        self.terminal = self.terminal or final or attempt["state"] in ("known", "reconciled")

    async def unknown(self, kind: str = "unavailable") -> None:
        if self.terminal:
            return
        allowed = {"auth", "rate_limit", "quota", "timeout", "network", "bad_output", "cancelled", "unavailable"}
        kind = kind if kind in allowed else "unavailable"
        async with self.scope.conn.transaction():
            row = await (
                await self.scope.conn.execute(
                    "select state from llm_runtime.wire_attempts where id=%s for update", (self.id,)
                )
            ).fetchone()
            if row is None or row["state"] in ("known", "reconciled"):
                self.terminal = True
                return
            await self.scope.conn.execute(
                "update llm_runtime.wire_attempts set state='unknown',finished_at=clock_timestamp(),error_kind=%s "
                "where id=%s and reconciliation_id is null and state='reserved'",
                (kind, self.id),
            )
            await self.scope.conn.execute(
                "update llm_runtime.credentials set usage_known=false,usage_source='app_observed_incomplete',"
                "updated_at=clock_timestamp() where uid=%s",
                (self.scope.uid,),
            )
        self.terminal = True


def service() -> PostgresAccounting:
    return PostgresAccounting()
