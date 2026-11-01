# T-040 — Сервис запусков эмуляции: sim_runs, run_id, режимы сброса, снимок baseline

| Поле | Значение |
|---|---|
| Эпик | E3 Симулятор банка, команды, SLA |
| Субагент | `SA-Teams` (симулятор, команды, SLA) |
| Оценка | L (3–4 дня) |
| Волна | 2 |
| Слой | `L2` Симулятор и данные (владелец — см. docs/TEAM-SPLIT.md и CODEOWNERS) |
| В демо-минимуме | да |
| Статус | `in_progress` |

## Цель
Каждый запуск эмуляции сохраняется с итогами; повторные запуски не загрязняют друг друга (ТЗ 4.6, решение заказчика 20.4).

## Разделы ТЗ (docs/TZ.md)
§4.6, §13, §16.2, §19 п. 16

## Контракты
- `db/schema.sql: sim_runs, sim_state.current_run_id, run_id во всех таблицах данных, v_run_counters`
- `api/openapi.yaml: sim/runs*, sim/baseline*, sim/control (start/stop)`
- `events/envelope.schema.json (run_id)`
- `events/ws/message.schema.json (topic runs)`

## Зависимости
- Зависит от: [T-005](T-005-primenenie-schema-sql-sqlalchemy-modeli-sessii.md), [T-031](T-031-simclock-sim-state-i-upravlenie-simulyaciej.md), [T-032](T-032-shina-sobytij-simulyatora.md)
- Блокирует: [T-020](T-020-predystoriya-signalov-incidentov-statusov-artefa.md), [T-038](T-038-dvizhok-scenariev-yaml-i-7-demo-scenariev.md), [T-041](T-041-preryvanie-i-vozobnovlenie-emulyacii-vosstanovle.md), [T-042](T-042-itogovye-metriki-zapuska-summary-i-eksport.md), [T-086](T-086-layout-rabochego-mesta-cx-shapka-sim-chasy-panel.md), [T-094](T-094-vkladka-zapuski-istoriya-sravnenie-sbros-k-basel.md), [T-132](T-132-api-svodnoj-ekonomiki-i-metrik-dashborda.md), [T-146](T-146-testy-izolyacii-zapuskov-i-vozobnovleniya.md), [T-171](T-171-mock-abs-scheta-tarify-provodki-sid-i-invariant.md), [T-180](T-180-rasshirenie-zapuskov-avtosozdanie-run-kind-live.md), [T-195](T-195-menyu-demonstratora-skrytaya-knopka-statusy-prov.md), [T-270](T-270-bezopasnyj-povtornyj-seed-i-pg-dump-v-docker.md), [T-275](T-275-avtomaticheskij-csi-remont-posle-baseline-restor.md)

## Что сделать
1. app/sim/runs.py — RunService: create(kind, scenario_id, label, seed, reset_mode, llm_profile_id) → sim_runs + sim_state.current_run_id; stop() → finished_sim, summary (DashboardMetrics + EconomicsSummary + токены по профилям), статус stopped; complete() для сценариев; archive() → экспорт runs/<id>.json и удаление строк данных (CASCADE по run_id); delete() с запретом для baseline и текущего.
2. Контекст запуска: contextvar current_run_id, который читают все генераторы, инструменты агента и репозитории при INSERT; средство проверки — тест «нет строк без run_id» после сценария.
3. Режимы сброса: none (409 при незавершённом запуске), counters (принудительный stop текущего + новый run), baseline (BaselineService.restore → новый run).
4. app/sim/baseline.py — BaselineService: dump() после сида (`pg_dump -Fc` в data/baseline/<profile>.dump + .sha256 + meta.json с сидом/профилем/baseline_run_id); restore() в режиме обслуживания: пауза симулятора, закрытие сессий, сохранение таблицы sim_runs и каталога runs/, `pg_restore --clean --if-exists`, возврат sim_runs (без данных незавершённых запусков), сброс sim_state на baseline; прогресс по WS topic runs (baseline_restore_started/finished).
5. API из openapi.yaml: GET/POST /api/sim/runs, current, {id}, stop, resume (делегирует T-041), archive, export (json/csv), compare, baseline GET/POST, baseline/restore; публикация runs.started|stopped в WS и NOTIFY 'sim_runs'.
6. scripts/run.sh stop|resume|status|reset-baseline — обёртка над API для консоли.
7. Параметр run_id (current|all|id) как общая зависимость FastAPI для лент/карточек/метрик: ленты и карточки по умолчанию baseline + current, метрики — только current.

