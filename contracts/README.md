# Контракты CX Pulse Control (v1.4)

Источник истины для backend, frontend, бота и генераторов данных. Соответствует ТЗ v1.4 (`docs/TZ.md`). v1.4 (дополнительное ТЗ, разделы 0.6, 3.7, 7, 9.7, 12.2, 20.6, 22.8–22.9): приёмный слой (`ingest_sources`, `ingest_messages`, `transcripts`, `signals.geo/sentiment/transcript_id`), эскалации и тикетница (`escalations`, `v_tickets`, `incidents.routing_status/problem_summary`), семейство `conduct` в таксономии нарушений, `service_scripts`, пакетные сессии (`audio_sessions.pacing`), зоны карты (`v_map_zones`, `economics_settings.map_zone_thresholds`); события `ingest.*`, `escalation.*`, `zone.changed`; теги API `ingest`, `tickets`, `escalations`; роутер-инструменты агента и цепочка решений. v1.2: таблица `sim_runs`, колонка `run_id` во всех таблицах данных, `run_id` в конверте событий, эндпоинты `/api/sim/runs*`, `/api/sim/baseline*`, действия `stop`/`resume` (ТЗ 4.6). v1.3 (BRD демо-стенда, ТЗ 21–22): Mock-АБС (`accounts`, `tariffs`, `ledger_entries`), бизнес-правила (`business_rules`, `rule_evaluations`), внешние площадки (`external_posts`, `external_replies`), отделения и аудиомониторинг (`branches`, `employees`, `audio_sessions`, `utterances`, `misselling_patterns`, `compliance_triggers`, `compliance_alerts`, `stt_metrics`), подстраховка (`llm_cassettes`, `demo_assets`); новые семейства событий `review.*`, `abs.*`, `compliance.*`, `demo.failover`; теги API `feed`, `abs`, `rules`, `compliance`, `stt`, `demo`; бинарный WebSocket `/ws/audio/{session_id}`.

| Каталог | Что внутри | Потребители |
|---|---|---|
| `db/schema.sql` | DDL PostgreSQL 16: 74 таблицы, 9 представлений, триггеры лога изменений, каналы NOTIFY | SQLAlchemy-модели, сид, миграция `0001` |
| `db/migrations/0002_brd_contours.sql` | Идемпотентный SQL контуров BRD (ALTER/CREATE IF NOT EXISTS): no-op на чистой БД после `0001`, обновляет базы v1.2 | миграция `0002` |
| `db/migrations/0003_additional_tz.sql` | Идемпотентный SQL дополнительного ТЗ (v1.4): no-op на чистой БД после `0001`, обновляет базы v1.3 | миграция `0003` |
| `db/alembic/` | `alembic.ini`, `env.py`, `script.py.mako`, `versions/0001_initial_schema.py` (исполняет schema.sql), `versions/0002_brd_contours.py`, `versions/0003_additional_tz.py` (исполняют migrations/000N) | backend |
| `api/openapi.yaml` | OpenAPI 3.1 (1.4.0): 131 путь по 24 тегам, 111 схем, описание WebSocket `/ws/stream` и бинарного `/ws/audio/{session_id}` | FastAPI-роутеры (сверка через `schemathesis`), генерация TS-клиента |
| `events/common.schema.json` | Единые перечисления: сегменты, продукты, системы, команды, каналы, типы сигналов, статусы, психотипы, состояния клиента | генерация `enums.py` / `enums.ts` |
| `events/envelope.schema.json` | Конверт события симулятора; `allOf/if` выбирает схему payload по `event_type` | шина `sim_events`, NOTIFY |
| `events/sim/*.schema.json` | Payload событий: `op.*`, `fault.*`, `fault.regression`, `client_error.*`, `signal.*`, `team.*`, `sla.*`; v1.3: `review.*` (посты площадки), `abs.*` (проводки Mock-АБС) | симулятор, тесты |
| `events/compliance/*.schema.json` | v1.3: `session_event` (`compliance.*`), `misselling_verdict` (structured output детектора), `speaker_attribution`, `stt_result` (сообщения `/ws/audio`) | `app/compliance`, `app/stt`, экраны `/compliance`, `/manager` |
| `events/rules/rule_condition.schema.json` | v1.3: DSL условий `business_rules.condition` | `app/rules`, экран настроек правил |
| `events/demo/failover.schema.json` | v1.3: событие `demo.failover` | `app/demo`, бейдж режима |
| `events/ingest/*.schema.json` | v1.4: `unified_message` (единая схема сообщения — канал, клиент, текст, timestamp, гео), `transcript` (JSON-формат готового транскрипта; TXT конвертируется в него), `ingest_event` (`ingest.*`) | `app/ingest`, адаптеры, вкладка «Транскрипты» |
| `events/compliance/transcript_report.schema.json` | v1.4: structured output пакетного анализа транскрипта — находки по семействам с цитатами, `fact_check`, рекомендации, соблюдение скрипта | `app/compliance/batch.py`, отчёт руководителю |
| `events/sim/escalation.schema.json`, `events/sim/zone.schema.json` | v1.4: `escalation.*`, `zone.changed` | `app/tickets`, карта |
| `events/behavior/*.schema.json` | Параметры психотипа (`psychotypes.params`) и события `client.*` модели поведения | `app/sim/behavior`, настройки |
| `events/agent/*.schema.json` | Structured output узлов агента: `classification`, `decision`, `client_twin_reaction`; v1.3: `normalization`, `client_match`, `rule_violation`, `instant_decision`; v1.4: `router_tools` (сигнатуры `route_to_department` / `notify_customer` / `escalate_to_manager` / `request_clarification`), `decision_chain` (ответ `/decision-chain`), поля `sentiment`, `hidden_negativity`, `problem_summary`, `router_action`; запись `tool_call` (+ 6 инструментов v1.3) | `app/agent/schemas.py` (Pydantic), промпты, бенчмарки |
| `events/ws/message.schema.json` | Сообщения WebSocket и команды подписки | `app/realtime`, `frontend/src/shared/api/ws.ts` |

