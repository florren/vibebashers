# T-221 — Миграция 0003 и OpenAPI 1.4 в коде: модели SQLAlchemy, перечисления v1.4, роутеры-заглушки ingest/tickets/escalations, TS-типы

| Поле | Значение |
|---|---|
| Эпик | E18 Приём транскриптов, роутер-инструменты, «красные фразы», зоны карты [ДТЗ] |
| Субагент | `SA-DB` (БД, миграции, генерация из контрактов, тесты данных) |
| Оценка | S (≤ 0,5 дня) |
| Волна | 2 |
| Слой | `L1` Базис (владелец — см. docs/TEAM-SPLIT.md и CODEOWNERS) |
| В демо-минимуме | да |
| Статус | `done` |

## Цель
Контракты v1.4 доступны в коде до начала узлов E18: применена 0003, сгенерированы Pydantic/TS, заглушки возвращают 501 с корректными схемами (AGENTS.md §7).

## Разделы ТЗ (docs/TZ.md)
§13, §3.7, §9.7

## Контракты
- `db/migrations/0003_additional_tz.sql`
- `db/alembic/versions/0003_additional_tz.py`
- `api/openapi.yaml 1.4.0`
- `events/ingest/*, events/agent/router_tools|decision_chain, events/sim/escalation|zone, events/compliance/transcript_report`

## Зависимости
- Зависит от: [T-199](T-199-migraciya-0002-primenenie-modeli-sqlalchemy-i-pe.md), [T-200](T-200-openapi-1-3-i-json-shemy-v-kode-routery-zaglushk.md)
- Блокирует: [T-207](T-207-edinaya-shema-soobscheniya-i-normalizator-ingest.md)

## Что сделать
1. alembic upgrade head на чистой БД и на дампе v1.3 — оба проходят; downgrade 0003 возвращает v1.3; тест идемпотентности (повторный прогон SQL — no-op).
2. make sync-contracts: enums.py/enums.ts с новыми перечислениями (sentiment, severity, router_action, routing_status, violation_family, alert_policy, pacing, transcript_kind, zone); datamodel-codegen для events/ingest; openapi-typescript 1.4.
3. Роутеры-заглушки FastAPI для тегов ingest, tickets, escalations и новых путей compliance/map/metrics/bench (501 + Problem), чтобы фронт мог собираться.
4. Модели SQLAlchemy: transcripts, ingest_sources, ingest_messages, escalations, service_scripts; представления v_tickets/v_map_zones как read-only модели.

## Критерии приёмки
- [ ] alembic upgrade head проходит на пустой БД и на дампе v1.3; contracts_check зелёный.
- [ ] Фронт и бэкенд собираются с типами 1.4.
- [ ] `make lint && make test` зелёные; Definition of Done из AGENTS.md §8 выполнен.

## Как проверить
```bash
alembic upgrade head && alembic downgrade 0002 && alembic upgrade head
make sync-contracts && make lint
```

## Отчёт субагента
Коммит B01. Миграция 0003 в коде (`backend/alembic/versions/0003_additional_tz.py`, `migrations/0003_additional_tz.sql`), downgrade до 0002 и обратно проверены интеграционным тестом; модели 74 таблиц; Pydantic для `ingest/*`, `sim/zone`, `sim/escalation`, `compliance/*`; роутеры тегов `ingest`, `tickets`, `escalations`, `rules`, `compliance`, `stt`, `demo` — 501-заглушки с карточками; дрейф OpenAPI 1.4.0 = 0.
