# T-207 — Единая схема сообщения и нормализатор ingest: signals.geo/sentiment, каскад гео, journal ingest_messages

| Поле | Значение |
|---|---|
| Эпик | E18 Приём транскриптов, роутер-инструменты, «красные фразы», зоны карты [ДТЗ] |
| Субагент | `SA-Agent` (агент LangGraph) |
| Оценка | M (1–2 дня) |
| Волна | 2 |
| Слой | `L3` Агент и контуры (владелец — см. docs/TEAM-SPLIT.md и CODEOWNERS) |
| В демо-минимуме | да |
| Статус | `todo` |

## Цель
Все входы (симулятор, API, лендинг, бот, площадка, голос, транскрипты, адаптеры) проходят через app/ingest/normalizer.py и создают signals в единой схеме с гео (ДТЗ FR-1.3, ТЗ 3.7, решение 20.6 п. 27).

## Разделы ТЗ (docs/TZ.md)
§3.6, §3.7, §13, §20.6

## Контракты
- `events/ingest/unified_message.schema.json`
- `events/common.schema.json: geo, geo_source, sentiment, signal_origin`
- `db/schema.sql: signals.geo, signals.sentiment, ingest_messages`
- `api/openapi.yaml: POST /api/ingest/messages, Geo, IngestResult`

## Зависимости
- Зависит от: [T-221](T-221-migraciya-0003-i-openapi-1-4-v-kode-modeli-sqlal.md), [T-056](T-056-agentstate-graf-langgraph-checkpointer-zapusk-po.md), [T-058](T-058-instrumenty-zapisi-i-pobochnyh-effektov.md)
- Блокирует: [T-208](T-208-priem-transkriptov-json-txt-parsery-post-api-ing.md), [T-209](T-209-adaptery-istochnikov-ingest-sources-rest-polling.md), [T-210](T-210-trehklassnaya-tonalnost-sentiment-prompt-soglaso.md), [T-213](T-213-router-instrumenty-route-to-department-notify-cu.md), [T-218](T-218-karta-sloj-zony-zelenaya-zheltaya-krasnaya-po-v.md)

## Что сделать
1. app/ingest/schemas.py (Pydantic из JSON-схемы), app/ingest/normalizer.py: функции from_sim_event/from_api_signal/from_landing/from_bot/from_external_post/from_voice/from_transcript/from_adapter → UnifiedMessage; единая точка create_signal_from_message().
2. Каскад гео: город клиента → регион контакта → geo сообщения → ip_mock (только demo-профиль, помечается) → none; счётчик «без гео» в метриках.
3. POST /api/ingest/messages (одно сообщение или массив ≤ 500): валидация, запись в ingest_messages со статусом accepted/duplicate/rejected по (source_code, external_id), создание сигнала; события ingest.message_*.
4. Поле signals.sentiment заполняется после normalize (T-210); до этого null.
5. Тесты: каждый вход даёт валидный UnifiedMessage; дубль по external_id → duplicate; гео-каскад на 5 случаях.

## Критерии приёмки
- [ ] Любой сигнал в БД имеет geo (или source=none) и создан через normalizer — проверка в тесте по трассировке вызовов.
- [ ] Повтор POST с тем же external_id не создаёт второй сигнал.
- [ ] `make lint && make test` зелёные; Definition of Done из AGENTS.md §8 выполнен.

## Как проверить
```bash
pytest backend/tests/unit/test_ingest_normalizer.py backend/tests/integration/test_ingest_messages.py
```

## Отчёт субагента
Ветка `feat/b04-agent`. `backend/app/ingest/normalizer.py`: from_api_signal/from_sim_event → UnifiedMessage (валидация `ingest/unified_message`), `create_signal` — ingest_messages (идемпотентность по (source_code, external_id): accepted/duplicate/rejected), signals (geo, external_contact, origin), событие signal.received в sim_events + NOTIFY sim_events (его слушает AgentService) + NOTIFY signals.created. API: POST /api/ingest/messages (объект или массив ≤500, заголовок X-Source-Code, 202 {items}), POST /api/signals (жюри-режим; ждёт прохода агента и возвращает agent_run_id), GET /api/signals (фильтры/курсор), GET /api/signals/{id}, GET /api/signals/deferred; плюс GET /api/incidents(+/{id}, /history, /signals, /communications), /api/hitl/queue, /api/hitl/{id}, /api/agent/runs, /api/agent/runs/{id}, /api/agent/graph, /api/agent/runs/{id}/decision-chain (json|markdown). В `data/ingest_sources.yaml` добавлен источник `api`. openapi drift = 0. **Отклонение:** транскрипты (/api/ingest/transcripts) и polling-адаптеры — отдельные карточки. Время: ~1 ч.
