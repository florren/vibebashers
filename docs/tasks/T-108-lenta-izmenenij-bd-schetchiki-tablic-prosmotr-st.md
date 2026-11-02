# T-108 — Лента изменений БД, счётчики таблиц, просмотр строк

| Поле | Значение |
|---|---|
| Эпик | E8 «Под капотом» |
| Субагент | `SA-UI-Engine` («Под капотом») |
| Оценка | M (1–2 дня) |
| Волна | 4 |
| Слой | `L4` Фронт (владелец — см. docs/TEAM-SPLIT.md и CODEOWNERS) |
| В демо-минимуме | да |
| Статус | `in_progress` |

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
- [x] Создание инцидента агентом отображается в ленте как цепочка INSERT incidents → incident_signals → incident_status_history → notifications.
- [x] Таблица вне allow-list → 403.
- [ ] `make lint && make test` зелёные; Definition of Done из AGENTS.md §8 выполнен.

## Как проверить
```bash
pytest backend/tests/integration/test_engine_db_api.py
```

## Отчёт субагента
Ветка `codex/T-108-db-activity` от `3c1c12c`. Контрактные/schema-test коммиты `84d3950`, `755cce5`, `2c9a1b0`: OpenAPI 1.5.14, nullable audit run_id, миграция 0011, generated ORM/TS, nullable last_change_at и строгий migration-head regression 0011. Обязателен human review [contract-change](../reviews/T-108-db-activity-scope.md); сохранить T-067 / PR #152 (1.5.12) и T-091 (1.5.13) при интеграции. До review merge запрещён.

Добавлена вкладка `/engine?tab=db`: счётчики/дельты таблиц, фильтры table/run, лента реальных audit INSERT/UPDATE/DELETE, cursor для старых событий, последние 50 строк и JSON-inspector. Обновление по существующему WebSocket topic db с throttling 250 мс, polling fallback 5 с и reconnect invalidation; pause удерживает снимок, refresh работает вручную. UI ru/en и light/dark, мобильный экран не выходит за viewport. Исходные шаги/граф/другие вкладки Engine сохранены.

API читает в repeatable-read/read-only transaction с statement timeout. Allow-list дополнен incident_signals для обязательной цепочки. Имя вне allow-list возвращает 403, arbitrary SQL не принимается. current — baseline + current; numeric — baseline + выбранный; all выбирается явно. Без current pointer область не становится all. agent_steps.run_id разрешается через agent_runs.sim_run_id, incident history/links — через incident.run_id. Малые и scoped таблицы считаются точно, большие all-таблицы используют pg_stat_user_tables с явной пометкой exact=false.

Аудит новых изменений содержит реальный снимок simulation run_id и только имена изменённых полей, без значений контактов/секретов. Старые неизвестные run_id не выдумываются и видны только в all. Snapshot run_id основной строки сохраняется после DELETE; при каскаде дочернего объекта после удаления родителя связь может быть неизвестной (null/all). Старые audit summaries проецируются безопасно при чтении, история не переписывается. JSON-inspector рекурсивно маскирует контакты, ключи/token/password и raw LLM payload; свободный текст проходит существующий privacy mask.

По согласованию с координатором в create_incident перенесена первая запись _history после incident_signals в той же транзакции. Теперь настоящий порядок audit INSERT — incidents → incident_signals → incident_status_history → notifications. Права refund/HITL и бизнес-решения не менялись; UI показывает фактический порядок, новые сверху.

Проверено: PostgreSQL target (agent chain, DELETE, run scope, masking, allow-list, exact counts, cursor, миграция repeat/downgrade/upgrade, NOTIFY→db routing, baseline prepare/restore); 8 security/legacy/estimate unit cases; 8 UI unit cases; 4 production-bundle Playwright ru/en×light/dark, включая фильтры/JSON, реальную frontend WS subscription и обновление счётчика/+1 за timeout ≤1000 мс, mobile overflow ≤2 px. UI fixtures синтетические и проверяют представление; фактические agent writes отдельно проверяются в PostgreSQL с mock LLM. Screenshot-комплект: `docs/screenshots/db-activity/db-{top,inspect}-{ru,en}-{light,dark}.png`, просмотрен вручную.

Финальный `make lint` зелёный (152 frontend tests, Ruff, mypy 242 modules, OpenAPI drift 191/191); обе сборки и i18n check (1512 keys) зелёные. Diff statement coverage нового backend-кода — 100 % (65/65: engine 64/64, перенос tool call 1/1); общий engine.py 53,30 %, tools/write.py 77,23 % — прежние ветки вне целевой проверки. 20 целевых schema/audit/security/NOTIFY/rollback tests прошли. Полный `make test` завершился с exit 0: 1060 backend passed / 22 skipped (unit 774/18, integration 213/2, scenarios 42/2, compliance 31/0); frontend 152 passed. В baseline/schema tests строго обновлён expected head 0011 и добавлена новая миграция в общий SQL idempotence list; assertions не ослаблены. Финальный diff/whitespace проверен, `check_owners --base 3c1c12c --card 108 --allow-cross` выполнен для разрешённого cross-layer scope. Свой localhost preview остановлен.

Интеграция: normal merge утверждённого T-091/T-067 (`3367687`), без cherry-pick/rebase. OpenAPI сохранён 1.5.14; Client360 RunId, text 3..5000, общий 20 RPM/429 и обе группы WS invalidation объединены. ORM/DB schema 0011 не менялись. После merge: 48 targeted backend passed (включая все 20 T-108 schema/audit checks, Client360, jury и gen_tasks); полный lint — 161 frontend passed, Ruff/mypy 243 modules, drift 191/191; обе сборки и contracts check зелёные. Повторная TS generation без diff; полный gen_tasks на копии 205 карточек — без изменений на первом и повторном прогоне; i18n 1614 keys. Совместный production Playwright — 13 passed / 0 retries (T-108 + Client360). Прежний полный make test выше относится к implementation commit до merge; после merge выполнен согласованный affected-scope regression.

Статус in_progress: human review контракта и live GigaChat из общего DoD не выполнены. Реальные LLM/почта/Telegram не использовались. Нет новых зависимостей, auth, SQL write UI или внешних каналов. PR/push/merge выполняет координатор.
