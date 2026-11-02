"""Фоновые бенчмарки с сохранением результатов и строгим выбором провайдера (T-129)."""

from __future__ import annotations

import asyncio
import csv
import io
import json
from dataclasses import asdict
from datetime import UTC, datetime
from functools import partial
from typing import Any, cast

from psycopg import Error as DatabaseError
from psycopg.types.json import Jsonb

from app.agent.prompts import load as load_prompt
from app.api.common import db, fetch_all, fetch_one
from app.api.settings import key_plain, load_keys
from app.bench import runner
from app.config import get_settings
from app.errors import Problem
from app.llm import accounting, credentials
from app.llm.base import LLMProfile, Provider, ProviderError
from app.llm.budget import load_openrouter_budget
from app.llm.failover import ProviderChain
from app.llm.gigachat import GigaChatProvider
from app.llm.keys import ApiKey, KeyPool
from app.llm.mock import MockProvider
from app.llm.openai_compat import OpenAICompatProvider, is_paid_model
from app.llm.ratelimit import RateLimiter, limiter
from app.logging import get_logger
from app.realtime.hub import hub
from app.replay.provider import ReplayProvider
from app.replay.store import CassetteStore
from app.sim.maintenance import spawn_writer, writer

log = get_logger(__name__)


async def record_key_usage(conn: Any, key_id: int, tokens: int) -> None:
    """Derived mirror only: inference was already durably counted before HTTP.

    tokens remains a compatibility argument for callbacks, never a new charge.
    """
    await conn.execute("select pg_advisory_xact_lock(%s)", (credentials.LOCK,))
    alias = await fetch_one(
        conn,
        "select a.credential_uid from llm_runtime.credential_aliases a join llm_api_keys k on k.credential_uid=a.config_uid where k.id=%s",
        (key_id,),
    )
    if alias is not None:
        await accounting.sync_mirrors(conn, alias["credential_uid"])


class BenchRateLimiter(RateLimiter):
    """Ждёт RPM-слот общего лимитера; суточное исчерпание завершает прогон."""

    async def acquire(self, code: str, rpm: int | None = None, rpd: int | None = None) -> None:
        while True:
            try:
                await limiter.acquire(code, rpm, rpd)
                return
            except ProviderError as exc:
                if exc.kind != "rate_limit" or not exc.retry_after_s or not 0 < exc.retry_after_s <= 60:
                    raise
                await asyncio.sleep(exc.retry_after_s)


