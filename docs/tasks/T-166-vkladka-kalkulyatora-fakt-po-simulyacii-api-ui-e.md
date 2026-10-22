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
