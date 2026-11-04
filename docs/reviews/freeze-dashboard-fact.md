# T-166: согласованный scope и честное чтение Fact перед фризом

Основа: main `52fd498ffe20c0a248e987b37fa3d1b6be796caf`.
Ветка: `codex/freeze-dashboard-scope`. Предлагается отдельный review API1.5.32
и границы чтения денежных оценок по AGENTS §5.1/§7; до одобрения и зелёного
общего CI runtime не обновляется. DDL нет.

## Проблема и исправление

Доступный legacy Dashboard при выборе «Все запуски» показывал текущий Fact,
а CSV не передавал scope. Во время смены scope сохранялись старые placeholder
метрики. Fact GET запускал денежный recompute; export xlsx выдавал CSV. В матрице
сигналы совпадающей системы/дня считались также из других runs, часов и продуктов.
All retention выбирал последнюю строку run вместо общей проверенной выборки.

- Dashboard передаёт один scope в dashboard/economics/Fact/CSV; query keys содержат
  scope и не показывают предыдущие данные во время переключения. GET dashboard/economics
  используют тот же строгий resolver, в том числе для родительского KpiStrip. Пока current
  неизвестен, эти запросы не отправляются. «Все» остаётся явным выбором.
- Apply выключен для all/отсутствующего current с объяснением ru/en. Прежний
  current POST `{mode}` не изменён; это глобальная настройка, не перенос истории.
- JSON Fact и экспорт читают один repeatable-read read-only snapshot, без
  `dcltv.recompute`/LLM. Существующий read_db ограничивает SQL statement 3 секундами.
- `current` без pointer даёт пустой scope, не all. Положительный numeric id обязан
  существовать (404), неверный scope даёт422. Обрабатываются только current/all/id.
  У dashboard явный run_id приоритетнее window, даже window=all. Без run_id
  window=all сохраняет прежнее all. Missing current возвращает пустой DashboardMetrics{};
  economics читает пустой scope без recompute. Валидный legacy dashboard/economics
  сохраняет прежний refresh и не объявляется read-only.
- Матрица коррелирует signal/fault по одному run, часу, системе и продукту.
  Сохранённая экономика принимается только от того же run, что и incident,
  при `computed_at>=incident.updated_at`, `computed_sim>=incident.created_sim`
  и не позже собственного run clock. Как и существующий native producer,
  own clock — sim_state.sim_time для current, finished_sim для остальных.
  Unknown own clock/stale/future estimate дают unknown; нового wall-clock TTL нет.
- Retention сохраняет отношение retained/resolved из прежнего представления,
  но считает distinct `(run,client)` в выбранном наборе, а не последнюю строку.
  Один клиент в разных запусках — разные наблюдения; это модельная статистика,
  не доказанная причинность удержания.
- Configured0 сохраняется0. Доля детракторов — unknown/null: состояния
  `detractor` в client_states нет, нового mapping этот пакет не придумывает.
- XLSX — настоящий openpyxl workbook с числовыми ячейками; текстовые ячейки
  принудительно text, без формул. CSV сохраняет прежние столбцы, разделитель и BOM.

## Совместимость API1.5.32

В путях Fact и export документирован уже существовавший runtime `run_id`.
DTO Fact outcome теперь имеет `economics_known` (из `incidents`). Три суммы
nullable, когда хотя бы одному incident не хватает same-run saved estimate.
Подтверждённый нулевой расчёт остаётся0. Неполная сумма не заменяется известным
нулём или неполным итогом. CSV/XLSX unknown — пустая ячейка, JSON — null.
Consumer должен проверять null перед форматированием/арифметикой; для покрытия
использовать `economics_known/incidents`. Отсутствие incidents — пустой массив.

Фильтры product/system/region_code раньше применялись частично к разным секциям.
Теперь они явно дают422 до DB; это намеренное изменение поведения контракта,
а не молчаливое игнорирование. В существующем UI потребителей этих фильтров нет.
Клиенту старого API нужно убрать фильтры либо использовать отдельный согласованный
API кабинета; полноценные фильтры Fact остаются открытым объёмом T-166.
Пустой/нулевой/отрицательный/слишком большой/несуществующий run больше не может
раскрывать общую историю. Nullable detractor fact уже разрешён прежним DTO.

Существующие сохранённые проводки, incident_economics, run summaries и настройки
не переписываются. GET больше не создаёт свежую оценку: пока штатный producer её
не сохранил, Fact честно показывает unknown. Другие legacy GET экономики и
сам POST calibrate этим пакетом не переводятся на новую политику.

