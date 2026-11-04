# T-166 — Вкладка калькулятора «Факт по симуляции»: API, UI, экспорт

| Поле | Значение |
|---|---|
| Эпик | E14 Поведение клиентов и калькулятор «Факт» |
| Субагент | `SA-Economics` (экономика и калькулятор) |
| Оценка | L (3–4 дня) |
| Волна | 4 |
| Слой | `L2` Симулятор и данные (владелец — см. docs/TEAM-SPLIT.md и CODEOWNERS) |
| В демо-минимуме | нет — можно отложить |
| Статус | `todo` |

## Цель
Фактические сбои по продуктам/дням/часам, исходы инцидентов, ушедшие клиенты, допущения vs факт, экспорт.

## Разделы ТЗ (docs/TZ.md)
§14.5

## Контракты
- `api/openapi.yaml: metrics/economics/fact, fact/export, calibrate`
- `db/schema.sql: v_faults_by_product_hour, v_incident_outcomes, churn_events`

## Зависимости
- Зависит от: [T-165](T-165-kalibrovka-koefficientov-uderzhaniya-po-faktam-s.md), [T-164](T-164-uhod-klienta-churn-events-incident-account-closu.md), [T-133](T-133-ekran-kalkulyator-poter-dopuscheniya-v-stile-biz.md)
- Блокирует: —

## Что сделать
1. API fact по контракту (через представления), фильтры продукт/система/регион; экспорт CSV/XLSX (openpyxl).
2. UI: тепловая матрица 14 дней × 24 часа (ECharts heatmap) с фильтрами; таблица исходов с суммами; таблица ушедших с переходом на инцидент account_closure; блок «допущения vs факт» с кнопкой «Подставить факт в калькулятор»; экспорт.

## Критерии приёмки
- [ ] Вкладка «Факт» считается в рамках выбранного запуска (run_id), по умолчанию текущего; есть режим all для сравнения с предысторией.
- [ ] Данные вкладки сходятся с дашбордом и карточками (тест консистентности).
- [ ] Экспорт открывается в Excel/LibreOffice с корректной кодировкой.
- [ ] `make lint && make test` зелёные; Definition of Done из AGENTS.md §8 выполнен.

## Как проверить
```bash
npx playwright test e2e/economics_fact.spec.ts
pytest backend/tests/integration/test_economics_fact_api.py
```

## Отчёт субагента
_Заполняется исполнителем: ветка/PR, что сделано, отклонения от карточки, затронутые контракты, скриншоты/логи, время._


### Freeze follow-up: read-only Fact и согласованный run scope

Ветка `codex/freeze-dashboard-scope`, основа main `52fd498`. Исправлен доступный
legacy Dashboard: Fact/CSV и экономика передают один scope, all не подставляется
в текущую калибровку, при отсутствующем current запросы не подменяются all.
Fact GET больше не запускает recompute; JSON/экспорт читают один repeatable-read
read-only snapshot. Исправлены run/hour/product связи матрицы и all retention
по уникальным (run,client), unknown оценки не становятся нулём, configured0 сохранён.
Настоящий XLSX использует уже установленный openpyxl.

API1.5.32: документированы run_id,404/422, неподдерживаемые целостно фильтры
отклоняются422; nullable outcome money и economics_known явно обозначают coverage.
DTO detractor_share.fact уже nullable; state detractor в client_states не существует,
поэтому отображается unknown до отдельного mapping. Формулы/ставки/POST calibrate,
выплаты и HITL сохранены. Контракт/денежная граница требуют review человека.
Review и совместимость: [freeze-dashboard-fact](../reviews/freeze-dashboard-fact.md).
Полная T166, heatmap/фильтры, T162/T164 и эмпирические исходы этим пакетом не закрыты.

Отдельный financial bugfix producer: configured0 долей не заменяется default0.1/0.5;
это меняет суммы при этих входах по существующей формуле и требует явного review.
RED3/4controls зафиксирован; primary/history не пересчитывались. Stale/future
и unknown own-clock оценки в Fact остаются unknown, а не свежими деньгами.

Итоговые локальные gates:2310unit/19skip;composition68(41unit+19новыхPG+8прежнихPG),
597frontend/83files,16actualChromecomponentcases(ru/en×themes),bothbuilds,
Ruff/format/mypy329/contracts48/167/drift197/197green. Изменённые producer
statements62/62executed,неbranch/fullprojectcoverage. FinalintegratedCI и
humancontract/financialreview обязательны; новаяprimaryсхема/данные не применялись.
