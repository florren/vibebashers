# T-196 — Автоматический failover по таймауту и ошибкам LLM/STT без разрыва цепочки

| Поле | Значение |
|---|---|
| Эпик | E17 Режим подстраховки демо [BRD] |
| Субагент | `SA-Agent` (агент LangGraph) |
| Оценка | S (≤ 0,5 дня) |
| Волна | 3 |
| Слой | `L3` Агент и контуры (владелец — см. docs/TEAM-SPLIT.md и CODEOWNERS) |
| В демо-минимуме | да |
| Статус | `done` |

## Цель
Быстрый путь и детектор не зависают: LLM-шаг > 8 с (агент) или > 2 с (детектор) → replay → mock с пометкой; STT-ошибка → транскрипт эталона для source=file (ТЗ 12.7, 16.4, 22.4).

## Разделы ТЗ (docs/TZ.md)
§12.7, §16.4, §21.4, §22.4

## Контракты
- `events/demo/failover.schema.json`
- `db/schema.sql: agent_runs.outcome = fallback_mock, agent_steps.status = fallback`

## Зависимости
- Зависит от: [T-194](T-194-provajder-replay-kassety-zapisannyh-otvetov-mode.md), [T-174](T-174-bystryj-put-agenta-uslovnoe-rebro-act-instant-st.md), [T-185](T-185-llm-detektor-missellinga-lightning-podtverzhdeni.md)
- Блокирует: —

## Что сделать
1. app/llm/failover.py: обёртка с таймаутами по контексту (fast_path 8 с, detector 2 с, default 30 с), цепочка провайдеров, событие demo.failover(automatic=true), шаг agent_steps.status=fallback с указанием источника.
2. STT: при ошибке воркера для source=file — переключение на transcript эталона с пометкой; для mic — сообщение error в /ws/audio и подсказка на экране.
3. Метрика доли fallback-шагов на экране бенчмарков и в summary запуска.

## Критерии приёмки
- [ ] Имитация таймаута GigaChat на быстром пути → цепочка завершается на кассете/моке ≤ 15 с, инцидент и ответ созданы, шаг помечен fallback.
- [ ] Событие demo.failover валидно по схеме.
- [ ] `make lint && make test` зелёные; Definition of Done из AGENTS.md §8 выполнен.

## Как проверить
```bash
pytest backend/tests/unit/test_failover.py
```

## Отчёт субагента
Коммит B02. `app/llm/failover.py` — `ProviderChain`: таймауты по контексту (`fast_path` 8 с, `detector` 2 с, `default` 30 с; `asyncio.wait_for`), любая ошибка/таймаут/исключение → следующий провайдер → mock (всегда замыкает цепочку), `ChainResult` с `attempts`, `fallback_mock`, `error` (для `agent_runs.error`), rate limiter per profile (`app/llm/ratelimit.py`: token bucket rpm + суточный rpd, при исчерпании — rate_limit → failover), запись кассет при LLM_RECORD. `stream` — failover до первого чанка. `build_chain(settings)` собирает цепочку из `LLM_CHAIN`, пропуская провайдеров без ключей; подключён в lifespan (`app.state.llm_chain`), `/api/health.llm` показывает провайдеров. Тесты: failover gigachat(429)→openai(auth)→mock, таймаут detector, stream failover, rpm/rpd лимиты.