## Отдельная денежная граница: configured0 в producer

В `compute_incident` исправлены только два входных значения: явные0 для
`detractor_share`/`no_return_share` больше не заменяются default0.1/0.5 через `or`.
Отсутствующее/None значение сохраняет прежний fallback; ненулевые значения,
само `dcltv.compute`, округление, ставки, premium addon и другие коэффициенты
не изменены. Это **изменяет расчётные суммы при configured0**, а не только UI.

Численный пример: affected10, bank_average4050, detractor0, no_return0.5.
Раньше producer подставлял0.1 и сохранял potential2025₽; теперь применяет0
и сохраняет potential0₽ по прежней формуле. То же для no_return0.
При0.2×0.4 сумма остаётся3240₽, при None/default0.1×0.5 —2025₽.
Настройки и прежние оценки автоматически не переписываются; изменение проявляется
при следующем штатном явном пересчёте соответствующего инцидента. Старые оценки
могут сохраняться до него. Refund fee/ledger, выплаты и HITL не меняются.
Это отдельная часть financial review, а не утверждение «все суммы неизменны».

## Проверки

- Исходный RED:3failed/1passed — нежелательный recompute и два ложных XLSX.
- Final composition:68passed (41unit +19новых actual PG +8прежних map/metrics/run-summary). Baseline отдельно, current/all/id,
  missing current, чужой run/час/продукт, all retention1/4, unknown/partial/known0,
  configured0 и foreign economics guard. XLSX открыт настоящим openpyxl parser.
  Fingerprints всех public tables и sequences сохраняются на read-only запросах.
- Targeted frontend:6passed, ru/en; scope JSON/CSV, all/current, отсутствие старого
  Fact между запросами, all Apply disabled/no POST, no-current/no-metrics-HTTP.
- Полные frontend:597passed/83files.
- Producer RED3failed/4passed →GREEN7: оба отдельных configured0 и два нуля раньше
  подменялись defaults. Остальные None/nonzero controls прошли до исправления.
- Изменённые producer statements:62/62executed (100%):metrics55/55, Factreader5/5, dcltv2/2.
  Метод — stdlib line trace innermost executable AST statements, содержащих diff lines;
  это не branch/full-project coverage. [Source-qualified JSON](freeze-dashboard-coverage.json).
- Actual Chrome component proof:16/16 (ru/en×themes×current/all/noCurrent/error),
  actual Dashboard+CSS/mock API, без POST/primary/LLM. [Proof](freeze-dashboard-ui-proof.json),
  [ru light](../screenshots/dashboard-fact/ru-light-all.png), [ru dark](../screenshots/dashboard-fact/ru-dark-all.png),
  [en light](../screenshots/dashboard-fact/en-light-all.png), [en dark](../screenshots/dashboard-fact/en-dark-all.png).
  KpiStrip scope закрыт отдельным native API тестом; component proof не выдаётся за primary end-to-end.
- Ruff/format593files,mypy329, frontendESLint/motion/typecheck, обе production
  сборки (operator/personal), contracts48/167 и drift197/197 — passed.
- Полный backend unit на последнем producer/guard коде:2310passed/19skipped
  (69.68s). Skips — прежние schema examples, не отключённые регрессии.
  Общий integrated CI и human review обязательны. Полный T166 этим не закрыт.

Первые ошибки harness (URI без psycopg driver/PG18 в PATH и доступ к кнопке до
async render) сохранены отдельно; исправлены окружение/ожидание рендера, assertions
не ослаблялись. После freshness guard отдельный67passed/1failed выявил
fixture с computed09/faults09–10 при исходном seed clock06UTC. Исправлен только
собственный fixture as_of11, cleanup сохраняет старый clock; строгие assertions
и production guard неизменны. Fresh final68passed после этого сохранён отдельно.
Фактическая проверка использует собственную PG16, mock LLM и
локальные сокеты. Primary БД/Telegram/внешние провайдеры не использовались.

## Ограничения и откат

Полная heatmap/фильтры Fact, activity-drop detector, durable closure и эмпирическая
калибровка остаются отдельными задачами. Legacy KPI не превращается этим изменением
в новую модель экономики. Старые timestamp ошибки и исторические суммы не чинятся.

Откат — прежний backend/frontend image парой после остановки runtime. Миграций
и repair нет; данные совместимы. Откат возвращает старое поведение GET/recompute,
ошибочные scope, ложный XLSX и подстановку defaults вместо configured0. Старый consumer API1.5.31 нельзя считать совместимым
с nullable sums без обработки unknown; код и generated types обновляются вместе.