## Критерии приёмки
- [ ] После сида существует запуск kind=baseline, предыстория помечена его run_id; снимок baseline создан, GET /api/sim/baseline показывает размер и sha256.
- [ ] POST /api/sim/runs с counters: новый run_id, v_run_counters нового запуска нулевые, предыдущий stopped с заполненным summary.
- [ ] POST /api/sim/runs с baseline на профиле demo: восстановление ≤ 60 с, данные прошлых запусков удалены, их summary и экспорт сохранены, таблица sim_runs цела.
- [ ] Два запуска baseline с одним сидом на mock дают идентичные sim_events и summary (тест детерминизма расширен).
- [ ] compare возвращает diff по метрикам 14.1/14.4 и токенам.
- [ ] `make lint && make test` зелёные; Definition of Done из AGENTS.md §8 выполнен.

## Как проверить
```bash
pytest backend/tests/integration/test_runs.py backend/tests/integration/test_baseline_restore.py
curl -s localhost:8000/api/sim/runs/current | jq .counters
```

## Отчёт субагента
Ветка main, коммит B03 (минимум). `app/sim/runs.py`: current_run_id, create_run (kind free, reset_mode counters: незавершённый текущий → stopped, parent_run_id, NOTIFY runs started), set_run_status (paused/running/interrupted/stopped c summary из v_run_counters), get_run (+ counters), list_runs. Все вставки симулятора идут с run_id текущего запуска (тест «нет строк без run_id»). Не сделано (остаётся по карточке): сценарные запуски, archive/export/delete, scripts/run.sh, общая зависимость run_id для лент. Время: ~25 мин.

Дополнение feat/T-040-baseline-restore: `app/sim/baseline.py` (pg_dump -Fc, meta, sha256, pg_restore с возвратом sim_runs), GET/POST `/api/sim/baseline`, POST `/restore`, POST `/api/sim/runs` с `reset_mode=baseline`. Сравнение запусков не менялось. В CI без postgresql-client интеграционный restore пропускается; unit мокает subprocess. Образ backend по-прежнему без pg_dump — честный 409, если бинаря нет.

Ревизия 02.11.2026: прежний `done` не подтверждён критериями. Сценарный POST, archive/delete, CLI и параметры запуска остаются неполными; summary/export реализованы отдельно в T-042 (PR #160). Карточка возвращена в работу; утверждения старого отчёта сохранены как история.

Локальный checkpoint T-040 (не merge-ready): добавлены typed POST202/SimRun, seed/profile metadata/settings snapshot, atomic reset none409/counters; history filters/cursor/counters; существующий scenario pipeline/baseline reset; YAML reset policy для1/4/7, internal DemoExecution явно применяет baseline. Stop/resume возвращают SimRun. run_lifecycle реализует archive/delete: FK ownership/cascade closure, short table locks/5s timeout, запрет baseline/current/unfinished/inflight agent, отказ при межзапусковых ссылках, один CTE для циклов, JSON fsync/exclusive link, проверка saved JSON/header/summary, rollback. Delete сохраняет готовый архив и обнуляет parent FK у сохранённых потомков. Audit log без FK остаётся. До pg_restore экспортируются summary/агрегаты прошлых run; archived status применяется к сохранённым заголовкам после успешного restore. scripts/run.sh реализован.

Проверено по мере реализации:7новых PG lifecycle passed; расширенный старый набор21PG (lifecycle+summary+live+sim) passed; затем11новых/restorePG passed, включая настоящий pg_restore с сохранением прошлогоrun/export. Последние YAML policy/list/return-body/fsync additions требуют следующего regression.25baseline unit passed, Ruff/mypy6green; bash-n/help green. Все DSN для последних PG+HTTP прогонов явно направлены на cx_run_lifecycle_revision:55439. Один предыдущий read-only API export test ошибочно использовал default DSN при заданном только DATABASE_URL_TEST; после задания обоих DSN исходныеasserts прошли. Рабочие данные не менялись.

Остаётся: actual per-run LLM profile в process/resume/followups (одной metadata недостаточно), контракт1.5.15 Scenario.reset_mode_required/live enum и review, строгий stopped-resume guard относится также T041, полный final make lint/test/coverage/performance, baseline/run maintenance concurrency и UI T094. Финансовые записи могут удаляться только явным archive/delete/reset после human review конкретного PR; сейчас все data changes — только scratch tests. Карточка in_progress.

Checkpoint per-run profiles: snapshot main/fast/twin и локальные bindings подключены к graph/load_deps/process, twins, demo employees/teams/recovery. Снимок включает модели/ID/тарифы, не secrets. Runtime mock/replay исключает live chain для всех ролей; legacy без snapshot сохраняет явную конфигурацию без заявления об исторической точности. Summary показывает frozen tariff estimate, recorded cost неизменна; compare/bench сохраняют собственный выбор. bench_only/inactive/missing отклоняются до старта; credentials в extra/URL и неконечные/отрицательные тарифы запрещены.44unit и12PG profiles/summary/jury passed; дополнительный profile+bench_only PG набор3passed11.42s. Полный regression и maintenance ещё не завершены; финансовые/контрактные изменения не готовы к merge.
