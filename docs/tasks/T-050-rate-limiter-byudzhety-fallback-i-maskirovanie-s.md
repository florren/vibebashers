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
