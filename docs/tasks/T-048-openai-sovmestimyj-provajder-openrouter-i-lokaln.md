# T-048 — OpenAI-совместимый провайдер: OpenRouter и локальная модель

| Поле | Значение |
|---|---|
| Эпик | E4 LLM-слой |
| Субагент | `SA-LLM` (LLM-слой) |
| Оценка | M (1–2 дня) |
| Волна | 1 |
| Слой | `L1` Базис (владелец — см. docs/TEAM-SPLIT.md и CODEOWNERS) |
| В демо-минимуме | да |
| Статус | `in_progress` |

## Цель
Бесплатные модели OpenRouter и любая локальная модель по OpenAI API без изменений кода.

## Разделы ТЗ (docs/TZ.md)
§5.2, §14.3, §20.2 п. 1–2

## Контракты
- `db/schema.sql: llm_profiles`

## Зависимости
- Зависит от: [T-046](T-046-interfejs-llm-provajdera-i-strukturirovannyj-vyv.md)
- Блокирует: [T-050](T-050-rate-limiter-byudzhety-fallback-i-maskirovanie-s.md)

## Что сделать
1. openai SDK с base_url из профиля; заголовки HTTP-Referer/X-Title для OpenRouter; поддержка моделей nvidia/nemotron-3-ultra-550b-a55b:free, openrouter/owl-alpha, openai/gpt-oss-120b:free по умолчанию.
2. Проверка доступности id через GET /api/v1/models при старте и в мастере; предложение замены (nvidia/nemotron-3-super-120b-a12b:free или первая из коллекции free).
3. Чтение баланса и лимитов GET /api/v1/key → LlmApiKey.balance_usd, rpd_limit; бюджетный лимит платных моделей (settings.llm.openrouter_budget_usd, по умолчанию 10).
4. Профиль local_openai: base_url из LOCAL_LLM_BASE_URL, без ключа или с ключом.

## Критерии приёмки
- [ ] Smoke-тест на трёх моделях по умолчанию возвращает валидный JSON классификации (лог в PR).
- [x] Исчезновение модели не ломает запуск — профиль деактивируется с предупреждением.
- [ ] `make lint && make test` зелёные; Definition of Done из AGENTS.md §8 выполнен.

## Как проверить
```bash
python -m app.llm.smoke --profile or_gpt_oss_120b
```

## Отчёт субагента
Ветка `codex/T-048-openai-sdk`, база `f594c43`; T-152 license gate интегрирован cherry-pick `7c7d51d` (исходный `c6d0485`). Push/PR/merge исполнитель не выполнял.

Gap-ревизия: четыре существующих части уже были реализованы — default model IDs, каталог/план деактивации, GET `/key` с отображением остатка лимита, local profile URL. Найдены и исправлены: обязательный SDK отсутствовал (был httpx chat/SSE), master запрещал keyless local и подставлял OpenRouter secret, json_schema fallback расходовал correcting retry, startup не закрывал OpenAI HTTP client; budget брался только из ENV и пропускал unknown usage.

Реализация: официальный `openai==2.54.0`, `AsyncOpenAI` structured/stream, `base_url` профиля, OpenRouter headers, SDK retries=0; одна correcting validation attempt дополнительно к format fallback; token usage агрегируется. Keyless local не отправляет Authorization и не читает `OPENAI_API_KEY`. Local end-to-end: отдельный `LOCAL_LLM_API_KEY` (необязателен); chain привязывает credentials к настроенным base URLs, не отправляет OpenRouter key локальной модели. Bench разрешает local URL из ENV и не выбирает OpenRouter key автоматически; saved local key можно выбрать явно через profile.extra.api_key_id. Миграция: если раньше локальный сервер использовал OPENROUTER_API_KEY, перенесите его значение в LOCAL_LLM_API_KEY. SDK errors показывают kind/status без upstream body; shutdown закрывает HTTP client. Host OpenRouter проверяется точно. 530 lock distributions (93 Python, 437 npm) проверены license gate; новые SDK dependencies — разрешённые лицензии.

Отдельный budget-policy commit `e8bea0e` и review `docs/reviews/T-048-budget-policy.md`: settings.llm override, fail-closed при неизвестном/исчерпанном бюджете или расходе, preflight каждого нового платного completion/retry/stream, неизвестный usage не подменяется нулём. `owl-alpha` без :free больше не обходит budget по hardcoded списку. Это preflight по upstream all-time usage; атомарный денежный потолок требует также server-side лимита ключа. Клиентские деньги и HITL не менялись. Контракты не менялись. Policy review до merge остаётся обязательным.

Реальный smoke не запускался по ограничению текущей ревизии. Для конкретного egress review подготовлен `python -m app.llm.live_smoke --run`: только три заданных ID/HTTPS OpenRouter, до 6 HTTP запросов всего (включая `/key`), max_tokens=128, fixed synthetic text. Границы и отсутствие секретов в отчёте проверены MockTransport; подробности `docs/reviews/T-048-live-smoke.md`. Цены/доступность моделей вживую не подтверждены. Карточка остаётся in_progress до согласования и реального smoke/CI.

Проверки на собственной uv среде/PYTHONPATH, отдельной PostgreSQL16 scratch БД `cx_openai_revision`, APP_ENV=test, LLM_PROVIDER=mock:
- Финальные targeted SDK/budget/chain/CLI/startup/local credentials/bench/roles — 99 passed.
- Полный `make lint` с документированным Node26 `NODE_OPTIONS=--no-experimental-webstorage` — успешно: frontend 144 tests, ruff/format (322 файла), mypy (244 файла), OpenAPI drift 191=191.
- Полный `make test` — exit 0: unit 808 passed/18 skipped, integration 208 passed/4 skipped, scenarios 42 passed/2 skipped, compliance 31 passed, frontend 144 passed. Всего backend 1089 passed/24 skipped.
- После последних pure/local доработок последовательно повторены полный unit suite (817 passed/18 skipped) и затронутые integration setup/settings, ENV editor, LLM routing, benchmark jobs (14 passed). Общая БД и генераторы параллельно не использовались.
- `licenses_check.py --write` и свежесть inventory — успешно, 530 distributions. `git diff --check` — успешно.

Логи: `/tmp/t048-targeted-final.log`, `/tmp/t048-lint.log`, `/tmp/t048-full-test.log`, `/tmp/t048-unit-final.log`, `/tmp/t048-integration-final.log`. Сводка: `/tmp/t048-verification-report.json`. Реальные LLM/Telegram/email не вызывались. Budget policy и предлагаемый bounded egress должны пройти отдельный review; CI и реальные smoke логи ещё не получены.


## Одобренный live smoke, 2026-11-02

После явного согласования пользователя PR159 выполнен один bounded запуск:5 из 6 HTTP-запросов, 3 фиксированные модели, max_output_tokens=128. Результат:1 `bad_output` и 2 `unavailable` HTTP 404; успешный structured ответ не подтверждён. Actual tokens/USD неизвестны, не считаются нулевыми. Повторных запусков/замен нет. Подробности и safe JSON: `docs/reviews/T-048-live-smoke.md`, `docs/reviews/T-048-live-smoke-result.json`. Ранние записи «не вызывались» выше описывают этап до этого согласования. Карточка остаётся in_progress до актуализации каталога T-047 и положительной live-проверки; schema/guard не ослаблены.