class BenchService:
    def __init__(self) -> None:
        self.tasks: dict[int, asyncio.Task[None]] = {}
        self.records: dict[int, runner.BenchRunRecord] = {}
        self.locks: dict[int, asyncio.Lock] = {}
        self.keys: dict[str, ApiKey] = {}
        self.ready = False
        self.start_lock = asyncio.Lock()
        self.gigachat_run_lock = asyncio.Lock()

    async def recover(self) -> None:
        async with self.start_lock:
            if self.ready:
                return
            async with db() as conn:
                await conn.execute(
                    "update bench_runs set status='failed',finished_at=now(),error='interrupted: server restarted' where status in ('queued','running')"
                )
            self.ready = True

    async def datasets(self) -> list[dict[str, Any]]:
        await self.recover()
        async with db() as conn:
            return await fetch_all(
                conn,
                "select d.id,d.code,d.title_ru,count(c.id)::int as cases from bench_datasets d left join bench_cases c on c.dataset_id=d.id group by d.id having count(c.id)>0 and bool_and(c.gold ? 'signal_type') order by d.code",
            )

    async def context(
        self, dataset_id: int, ids: list[int]
    ) -> tuple[str, list[runner.BenchCase], list[dict[str, Any]], list[dict[str, Any]]]:
        async with db() as conn:
            dataset = await fetch_one(conn, "select code from bench_datasets where id=%s", (dataset_id,))
            if dataset is None:
                raise Problem(404, "набор не найден")
            rows = await fetch_all(
                conn,
                "select id,channel_code,text,gold,tags from bench_cases where dataset_id=%s order by id",
                (dataset_id,),
            )
            if not rows or any("signal_type" not in r["gold"] for r in rows):
                raise Problem(422, "ожидается непустой classify-набор с gold.signal_type")
            profiles = await fetch_all(
                conn, "select * from llm_profiles where id=any(%s) and is_active order by id", (ids,)
            )
            if len(profiles) != len(set(ids)):
                raise Problem(422, "неизвестный или неактивный профиль")
            for row in profiles:
                await credentials.validate_binding(conn, self.profile(row))
            keys = await load_keys(conn)
            await self.accounting_metadata(conn, profiles, keys)
        cases = [
            runner.BenchCase(r["id"], str(r["id"]), r["channel_code"], r["text"], r["gold"], r.get("tags", []))
            for r in rows
        ]
        return dataset["code"], cases, profiles, keys

    async def accounting_metadata(self, conn: Any, profiles: list[dict[str, Any]], keys: list[dict[str, Any]]) -> None:
        # Private grouping keys never enter Forecast/BenchRecord/export DTOs.
        groups = await fetch_all(
            conn,
            "select credential_uid, count(distinct row(tokens_limit,rpd_limit))>1 as conflict from llm_api_keys where is_active and deleted_at is null group by credential_uid",
        )
        conflicts = {str(row["credential_uid"]): row["conflict"] for row in groups}
        identities = await fetch_all(conn, "select id,credential_uid from llm_api_keys where deleted_at is null")
        by_id = {row["id"]: str(row["credential_uid"]) for row in identities}
        for item in keys:
            item["_quota_group"] = by_id[item["id"]]
            item["_quota_conflict"] = conflicts.get(item["_quota_group"], False)
        for provider in ("gigachat", "openai_compatible"):
            for env in self.available_keys(provider, []):
                facts = accounting.KeyFacts(provider, env["_secret"], env["endpoint_url"], env["tokens_limit"])
                observed = await accounting.attach_env_observation(conn, env, facts)
                identity = await fetch_one(
                    conn,
                    "select coalesce((select a.config_uid from llm_runtime.credential_aliases a where a.credential_uid=c.uid limit 1),c.uid) as uid from llm_runtime.credentials c where c.verifier=%s",
                    (facts.verifier(),),
                )
                observed["_quota_group"] = str(identity["uid"]) if identity else env["label"]
                observed["_quota_conflict"] = conflicts.get(observed["_quota_group"], False)
                keys.append(observed)
        daily = await fetch_all(
            conn,
            "with clock as(select (clock_timestamp() at time zone 'UTC')::date as day) "
            "select p.id,coalesce(d.requests_today,0) as used,coalesce(d.requests_known,(s.created_at at time zone 'UTC')::date<clock.day,false) as known "
            "from clock cross join llm_profiles p left join llm_runtime.profile_scopes s on s.scope='quota:'||p.quota_uid::text "
            "left join llm_runtime.daily_usage d on d.scope_type='profile' and d.scope_id=s.scope and d.utc_day=clock.day where p.id=any(%s)",
            ([row["id"] for row in profiles],),
        )
        by_profile = {row["id"]: row for row in daily}
        for row in profiles:
            observed = by_profile[row["id"]]
            row["_requests_known"], row["_requests_today"] = observed["known"], observed["used"]

    @staticmethod
    def profile(row: dict[str, Any]) -> LLMProfile:
        values = {key: row[key] for key in LLMProfile.__dataclass_fields__ if key in row}
        for key in ("temperature", "price_in_per_1m", "price_out_per_1m"):
            if key in values:
                values[key] = float(values[key])
        values["temperature"] = 0.0  # единые параметры сравнения; профиль twin в БД не меняется
        profile = LLMProfile(**values)
        from app.llm.run_profiles import _safe

        _safe(profile)
        return profile

    def available_keys(self, provider: str, saved: list[dict[str, Any]]) -> list[dict[str, Any]]:
        settings = get_settings()
        keys = [
            {**k, "label": f"bench_{provider}_db_{k['id']}" if k.get("id") is not None else k["label"]}
            for k in saved
            if k.get("provider") == provider and k.get("is_active", True)
        ]
        env_values = (
            (settings.gigachat_auth_key_1, settings.gigachat_auth_key_2)
            if provider == "gigachat"
            else (settings.openrouter_api_key,)
        )
        for index, value in enumerate(env_values, 1):
            if value and not any(key.get("_env_slot") == index for key in keys):
                keys.append(
                    {
                        "id": None,
                        "label": f"{provider}_env_{index}",
                        "_env_slot": index,
                        "provider": provider,
                        "_secret": value,
                        "tokens_limit": 50_000_000 if provider == "gigachat" else None,
                        "tokens_used": 0,
                        "endpoint_url": credentials.endpoint(
                            settings.gigachat_base_url if provider == "gigachat" else settings.openrouter_base_url
                        ),
                    }
                )
        return keys

    def selected_keys(self, profile: LLMProfile, saved: list[dict[str, Any]]) -> list[dict[str, Any]]:
        keys = self.available_keys(profile.provider, saved)
        if profile.api_key_id is not None:
            return [key for key in keys if key.get("id") == profile.api_key_id]
        target = credentials.endpoint(profile.base_url or credentials.default_endpoint(profile.provider))
        return [key for key in keys if key.get("endpoint_url") and credentials.endpoint(key["endpoint_url"]) == target]

    def remaining(self, keys: list[dict[str, Any]]) -> int | None:
        unique: dict[str, dict[str, Any]] = {}
        for key in keys:
            group = key.get("_quota_group", key["label"])
            if group not in unique or (unique[group].get("id") is None and key.get("id") is not None):
                unique[group] = key
        selected = list(unique.values())
        if any(k.get("usage_known") is False or k.get("_quota_conflict") for k in selected):
            return None
        if any(k.get("tokens_limit") is None for k in selected):
            return None
        return sum(
            int(k["tokens_remaining"])
            if k.get("usage_known") is True
            else max(
                0,
                int(k["tokens_limit"])
                - max(
                    int(k.get("tokens_used") or 0), self.keys[k["label"]].tokens_used if k["label"] in self.keys else 0
                ),
            )
            for k in selected
        )

    def forecast(
        self, code: str, cases: list[runner.BenchCase], row: dict[str, Any], saved: list[dict[str, Any]], repeats: int
    ) -> dict[str, Any]:
        profile = self.profile(row)
        keys = self.selected_keys(profile, saved)
        fc = runner.forecast(
            code, profile, repeats=repeats, cases=cases, key_tokens_remaining=self.remaining(keys) if keys else None
        )
        warning = fc.warning
        if (
            profile.provider not in ("mock", "replay")
            and not keys
            and not (profile.provider == "openai_compatible" and profile.extra.get("local"))
        ):
            fc.fits_limits = False
            warning = "; ".join(filter(None, (warning, "нет активного ключа провайдера")))
        if profile.provider not in ("mock", "replay"):
            budgeted = (
                is_paid_model(profile, profile.base_url or get_settings().openrouter_base_url)
                or profile.rpd_limit is not None
                or any(k.get("tokens_limit") is not None or k.get("rpd_limit") is not None for k in keys)
            )
            if any(k.get("_quota_conflict") for k in keys):
                fc.fits_limits = False
                warning = "; ".join(filter(None, (warning, "конфликт лимитов active aliases physical credential")))
            if budgeted and any(k.get("usage_known") is not True or k.get("requests_known") is not True for k in keys):
                fc.fits_limits = False
                warning = "; ".join(filter(None, (warning, "расход ключа неизвестен; нужен operator reconciliation")))
            if profile.rpd_limit is not None and row.get("_requests_known") is False:
                fc.fits_limits = False
                warning = "; ".join(
                    filter(None, (warning, "суточный расход профиля неизвестен; нужен operator reconciliation"))
                )
        used = int(row.get("_requests_today", limiter.stats().get(profile.code, {}).get("today") or 0))
        if profile.rpd_limit is not None and used + fc.est_requests > profile.rpd_limit:
            fc.fits_limits = False
            warning = "; ".join(
                filter(None, (warning, f"доступно {max(0, profile.rpd_limit - used)} запросов сегодня"))
            )
        return {"llm_profile_id": row["id"], **asdict(fc), "warning": warning}

    def chain(
        self, profile: LLMProfile, saved: list[dict[str, Any]]
    ) -> tuple[ProviderChain, list[Provider], str | None]:
        settings = get_settings()
        providers: list[Provider] = []
        selected_key: str | None = None
        if profile.provider == "mock":
            providers.append(MockProvider())
        elif profile.provider == "replay":
            providers.append(ReplayProvider(CassetteStore(settings.cassettes_dir)))
        elif profile.provider == "gigachat":
            pool = []
            for item in self.selected_keys(profile, saved):
                label = str(item["label"])
                secret = item.get("_secret") or key_plain(item)
                key = self.keys.get(label)
                if key is None or key.secret != secret:
                    key = ApiKey(
                        label=label,
                        secret=secret,
                        tokens_limit=item.get("tokens_limit"),
                        tokens_used=int(item.get("tokens_used") or 0),
                        db_id=item.get("id"),
                    )
                    self.keys[label] = key
                key.tokens_used = max(key.tokens_used, int(item.get("tokens_used") or 0))
                key.tokens_limit = item.get("tokens_limit")
                pool.append(key)
            if not pool:
                raise ProviderError("auth", "нет активного ключа GigaChat")
            providers.append(
                GigaChatProvider(
                    KeyPool(pool),
                    oauth_url=settings.gigachat_oauth_url,
                    base_url=profile.base_url or settings.gigachat_base_url,
                    scope=settings.gigachat_scope,
                    verify_ssl=True,
                    ca_bundle_file=settings.gigachat_ca_bundle_file,
                )
            )
        elif profile.provider == "openai_compatible":
            local = bool(profile.extra.get("local"))
            base = profile.base_url or (settings.local_llm_base_url if local else settings.openrouter_base_url)
            if not base:
                raise ProviderError("unavailable", "LOCAL_LLM_BASE_URL или base_url локального профиля не задан")
            keys = self.selected_keys(profile, saved)
            if local:
                # Ключ локального endpoint выбирается явно; OpenRouter secret не подставляется.
                keys = [
                    key
                    for key in keys
                    if (profile.api_key_id or profile.extra.get("api_key_id")) is not None
                    and key.get("id") == (profile.api_key_id or profile.extra.get("api_key_id"))
                ]

            def capacity(item: dict[str, Any]) -> int:
                remaining = self.remaining([item])
                return remaining if remaining is not None else 10**12

            usable = [k for k in keys if capacity(k) > 0]
            chosen = max(usable, key=capacity) if usable else None
            if keys and chosen is None:
                raise ProviderError("quota", "ключи OpenAI-compatible исчерпаны")
            if chosen is None and not profile.extra.get("local"):
                raise ProviderError("auth", "нет активного OpenAI-compatible ключа")
            secret = (
                (chosen.get("_secret") or key_plain(chosen))
                if chosen
                else (getattr(settings, "local_llm_api_key", None) if local else None)
            )
            if chosen is not None:
                selected_key = chosen["label"]
                if selected_key not in self.keys or self.keys[selected_key].secret != secret:
                    self.keys[selected_key] = ApiKey(
                        label=selected_key,
                        secret=str(secret),
                        provider=profile.provider,
                        tokens_limit=chosen.get("tokens_limit"),
                        tokens_used=int(chosen.get("tokens_used") or 0),
                        db_id=chosen.get("id"),
                    )
                self.keys[selected_key].tokens_used = max(
                    self.keys[selected_key].tokens_used, int(chosen.get("tokens_used") or 0)
                )
                self.keys[selected_key].tokens_limit = chosen.get("tokens_limit")
            if (
                local
                and chosen is None
                and secret
                and base.rstrip("/") != (settings.local_llm_base_url or "").rstrip("/")
            ):
                raise ProviderError("auth", "local env source не разрешён для endpoint профиля")
            providers.append(
                OpenAICompatProvider(
                    secret,
                    base,
                    budget_usd=settings.openrouter_budget_usd,
                    budget_loader=partial(load_openrouter_budget, settings.openrouter_budget_usd),
                )
            )
        else:
            raise ProviderError("unavailable", "провайдер не поддерживается")
        if profile.api_key_id is not None:
            for provider in providers:
                cast(Any, provider).credential_id = profile.api_key_id
        return ProviderChain(providers, append_mock=False, rate_limiter=BenchRateLimiter()), providers, selected_key

    async def start(self, dataset_id: int, ids: list[int], repeats: int, dry_run: bool) -> dict[str, Any]:
        await self.recover()
        code, cases, profiles, saved = await self.context(dataset_id, ids)
        forecasts = [self.forecast(code, cases, row, saved, repeats) for row in profiles]
        if dry_run:
            return {"run_ids": [], "forecast": forecasts}
        if any(not fc["fits_limits"] for fc in forecasts):
            raise Problem(409, "прогноз не укладывается в лимиты или нет ключа; сначала исправьте настройки")
        records = []
        async with db() as conn, conn.transaction():
            for row in profiles:
                created = await fetch_one(
                    conn,
                    "insert into bench_runs(dataset_id,llm_profile_id,prompt_version,seed,repeats) values(%s,%s,%s,42,%s) returning id",
                    (dataset_id, row["id"], load_prompt("classify").version, repeats),
                )
                assert created is not None
                rec = runner.BenchRunRecord(
                    created["id"], code, row["code"], load_prompt("classify").version, 42, repeats, "queued"
                )
                records.append((row, rec))
        for row, rec in records:
            self.records[rec.id] = rec
            task = spawn_writer(self.execute(row, rec, cases, saved), kind="bench")
            self.tasks[rec.id] = task
            task.add_done_callback(partial(self.finished, rec.id))
        return {"run_ids": [rec.id for _, rec in records], "forecast": forecasts}

    def finished(self, id_: int, task: asyncio.Task[None]) -> None:
        self.tasks.pop(id_, None)
        self.records.pop(id_, None)
        if not task.cancelled() and task.exception() is not None:
            log.error("bench_background_failed", run_id=id_, error_type=type(task.exception()).__name__)

    @writer("bench")
    async def execute(
        self,
        row: dict[str, Any],
        rec: runner.BenchRunRecord,
        cases: list[runner.BenchCase],
        saved: list[dict[str, Any]],
    ) -> None:
        persisted = 0
        providers: list[Provider] = []
        selected_key: str | None = None

        async def update(record: runner.BenchRunRecord) -> None:
            nonlocal persisted
            usage_updates: list[tuple[ApiKey, int]] = []
            async with db() as conn, conn.transaction():
                for result in record.results[persisted:]:
                    label = result.get("key_label") or selected_key
                    key = self.keys.get(label) if label else None
                    if key is not None:
                        if key.provider != "gigachat":
                            usage_updates.append((key, result["prompt_tokens"] + result["completion_tokens"]))
                        if key.db_id is not None:
                            await record_key_usage(
                                conn, key.db_id, result["prompt_tokens"] + result["completion_tokens"]
                            )
                    await conn.execute(
                        "insert into bench_results(run_id,case_id,repeat_no,predicted,correct,json_valid_first_try,retries,latency_ms,prompt_tokens,completion_tokens,fallback_mock) values (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)",
                        (
                            record.id,
                            result["case_id"],
                            result["repeat_no"],
                            Jsonb(result["predicted"]),
                            Jsonb(result["correct"]),
                            result["json_valid_first_try"],
                            result["retries"],
                            result["latency_ms"],
                            result["prompt_tokens"],
                            result["completion_tokens"],
                            result["fallback_mock"],
                        ),
                    )
                await conn.execute(
                    "update bench_runs set status=%s,metrics=%s,started_at=%s,finished_at=%s,error=%s where id=%s",
                    (
                        record.status,
                        Jsonb(record.metrics) if record.metrics is not None else None,
                        record.started_at,
                        record.finished_at,
                        record.error,
                        record.id,
                    ),
                )
            # Счётчик в памяти меняется только после успешного commit.
            for key, tokens in usage_updates:
                KeyPool([key]).add_usage(key, tokens)
            persisted = len(record.results)
            await hub.publish(
                "bench", "bench.progress", {"id": record.id, "status": record.status, "progress": record.progress}
            )

        try:
            lock = self.locks.setdefault(row["id"], asyncio.Lock())
            if row["provider"] == "gigachat" and get_settings().gigachat_scope == "GIGACHAT_API_PERS":
                lock = self.gigachat_run_lock
            async with lock:
                if rec._cancel:
                    rec.status = "cancelled"
                    rec.finished_at = datetime.now(UTC)
                    await update(rec)
                    return
                # Повторная проверка после ожидания другого прогона того же профиля.
                async with db() as conn:
                    await credentials.validate_binding(conn, self.profile(row))
                    saved = await load_keys(conn, reveal=True)
                fc = self.forecast(rec.dataset_code, cases, row, saved, rec.repeats)
                if not fc["fits_limits"]:
                    raise ProviderError("quota", str(fc["warning"]))
                chain, providers, selected_key = self.chain(self.profile(row), saved)
                await runner.run(
                    rec.dataset_code,
                    self.profile(row),
                    repeats=rec.repeats,
                    cases=cases,
                    record=rec,
                    chain=chain,
                    on_update=update,
                )
        except asyncio.CancelledError:
            rec.status = "cancelled"
            rec.finished_at = datetime.now(UTC)
            await update(rec)
        except Exception as exc:
            log.error("bench_job_failed", run_id=rec.id, error_type=type(exc).__name__)
            rec.status = "failed"
            # Произвольный текст ошибки провайдера может содержать ключ или данные клиента.
            rec.error = "benchmark failed: provider or persistence unavailable"
            rec.finished_at = datetime.now(UTC)
            await update(rec)
        finally:
            for provider in providers:
                close = getattr(provider, "aclose", None)
                if close is not None:
                    await close()
            self.records.pop(rec.id, None)

    async def runs(self) -> list[dict[str, Any]]:
        await self.recover()
        async with db() as conn:
            return await fetch_all(
                conn,
                "select r.*,d.code dataset_code,p.code llm_profile_code,coalesce((select count(*) from bench_results br where br.run_id=r.id)::float/nullif((select count(*) from bench_cases c where c.dataset_id=r.dataset_id)*r.repeats,0),0) progress from bench_runs r join bench_datasets d on d.id=r.dataset_id join llm_profiles p on p.id=r.llm_profile_id order by r.id",
            )

    async def detail(self, id_: int) -> dict[str, Any]:
        rows = await self.runs()
        row = next((r for r in rows if r["id"] == id_), None)
        if row is None:
            raise Problem(404, "прогон не найден")
        async with db() as conn:
            results = await fetch_all(
                conn,
                "select br.*,c.text,c.gold,c.tags from bench_results br join bench_cases c on c.id=br.case_id where br.run_id=%s order by br.repeat_no,br.case_id",
                (id_,),
            )
        return {**row, "results": results}

    async def cancel(self, id_: int) -> None:
        detail = await self.detail(id_)
        if detail["status"] in ("queued", "running"):
            async with db() as conn:
                await conn.execute(
                    "update bench_runs set status='cancelled',finished_at=now() where id=%s and status in ('queued','running')",
                    (id_,),
                )
            if id_ in self.records:
                self.records[id_].request_cancel()
            task = self.tasks.get(id_)
            if task is not None:
                task.cancel()

    async def stop(self) -> None:
        ids = list(self.tasks)
        tasks = list(self.tasks.values())
        for task in tasks:
            task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)
        if ids:
            try:
                async with db() as conn:
                    await conn.execute(
                        "update bench_runs set status='cancelled',finished_at=now() where id=any(%s) and status in ('queued','running')",
                        (ids,),
                    )
            except DatabaseError as exc:
                # Следующий recover пометит незавершённые записи interrupted.
                log.error("bench_shutdown_persist_failed", error_type=type(exc).__name__)

    async def export(self, id_: int, format_: str) -> str:
        detail = await self.detail(id_)
        if format_ == "json":
            return json.dumps(detail, ensure_ascii=False, default=str)
        out = io.StringIO()
        fields = [
            "case_id",
            "repeat_no",
            "text",
            "gold",
            "predicted",
            "correct",
            "latency_ms",
            "json_valid_first_try",
            "retries",
            "fallback_mock",
            "prompt_tokens",
            "completion_tokens",
            "tags",
        ]
        writer = csv.DictWriter(out, fieldnames=fields)
        writer.writeheader()
        for result in detail["results"]:
            writer.writerow(
                {
                    k: json.dumps(result[k], ensure_ascii=False) if isinstance(result[k], (dict, list)) else result[k]
                    for k in fields
                }
            )
        return out.getvalue()
