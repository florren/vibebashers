# T-244: cold-план сохранённых версий правил

## Подтверждённое падение

Main CI41793839760, backend shard3 job126453171465: один failure,
`test_cold_report_preserves_links_without_repeated_scans`. p95=371.295ms
при неизменённом300ms limit, min356.245ms, response1799610bytes. Остальные835tests
этого shard прошли. Показанные26.314ms SQL относились только к ленте сигналов;
план чтения версий правил исходный тест не проверял.

## Причина и исправление

Отдельная PG16/demo5000, статистика signals отсутствует (autovacuum выключен
только в существующей scratch fixture): rules сначала соединял400incidents
со всеми2813signals того же run, создавая1125200промежуточных строк до проверки
incident_signals. Полная коллекция pytest воспроизвела этот объём работы.
EXPLAIN facts query:258.874ms; median сериализации JSON:10.4ms. Retry, прогрев,
ANALYZE, изменение GC/planner settings или увеличение gate не применяются.

`selected_edges AS MATERIALIZED` сохраняет настоящий incident/signal/run triple
до чтения rules. Предикаты выбранных evaluations сохранены: выбранные инциденты,
тот же run, период/product line сигнала, прежний view/proactive filter и run
сохранённой evaluation. Текущая версия правила не подменяет сохранённую.
Wire fields, money_exact, privacy, scope, limits, DDL, LLM routing и денежные
формулы не меняются.

## Регрессии и измерения

- Новый native work-bound test RED на старом source и GREEN на исправлении.
  Проверяет actual rows×loops каждого EXPLAIN node, без требования конкретного
  join type; ANALYZE/statistics не подменяются, fingerprint всех public tables
  во время GET сохраняется.
- Прежний cold HTTP test не изменён:30samples, первый GET включён. Новый
  p95=117.612ms,1799610bytes; facts EXPLAIN4.307ms; max node work2813
  вместо1125200, work budget10000.
- Native сохранённая version901 / foreign-run902 проверены для current/all.
- Полный целевой набор отчёта/API/lifecycle/cold:72PGpassed/237.19s; включает
  JSON/XLSX/exact-money/scope/privacy/read-only. Unit text/scope56passed.
  Strict mypy329sourcefiles и backend Ruff прошли.

Диагностические timers/GC callbacks отделены от native timing. Полный CI
обязателен до merge; прежний зелёный CI PR218 не отменяет позднее падение main.
Локальные логи и планы synthetic fixtures — в `.runtime/`; CI сохраняет
`test-results/cabinet-report-rules-cold.json`. Секреты/рабочие данные в diff
не включены.

## Откат

При необходимости — отдельный app revert PR. Миграций, изменений configuration,
записи данных и внешних вызовов нет.