## Соглашения
- `snake_case` везде; `*_at` — реальное время, `*_sim` — симуляционное.
- Перечисления и статусы в `schema.sql` (CHECK) и в `common.schema.json` обязаны совпадать; тест `tests/unit/test_contracts_sync.py` сравнивает их.
- JSON Schema draft 2020-12; `$id` — абсолютные, `$ref` — относительные. Валидация примеров: `make contracts-check` (jsonschema + openapi-spec-validator + pglast).
- Ключевые сценарии ТЗ 18 имеют эталонные примеры событий в `backend/tests/scenarios/fixtures/` — они обязаны проходить валидацию этими схемами.

## Генерация кода из контрактов (`make sync-contracts`)
1. `schema.sql` → `backend/schema.sql` (копия) → `alembic upgrade head`.
2. `common.schema.json` → `backend/app/contracts/enums.py` (`StrEnum`) и `frontend/src/shared/contracts/enums.ts`.
3. `events/agent/*.json` → `backend/app/agent/schemas.py`, `events/compliance|rules|ingest/*.json` → соответствующие `schemas.py` через `datamodel-code-generator` (Pydantic v2).
4. `api/openapi.yaml` → `frontend/src/shared/api/types.ts` через `openapi-typescript`.
5. FastAPI генерирует собственный OpenAPI; CI сравнивает его с `contracts/api/openapi.yaml` (`scripts/check_openapi_drift.py`) и падает при расхождении.

## Версионирование
- Правка контрактов — только по процедуре `AGENTS.md` раздел 7.
- Несовместимые изменения JSON-схем — новый файл с суффиксом `_v2`, старый остаётся до миграции потребителей.
- Миграция `0001` неизменяема; дальнейшие изменения БД — новые ревизии. `schema.sql` остаётся полным актуальным DDL (его исполняет `0001` на чистой БД), а каждая следующая ревизия исполняет идемпотентный SQL из `db/migrations/NNNN_*.sql`, чтобы `upgrade head` работал и на чистой, и на ранее созданной базе.
