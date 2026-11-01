# T-059 — Узлы ingest, normalize, identify_client, gather_context

| Поле | Значение |
|---|---|
| Эпик | E5 Агент LangGraph |
| Субагент | `SA-Agent` (агент LangGraph) |
| Оценка | M (1–2 дня) |
| Волна | 3 |
| Слой | `L3` Агент и контуры (владелец — см. docs/TEAM-SPLIT.md и CODEOWNERS) |
| В демо-минимуме | да |
| Статус | `done` |

## Цель
Подготовка контекста: нормализация текста, идентификация клиента, сбор операций/логов/истории.

## Разделы ТЗ (docs/TZ.md)
§6 шаги 1–2, §9.1

## Контракты
- `events/sim/signal.schema.json`

## Зависимости
- Зависит от: [T-057](T-057-instrumenty-chteniya-konteksta.md)
- Блокирует: [T-060](T-060-uzel-classify-i-prompty-v1.md), [T-173](T-173-matching-klienta-po-kosvennym-dannym-match-clien.md), [T-210](T-210-trehklassnaya-tonalnost-sentiment-prompt-soglaso.md)

## Что сделать
1. normalize: язык, очистка, извлечение сумм/дат/масок карт регулярками (как подсказки, не замена LLM).
2. identify_client: по client_id, иначе по контактам external_contact (точное совпадение телефона/email/ника) → клиент или «неидентифицированный».
3. gather_context: вызовы инструментов чтения, компактная сводка для промпта (≤ 2 500 токенов), список активных сбоев по системам продукта.

## Критерии приёмки
- [ ] Неидентифицированный сигнал проходит без ошибок (контекст пуст).
- [ ] Сводка контекста содержит найденный error_code при наличии сбоя в окне ±2 сим-часа.
- [ ] `make lint && make test` зелёные; Definition of Done из AGENTS.md §8 выполнен.

## Как проверить
```bash
pytest backend/tests/unit/test_nodes_context.py
```

## Отчёт субагента
Ветка `feat/b04-agent`, `backend/app/agent/nodes.py`: ingest (status processing + NOTIFY signals), normalize (regex-подсказки сумма/карта/промо/операция + LLM normalization, пост-проверки тональности, запись signals.sentiment/lang), identify_client (client_id → профиль; иначе ник в social_handles → card_last4+регион; запись client_id в сигнал), gather_context (продукты/операции/сбои/связанные инциденты/похожие сигналы; hints по неуспешным операциям клиента; активные сбои без операции — только подсказка), check_rules (движок `app/rules/engine.py` по business_rules → rule_evaluations). Промпты: `app/agent/prompts/v1/{system,normalize,classify,decide}.md` с frontmatter (version, model_hints, output_schema); системное сообщение = system.md + промпт узла с контекстом, user = только текст клиента (так MockProvider и реальная модель видят одно и то же). Время: ~1 ч.

Доработка 29.10.2026: нормализация уже использовала LLM fast, однако bad_output Lightning приводил сразу к mock. Теперь перед mock пробуется настроенная main-модель (без жёстко заданного имени), с общим бюджетом fast_path. Явные mock/replay не включают live. В input шага сохраняются llm_attempts и fallback_reason; допустимые нули negativity/confidence не заменяются значениями по умолчанию. На контрольной выборке 9/9 валидных live-ответов, включая текст SIG-080097; подробности и ограничения — docs/benchmarks/normalization-live-2026-10-29/.

Follow-up 01.11.2026, ветка `codex/fix-money-normalization` от `f594c43`: обнаружен независимый defect financial input — `5472.45 рублей` превращалось в 45.0 одновременно в regex_hints и MockProvider.normalize. Общий Decimal parser `app/amounts.py` теперь сохраняет полный токен, decimal comma/dot и корректные группы тысяч; частичные дроби/группы не извлекаются. Выбор первой суммы сохраняется. JSON hint — finite number, источником refund остаются существующие rules/ledger; политики money/HITL и контракты не менялись. Assertions/cassettes T-017 не менялись; исходный deferred T-017 имеет отдельные причины, этот fix не объявляется его полным решением.

Перед merge требуется отдельное ревью financial input boundary: `docs/reviews/T-059-money-normalization.md`. Проверено: 137 targeted unit tests; 1 synthetic decimal graph/ledger integration (на финальном коде повторно 1 passed); полный make lint (frontend 144, ruff/format319, mypy243, OpenAPI191=191). Полный `make test` завершился exit 0: backend 1062 passed/24 skipped (unit780/18, integration209/4, scenarios42/2, compliance31), frontend144 passed. После двух последних pure regressions повторён весь unit suite: 782 passed/18 skipped. Все DB-проверки только на отдельной scratch БД `cx_money_normalization_revision`, LLM mock; генерация unit models и DB suites выполнялись последовательно. Реальных LLM/Telegram/email вызовов нет. Code review financial input boundary и CI до merge остаются обязательными. Логи: `/tmp/money-normalization-unit.log`, `/tmp/money-normalization-lint.log`, `/tmp/money-normalization-full-test.log`, `/tmp/money-normalization-final-unit.log`, `/tmp/money-normalization-integration-final.log`; сводка `/tmp/money-normalization-verification.json`.
