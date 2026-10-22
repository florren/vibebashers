# T-199 — Миграция 0002: применение, модели SQLAlchemy и перечисления v1.3

| Поле | Значение |
|---|---|
| Эпик | E1 Каркас, БД, установка |
| Субагент | `SA-DB` (БД, миграции, генерация из контрактов, тесты данных) |
| Оценка | M (1–2 дня) |
| Волна | 2 |
| Слой | `L1` Базис (владелец — см. docs/TEAM-SPLIT.md и CODEOWNERS) |
| В демо-минимуме | да |
| Статус | `todo` |

## Цель
Контракт БД v1.3 в коде: новые таблицы/колонки/CHECK, модели ORM, alembic 0002 идемпотентна на чистой и на v1.2-базе.

## Разделы ТЗ (docs/TZ.md)
§13, §3.4, §22

## Контракты
- `db/schema.sql`
- `db/migrations/0002_brd_contours.sql`
- `db/alembic/versions/0002_brd_contours.py`
- `events/common.schema.json`

## Зависимости
- Зависит от: [T-005](T-005-primenenie-schema-sql-sqlalchemy-modeli-sessii.md), [T-006](T-006-sync-contracts-generaciya-enums-pydantic-shem-ts.md)
- Блокирует: [T-221](T-221-migraciya-0003-i-openapi-1-4-v-kode-modeli-sqlal.md)

## Что сделать
1. make sync-contracts копирует migrations/ в backend/; alembic upgrade head на чистой БД (0001 v1.3 + 0002 no-op) и на дампе v1.2 (0002 применяет изменения) — оба пути в тесте.
2. Модели для 17 новых таблиц и новых колонок; alembic check без дрейфа; gen_enums подхватывает новые $defs (incident_type, signal_origin, misselling_pattern, …).
3. Триггеры db_activity на ledger_entries, external_posts, audio_sessions, compliance_triggers проверены тестом.
4. Baseline-снимок включает новые таблицы; downgrade 0002 возвращает v1.2.

## Критерии приёмки
- [ ] alembic upgrade head / downgrade -1 / upgrade head проходят на обоих стартовых состояниях.
- [ ] test_contracts_sync зелёный после регенерации.
- [ ] `make lint && make test` зелёные; Definition of Done из AGENTS.md §8 выполнен.

## Как проверить
```bash
cd backend && alembic upgrade head && alembic check
pytest backend/tests/integration/test_schema_v13.py
```

## Отчёт субагента
_Заполняется исполнителем: ветка/PR, что сделано, отклонения от карточки, затронутые контракты, скриншоты/логи, время._
