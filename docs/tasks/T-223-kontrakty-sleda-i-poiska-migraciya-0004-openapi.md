# T-223 — Контракты следа и поиска: миграция 0004, OpenAPI 1.5.0, схемы trace/*, public_id объектов, индексы

| Поле | Значение |
|---|---|
| Эпик | E22 Сквозная демонстрация «Путь обращения» [АРХ] |
| Субагент | `SA-DB` (БД, миграции, генерация из контрактов, тесты данных) |
| Оценка | M (1–2 дня) |
| Волна | 7 |
| Слой | `L1` Базис (владелец — см. docs/TEAM-SPLIT.md и CODEOWNERS) |
| В демо-минимуме | да |
| Статус | `todo` |

## Цель
Контракты для «Пути обращения» и «Поиска и следа» существуют до начала кода: идентификаторы у всех объектов цепочки, индексы поиска, пути и схемы ответов (AGENTS.md §7, метка `contract-change`).

## Разделы ТЗ (docs/TZ.md)
§13, §27.5, §28.2, §28.3, §28.6, §20.7

## Контракты
- `db/migrations/0004_trace_search.sql`
- `db/alembic/versions/0004_trace_search.py`
- `db/schema.sql (v1.5)`
- `api/openapi.yaml 1.5.0: /api/search, /api/trace/{kind}/{ref}, /api/journey/{ref}, /api/journey/latest`
- `events/trace/trace_event.schema.json, trace_response.schema.json, search_response.schema.json, journey.schema.json`
- `events/common.schema.json: trace_event_kind, trace_phase, trace_actor, journey_stage, journey_message_kind`
- `CODEOWNERS`

## Зависимости
- Зависит от: [T-199](T-199-migraciya-0002-primenenie-modeli-sqlalchemy-i-pe.md), [T-200](T-200-openapi-1-3-i-json-shemy-v-kode-routery-zaglushk.md), [T-221](T-221-migraciya-0003-i-openapi-1-4-v-kode-modeli-sqlal.md)
- Блокирует: [T-224](T-224-sborschik-sleda-app-trace-kauzalnyj-obhod-fazy-d.md), [T-230](T-230-universalnyj-poisk-app-search-raspoznavanie-iden.md), [T-237](T-237-kontrakty-kabineta-csi-i-vsp-migraciya-0005-open.md)

## Что сделать
1. Идемпотентный SQL 0004: генерируемые `public_id` — `agent_runs` (`AR-`, 6 цифр), `sim_runs` (`SR-`, 4), `tasks` (`TSK-`), `notifications` (`NTF-`), `ledger_entries` (`LED-`), `human_decisions` (`HD-`), `followups` (`FUP-`) через `ADD COLUMN IF NOT EXISTS … GENERATED ALWAYS AS … STORED`; `CREATE EXTENSION IF NOT EXISTS pg_trgm` (разрешено: 20.7 № 72, ADR-0008).
2. Индексы: GIN `to_tsvector('russian', …)` по `signals.text`, `incidents.title`, `external_posts.text`; триграммные по `public_id`-колонкам и `clients.social_handles`; аудит и добавление недостающих индексов по внешним ключам цепочки (`incident_signals`, `notifications`, `tasks`, `external_replies`, `client_reactions`, `followups`, `human_decisions`, `escalations`, `ledger_entries.operation_id/agent_run_id`).
3. Alembic 0004 (downgrade возвращает v1.4), обновить шапку `schema.sql` (v1.5), `contracts_check.py` учитывает 0004; тест идемпотентности и применения на дампе v1.4.
4. JSON-схемы `events/trace/*` по ТЗ 27.5 и 28.3 (TraceEvent, TraceEdge, TraceGroup, PendingStep, Terminal, JourneyResponse, ClientMessage, SearchResponse) и перечисления в `common.schema.json` только добавлением; фиксируется итоговый перечень `trace_event_kind`.
5. OpenAPI 1.5.0: четыре пути, теги `search`, `trace`, `journey`, параметры `run_id`, `before_depth`, `after_limit`, `include`; `make sync-contracts` (Pydantic и TS-типы); роутеры-заглушки 501 в `backend/app/api/` (метка cross-layer, как в T-221).
6. CODEOWNERS: `backend/app/trace/`, `backend/app/search/`, `backend/app/analytics/` — L3; `frontend/src/pages/{journey,trace,cabinet,csi}/` — L4; проверка `check_owners.py`.

## Критерии приёмки
- [ ] `alembic upgrade head` на пустой БД и на дампе v1.4; `downgrade 0003` и повторный `upgrade` проходят; повторный прогон SQL — no-op.
- [ ] `python scripts/contracts_check.py` зелёный; типы Pydantic/TS сгенерированы; фронт и бэкенд собираются.
- [ ] PR помечен `contract-change`, подтверждён техлидом.
- [ ] `make lint && make test` зелёные; Definition of Done из AGENTS.md §8 выполнен.

## Как проверить
```bash
alembic upgrade head && alembic downgrade 0003 && alembic upgrade head
python scripts/contracts_check.py && make sync-contracts && make lint
```

## Отчёт субагента
_Заполняется исполнителем: ветка/PR, что сделано, отклонения от карточки, затронутые контракты, скриншоты/логи, время._
