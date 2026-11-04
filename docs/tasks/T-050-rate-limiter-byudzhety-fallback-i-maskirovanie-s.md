# T-050 — Rate limiter, бюджеты, fallback и маскирование секретов

| Поле | Значение |
|---|---|
| Эпик | E4 LLM-слой |
| Субагент | `SA-LLM` (LLM-слой) |
| Оценка | S (≤ 0,5 дня) |
| Волна | 2 |
| Слой | `L1` Базис (владелец — см. docs/TEAM-SPLIT.md и CODEOWNERS) |
| В демо-минимуме | да |
| Статус | `in_progress` |

## Цель
Симуляция не останавливается при лимитах и сбоях провайдеров; расход прозрачен.

## Разделы ТЗ (docs/TZ.md)
§5.2, §16.4

## Контракты
- `db/schema.sql: llm_api_keys, agent_runs (outcome fallback_mock)`

## Зависимости
- Зависит от: [T-047](T-047-gigachat-provajder-s-pulom-klyuchej-i-uchetom-to.md), [T-048](T-048-openai-sovmestimyj-provajder-openrouter-i-lokaln.md), [T-049](T-049-mock-provajder-pravila-shablony-determinizm.md)
- Блокирует: [T-051](T-051-api-i-ui-profilej-llm-i-klyuchej.md), [T-129](T-129-benchmark-ranner-i-metriki.md)

## Что сделать
1. Token bucket per profile (rpm) + суточный счётчик (rpd) в llm_api_keys; очередь ожидания с таймаутом 20 с, затем fallback.
2. Политика fallback: main → fast → mock; результат помечается outcome=fallback_mock, в UI — бейдж.
3. Единый фильтр логов, маскирующий Authorization/api_key; тест на отсутствие ключей в логах.

## Критерии приёмки
- [ ] При искусственном 429 на main запрос уходит в fast, затем в mock без ошибок для пользователя.
- [ ] Остаток лимитов виден в /api/settings/llm-keys.
- [ ] `make lint && make test` зелёные; Definition of Done из AGENTS.md §8 выполнен.

## Как проверить
```bash
pytest backend/tests/unit/test_ratelimit.py
```

## Отчёт субагента

Дополнение 04.11.2026, `codex/llm-recovery-record`: операторская процедура
`docs/LLM-RECOVERY.md` фиксирует существующий recovery через достоверные
provider observations, приватную backup и штатный reconciliation. Добавлены
четыре PG/provider composition cases без внешней сети: unknown preflight,
SQL numeric через production loader, committed admission, известный usage,
сохранение RPD после пересоздания provider и fail-closed при missing usage.
Новый пакет вместе с существующим accounting suite: 47 passed/30.89s;
Ruff/format578, mypy328, contracts48/167 и owners green. Полный PR CI обязателен.
Политика, caps, API/DDL, денежные формулы и runtime implementation не меняются.
Реальные ключи, dump, индивидуальная статистика и operational DB state в Git
не включаются. Восстановление основного GigaChat/OpenRouter проверено отдельно
live в рабочем контуре; второй GigaChat credential требует собственного
подтверждённого observation, unknown не превращается в известный ноль.
Вся карточка этим дополнением не объявляется завершённой.

Доработка 29.10.2026: если все активные неизрасходованные ключи временно на cooldown после 429, KeyPool сообщает rate_limit с retry_after_s, а не исчерпанную quota. Существующее поведение смешанных quota/cooldown и авторизации сохранено. Ошибки ресурса не инициируют повтор той же операцией через другую модель.


## Ревизия streaming quota, 2026-11-02

Подтверждён и исправлен обход существующего limiter в `ProviderChain.stream`: acquire перед live candidate, общий deadline ожидания/stream I/O, offline bypass, no fallback после первого чанка, cancellation/close освобождают источник. Значения лимитов, модель/ключи, banking/HITL и contracts не менялись. Targeted 53 passed; lint зелёный; failover statement coverage 82%. Review внешнего API-budget enforcement: `docs/reviews/T-050-stream-limits.md`.

