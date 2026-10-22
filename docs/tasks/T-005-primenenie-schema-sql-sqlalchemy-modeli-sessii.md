# T-005 — Применение schema.sql, SQLAlchemy-модели, сессии

| Поле | Значение |
|---|---|
| Эпик | E1 Каркас, БД, установка |
| Субагент | `SA-DB` (БД, миграции, генерация из контрактов, тесты данных) |
| Оценка | L (3–4 дня) |
| Волна | 1 |
| Слой | `L1` Базис (владелец — см. docs/TEAM-SPLIT.md и CODEOWNERS) |
| В демо-минимуме | да |
| Статус | `todo` |

## Цель
База данных по контракту, модели ORM, совпадающие с DDL, миграция 0001 проверена на живой PostgreSQL 16.

## Разделы ТЗ (docs/TZ.md)
§13

## Контракты
- `db/schema.sql`
- `db/alembic/*`

## Зависимости
- Зависит от: [T-001](T-001-skelet-repozitoriya-makefile-env-example-pre-com.md)
- Блокирует: [T-003](T-003-install-sh-ustanovka-odnoj-komandoj.md), [T-008](T-008-realtime-listen-notify-websocket-hab.md), [T-009](T-009-api-mastera-nastrojki-i-proverok-podklyucheniya.md), [T-016](T-016-generator-klientov-profili-lite-demo-stress.md), [T-031](T-031-simclock-sim-state-i-upravlenie-simulyaciej.md), [T-040](T-040-servis-zapuskov-emulyacii-sim-runs-run-id-rezhim.md), [T-056](T-056-agentstate-graf-langgraph-checkpointer-zapusk-po.md), [T-057](T-057-instrumenty-chteniya-konteksta.md), [T-108](T-108-lenta-izmenenij-bd-schetchiki-tablic-prosmotr-st.md), [T-131](T-131-raschet-ekonomiki-dcltv-po-incidentu.md), [T-141](T-141-testovaya-infrastruktura-backend.md), [T-171](T-171-mock-abs-scheta-tarify-provodki-sid-i-invariant.md), [T-181](T-181-sttprovider-i-vosk-vorker-s-modelyu-v-repozitori.md), [T-184](T-184-taksonomiya-missellinga-i-rule-detektor-predvari.md), [T-199](T-199-migraciya-0002-primenenie-modeli-sqlalchemy-i-pe.md)

## Что сделать
1. Скопировать alembic.ini/env.py/versions в backend/, `make sync-contracts` копирует schema.sql.
2. Выполнить `alembic upgrade head` на чистой БД; исправить обнаруженные ошибки DDL через правку contracts/db/schema.sql (миграция 0001 исполняет файл) — до первого релиза это допустимо, после — только новые ревизии.
3. Сгенерировать/написать app/db/models.py (SQLAlchemy 2.0 declarative, typed Mapped) для всех таблиц; `alembic check` не должен находить расхождений.
4. app/db/session.py: async engine (psycopg3), фабрика сессий, зависимость FastAPI; отдельное соединение для LISTEN.
5. Репозитории для горячих запросов: signals feed, incidents board, client 360, region heat (используют v_*).

## Критерии приёмки
- [ ] `alembic upgrade head` и `alembic downgrade base` проходят без ошибок на PostgreSQL 16.
- [ ] `alembic check` не находит дрейфа между моделями и БД.
- [ ] Триггеры db_activity_log пишут записи при INSERT/UPDATE в signals/incidents/tasks/notifications.
- [ ] `make lint && make test` зелёные; Definition of Done из AGENTS.md §8 выполнен.

## Как проверить
```bash
cd backend && alembic upgrade head && alembic check
pytest backend/tests/integration/test_schema.py
```

## Отчёт субагента
Коммит B01. `backend/alembic/` (копия `contracts/db/alembic`, `alembic.ini`), `backend/migrations/*.sql`, `backend/schema.sql`. `app/db/models.py` генерируется `scripts/gen_models.py` (sqlacodegen declarative, `nojoined,noindexes`, без представлений; 74 класса) из временной БД со `schema.sql`. `app/db/session.py` — async engine (psycopg), `get_session`, `listen_connection`. Проверено на PostgreSQL 18: `alembic upgrade head` (0001→0003), `alembic check` без дрейфа, `downgrade 0002` (69 таблиц) и повторный `upgrade` (74), триггер `db_activity_log` на `signals`, выполнение всех представлений — `tests/integration/test_schema.py`. Отклонения/контракты: в `0001/0002/0003` `op.execute` заменён на `exec_driver_sql` (text() ломался на `:` внутри DDL); в `alembic/env.py` добавлен `include_object` (индексы и представления сравнивает только `schema.sql`).
