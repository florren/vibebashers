# T-042 — Итоговые метрики запуска (summary) и экспорт

| Поле | Значение |
|---|---|
| Эпик | E3 Симулятор банка, команды, SLA |
| Субагент | `SA-Economics` (экономика и калькулятор) |
| Оценка | S (≤ 0,5 дня) |
| Волна | 3 |
| Слой | `L2` Симулятор и данные (владелец — см. docs/TEAM-SPLIT.md и CODEOWNERS) |
| В демо-минимуме | да |
| Статус | `review` |

## Цель
При завершении запуска фиксируется полный набор показателей 14.1/14.4/14.5 и расход токенов — основа истории и сравнения запусков.

## Разделы ТЗ (docs/TZ.md)
§4.6, §14.1, §14.4, §14.5

## Контракты
- `api/openapi.yaml: SimRun.summary, sim/runs/{id}/export, sim/runs/compare`
- `db/schema.sql: sim_runs.summary, v_run_counters, v_incident_outcomes, v_retention_by_outcome`

## Зависимости
- Зависит от: [T-040](T-040-servis-zapuskov-emulyacii-sim-runs-run-id-rezhim.md), [T-132](T-132-api-svodnoj-ekonomiki-i-metrik-dashborda.md)
- Блокирует: [T-094](T-094-vkladka-zapuski-istoriya-sravnenie-sbros-k-basel.md), [T-146](T-146-testy-izolyacii-zapuskov-i-vozobnovleniya.md)

## Что сделать
1. app/sim/run_summary.py: build_summary(run_id) собирает DashboardMetrics(window=run), EconomicsSummary, факт удержания по исходам/психотипам, токены и стоимость по llm_profiles, длительность реальную и сим, число HITL/подарков/уходов; схема summary версионирована (summary_version).
2. Экспорт JSON (summary + агрегаты по часам/продуктам/командам) и CSV событий; compare: разность по числовым ключам summary.
3. Пересчёт summary для прошлых запусков командой make run-summary ID=…

## Критерии приёмки
- [x] summary заполняется при stop/complete и совпадает с ответами metrics API по run_id (тест).
- [x] Экспорт JSON открывается и содержит все разделы; CSV ≥ 1 строка на событие.
- [ ] `make lint && make test` зелёные; Definition of Done из AGENTS.md §8 выполнен.

## Как проверить
```bash
pytest backend/tests/unit/test_run_summary.py
```

## Отчёт субагента
Ревизия01.11.2026, `codex/T-042-run-summary`. Общие dashboard/«Факт» проекции
извлечены в analytics/dashboard.py и используются API и итоговым снимком без
дублирования формул. Stop/complete атомарно фиксирует summary_version1; следующий
create_run также финализирует предыдущий, resume сбрасывает устаревший снимок.
Сохранены legacy counters, добавлены dashboard/economics/fact, профили и агрегаты
LLM tokens/cost, длительности и completed gifts. Отсутствующий тариф не бесплатный:
unknown_tariff_runs; missing/stale economics явно отмечаются. Формулы/ставки,
проводки/лимиты/HITL не меняются. dcltv.summary получил optional refresh=True
(прежнее поведение по умолчанию); экспорт использует refresh=False.

JSON export включает summary и часовые/продуктовые/командные агрегаты. CSV читает
все события named cursor по500, с bounded spool1MiB и защитой formula injection.
Export/compare работают в read-only repeatable-read; сравнение числовых ключей
вложенного summary (bool/ID/version исключены). Для старых запусков временная
проекция не записывается. `make run-summary ID=…` явно пересчитывает завершённый
запуск; archived/running отклоняются. Контрактные файлы не меняются.

Проверено21адресной регрессией (свои6+unit1 и управление симуляцией): snapshot
совпадает сmetrics, tokens/cost отдельно поkind/profile,1001CSV events безутечки
другогоrun, атомарностьrollback, read-onlySQL, JSON/CSV/compare API,dict/tuple
row_factory. В полном первом прогоне найден dict-row KeyError вcreate_run;
исправлен и подтверждён тремя отдельными regression в изолированном checkout/DB.
Проверка полного пакета: make test exit0 —734unit/18skip,214integration/4skip,
42scenario/2skip,31compliance,144frontend(1021backendpassed/24skip). Make lint
зелёный, обаfrontendbuild,contracts44/161/OpenAPIdrift191,ownersallow-cross,
i18n/diff-check проходят. После финального расширения hourly export с EventBus
на всю историю operations/signals/incidents повторены7DB/unit checks(24.22с),
проверены точные суммы часов и изоляцияrun. Покрытие изменённых строк218/241=90.46%.
Полный CI на итоговом дереве и liveGigaChat ожидаются; карточка не done.
