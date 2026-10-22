# T-108 — Лента изменений БД, счётчики таблиц, просмотр строк

| Поле | Значение |
|---|---|
| Эпик | E8 «Под капотом» |
| Субагент | `SA-UI-Engine` («Под капотом») |
| Оценка | M (1–2 дня) |
| Волна | 4 |
| Слой | `L4` Фронт (владелец — см. docs/TEAM-SPLIT.md и CODEOWNERS) |
| В демо-минимуме | да |
| Статус | `todo` |

## Цель
Экран 4г: что агент реально записал в базу — INSERT/UPDATE в реальном времени.

## Разделы ТЗ (docs/TZ.md)
§12.2 экран 4, §12.5 приём 5

## Контракты
- `api/openapi.yaml: engine/db/*`
- `db/schema.sql: db_activity_log`

## Зависимости
- Зависит от: [T-005](T-005-primenenie-schema-sql-sqlalchemy-modeli-sessii.md), [T-008](T-008-realtime-listen-notify-websocket-hab.md), [T-007](T-007-karkas-frontend-vite-ts-strict-tailwind-tokeny-t.md)
- Блокирует: —

## Что сделать
1. API engine/db/tables (counts из pg_stat_user_tables + точные для малых), engine/db/tables/{name}/rows с allow-list (signals, incidents, incident_status_history, notifications, tasks, agent_runs, agent_steps, client_states, churn_events, incident_economics, faults), engine/db/activity.
2. UI: лента с фильтром по таблице и корреляцией к run_id, тикер счётчиков, просмотр последних строк (JSON-вьювер).
3. Маскирование contacts в выдаче строк.

## Критерии приёмки
- [ ] Создание инцидента агентом отображается в ленте как цепочка INSERT incidents → incident_signals → incident_status_history → notifications.
- [ ] Таблица вне allow-list → 403.
- [ ] `make lint && make test` зелёные; Definition of Done из AGENTS.md §8 выполнен.

## Как проверить
```bash
pytest backend/tests/integration/test_engine_db_api.py
```

## Отчёт субагента
_Заполняется исполнителем: ветка/PR, что сделано, отклонения от карточки, затронутые контракты, скриншоты/логи, время._
