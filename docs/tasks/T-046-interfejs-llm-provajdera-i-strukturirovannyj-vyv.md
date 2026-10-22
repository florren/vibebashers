# T-046 — Интерфейс LLM-провайдера и структурированный вывод

| Поле | Значение |
|---|---|
| Эпик | E4 LLM-слой |
| Субагент | `SA-LLM` (LLM-слой) |
| Оценка | M (1–2 дня) |
| Волна | 1 |
| Слой | `L1` Базис (владелец — см. docs/TEAM-SPLIT.md и CODEOWNERS) |
| В демо-минимуме | да |
| Статус | `done` |

## Цель
Единая абстракция для GigaChat, OpenAI-совместимых API и mock с валидацией JSON по Pydantic-схемам.

## Разделы ТЗ (docs/TZ.md)
§5.2, §9, §12.5

## Контракты
- `events/agent/*.schema.json`
- `db/schema.sql: llm_profiles, agent_steps`

## Зависимости
- Зависит от: [T-004](T-004-karkas-fastapi-konfig-logirovanie-oshibki-health.md), [T-006](T-006-sync-contracts-generaciya-enums-pydantic-shem-ts.md)
- Блокирует: [T-009](T-009-api-mastera-nastrojki-i-proverok-podklyucheniya.md), [T-036](T-036-emulyator-komand-i-cifrovoj-sled-incidenta.md), [T-047](T-047-gigachat-provajder-s-pulom-klyuchej-i-uchetom-to.md), [T-048](T-048-openai-sovmestimyj-provajder-openrouter-i-lokaln.md), [T-049](T-049-mock-provajder-pravila-shablony-determinizm.md), [T-056](T-056-agentstate-graf-langgraph-checkpointer-zapusk-po.md), [T-060](T-060-uzel-classify-i-prompty-v1.md), [T-163](T-163-llm-dvojniki-podsvechennyh-klientov.md), [T-183](T-183-audiosessii-repliki-i-tri-rezhima-razdeleniya-sp.md), [T-194](T-194-provajder-replay-kassety-zapisannyh-otvetov-mode.md)

## Что сделать
1. app/llm/provider.py: Protocol с complete_structured(messages, schema_model, profile) → (obj, usage, raw, reasoning), stream(...) → async iterator дельт (kind reasoning/content/tool_args), capabilities().
2. Стратегия structured output: native JSON schema/function calling, если поддерживается; иначе инструкция + извлечение JSON-блока; один retry с текстом ошибок валидации; затем исключение StructuredOutputError для fallback.
3. Учёт usage (prompt/completion tokens, latency) и возврат сырых ответов для трассировки.
4. Регистр профилей из БД с горячей перезагрузкой при изменении настроек.

## Критерии приёмки
- [ ] Юнит-тесты на извлечение JSON из «грязных» ответов (markdown-блоки, преамбула).
- [ ] Невалидный ответ → retry → ошибка, без падения процесса.
- [ ] `make lint && make test` зелёные; Definition of Done из AGENTS.md §8 выполнен.

## Как проверить
```bash
pytest backend/tests/unit/test_llm_provider.py
```

## Отчёт субагента
Коммит B02 в `main`. `backend/app/llm/base.py`: `Provider` (Protocol) с `complete_structured(messages, schema, profile, timeout_s) -> (obj, usage, raw)` и `stream(...)`, `LLMProfile` (поля llm_profiles + стоимость), `Usage` (prompt/completion/latency/cost_rub/source/key_label), `ProviderError(kind)` (auth, rate_limit, quota, timeout, network, bad_output, miss, unavailable), `extract_json` (JSON из ответа с ```json и мусором), `normalize_messages`. Схемы контрактов разыменовываются `app/contracts/registry.py` (`deref`, `validate`, `validate_schema`, реестр `referencing`). Структурированный вывод: инструкция «только JSON по схеме» → разбор → jsonschema-валидация → одна повторная попытка с перечнем ошибок. `python -m app.llm.smoke` — дымовой прогон цепочки.