T050 остаётся in_progress: persistence ключевых daily counters и API остатки, queue 20s/global-lock и 429→fast policy требуют отдельных coherent packets; централизованный secret filter уже слит в PR #170; эта доработка не закрывает всю карточку. No live/credentials/DB calls. Подробный read-only audit T050/T047: `/tmp/t050-t047-readonly-audit.json`.

Полный unit: 925 passed/18 skipped, exit 0; license gate 526 прошёл. Полный DB suite не запускался по границам packet. Подробные evidence/ограничения — в review.
## Ревизия application secret logging, 2026-11-02

Добавлена единая pure redaction boundary после format_exc_info перед console/JSONL и до HttpStats error retention. Маскируются известные credential fields/labeled strings без чтения env/реальных ключей; nonmutating/idempotent, hints/counters/business IDs сохранены. Подтверждённый T119 unknown-route capability leak закрыт тем же существующим regex/helper и safe_public_path ДО counter keys/ring buffer; API shape/публичные error responses не менялись.

Targeted 37 passed; lint зелёный, coverage redactor/app.logging 100%. Полные evidence/границы: `docs/reviews/T-050-secret-redaction.md`. Нет новых dependencies/DB/live/credential probes или изменений money/HITL. T050 остаётся in_progress; durable counters/rate-policy очередь и fallback требуют отдельных пакетов. Streaming-enforcement реализован отдельно и не смешан с этой веткой.

Полный unit: 953 passed / 18 skipped, exit 0; make lint и license gate 526 прошли. Новый redactor и app.logging имеют 100% statement coverage по stdlib trace. Полный DB/integration suite не запускался: согласованный no-DB packet.


Follow-up parent review: named credential containers внутри diagnostic repr теперь маскируются целиком (list/dict/tuple/nested/quoted/escaped), без eval. Truncated/malformed container скрывает остаток строки; outside IDs после balanced container сохраняются. Targeted 59 passed; lint/100% coverage прошли. Подробности и итог полного unit — в `docs/reviews/T-050-secret-redaction.md`.

Follow-up полный unit: 975 passed / 18 skipped, exit 0; source и credentials/environment boundaries сохранены.

## P2 durable accounting, 2026-11-02

Production wire hooks обоих live providers используют private durable UTC ledger0016/API1.5.21; failed/retry attempts, streaming lower usage floor, unknown provenance и explicit operator reconciliation больше не сводятся к process-local успешным benchmark counters. API/UI показывают known/source/observed floor/server remaining; legacy hint не объявляется подтверждённым расходом. История не откатывается банковским restore; aliases одного physical key делят allowance, conflicting limits fail-closed. Setup binding и configured env endpoint повторно проверяются перед HTTP. Никаких новых численных лимитов/цен/customer money/HITL/auth или реальных HTTP вызовов.

Frozen bc40536:1669 unit/18 skip;435 integration/4 skip/1 Alembic drift failure;43 scenario/2 skip;31 compliance;354 frontend;43 bot. После нормализации pre-release default исходный schema check и ledger52 passed, targeted110 unit passed; полный unit на6c8ae26 —1669 passed/18 skipped; новый lint включает362 frontend, Ruff/mypy/OpenAPI и licenses550+36 green. Это source-qualified evidence, не заявление полного make test green. Final scoped coverage:413 targeted passed,1100/1193=92.20% changed executable statements. Exact-head CI и human API/DDL/external-budget policy review обязательны до merge. Подробные semantics, recovery и итоговые проверки: `docs/reviews/T-050-durable-accounting.md`; UI proof: `docs/reviews/T-050-quota-ui.md`.

T050 остаётся `in_progress`: очередь20s/limiter lock и main→fast→mock policy требуют отдельных coherent packets. Критерий всей карточки и live DoD не объявлены выполненными.
