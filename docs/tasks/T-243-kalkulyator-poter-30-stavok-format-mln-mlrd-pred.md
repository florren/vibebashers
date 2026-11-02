# T-243 — Калькулятор потерь: 30 ставок, формат млн/млрд ₽, предзаполнение ставки направления, интеграция с картой региона

| Поле | Значение |
|---|---|
| Эпик | E19 Кабинет менеджера продукта и продуктовый разрез [ЕТЗ] |
| Субагент | `SA-UI-Analytics` (экраны кабинета, CSI, слой ВСП [ЕТЗ]) |
| Оценка | S (≤ 0,5 дня) |
| Волна | 9 |
| Слой | `L4` Фронт (владелец — см. docs/TEAM-SPLIT.md и CODEOWNERS) |
| В демо-минимуме | нет — можно отложить |
| Статус | `in_progress` |

## Цель
ЕТЗ FR-7.1–7.7 и 6.4 (ТЗ 24.6) поверх калькулятора T-133: без изменения формулы и коэффициентов.

## Разделы ТЗ (docs/TZ.md)
§24.6, §14.4, §14.5

## Контракты
- frontend/src/pages/economics/
- `api/openapi.yaml: GET /api/refs/dcltv_rates`

## Зависимости
- Зависит от: [T-133](T-133-ekran-kalkulyator-poter-dopuscheniya-v-stile-biz.md), [T-242](T-242-ekran-kabinet-menedzhera-produkta-cabinet-kpi-ka.md)
- Блокирует: —

## Что сделать
1. Форматтер результата «−1,23 млн ₽ / −456 789 ₽ / −1,23 млрд ₽» (локаль ru/en) с юнит-тестами границ.
2. Предзаполнение ставки направления менеджера и выбор из 30 ставок; показ «по средней ставке по банку», если ставки нет.
3. Интеграция с картой: щелчок по красному региону → «Рассчитать потерю»; подстановка числа пострадавших (различные клиенты сигналов региона и направления); расчётная потеря на карточке региона.
4. vitest: расчёт совпадает с `incident_economics` на фикстуре; e2e сценария 14.

## Критерии приёмки
- [ ] Формула и коэффициенты не изменены; результат совпадает с серверным расчётом на фикстуре.
- [ ] Форматы суммы корректны для ±, тысяч, млн, млрд.
- [ ] Подстановка из региона работает.
- [ ] `make lint && make test` зелёные; Definition of Done из AGENTS.md §8 выполнен.

## Как проверить
```bash
cd frontend && npx vitest run src/pages/economics
cd frontend && npx playwright test e2e/calculator-map.spec.ts
```

## Отчёт субагента
Ветка `codex/T-243-server-calculator` от T241f15, API1.5.24/безDDL.
Existing read-only preview optionalrate_code→actualcatalog→единственный
dcltv.compute; old absent behavior сохраняется, ambiguousproduct/system422.
Подтверждённый actualcatalog31 (exactcanonicalCSV↔DB), новых ставок нет.
14unit/actualPG green, saved incident fixture совпадает, GET fingerprints
unchanged/BombLLM0/writeproducer0; new executable7/7coverage100%.
Shared formatter15/queryhook3tests green; fullfront372/builds/type/lint green.
Подробный monetary diff/review boundary: docs/reviews/T-243-server-calculator.md.
До normalT242composition и actualcalculator/map/screens/CI/humanreview
карточка остаётся in_progress; localarithT242 не принимается окончательно.
