# T-244 — Отчёт по направлению «для человека»: GET /api/cabinet/report (json|xlsx), выводы на русском без LLM, печатная форма A4 для PDF

| Поле | Значение |
|---|---|
| Эпик | E19 Кабинет менеджера продукта и продуктовый разрез [ЕТЗ] |
| Субагент | `SA-Analytics` (API кабинета, CSI и ВСП, индекс CX [ЕТЗ]) |
| Оценка | M (1–2 дня) |
| Волна | 9 |
| Слой | `L3` Агент и контуры (владелец — см. docs/TEAM-SPLIT.md и CODEOWNERS) |
| В демо-минимуме | нет — можно отложить |
| Статус | `todo` |

## Цель
Кнопка «Сформировать отчёт» (ЕТЗ FR-6.8, ТЗ 24.5, 20.7 № 69): документ, который руководитель читает без пояснений — выводы словами, числа с единицами, графики с заголовками-выводами.

## Разделы ТЗ (docs/TZ.md)
§24.5, §14.4, §16.3

## Контракты
- `api/openapi.yaml: GET /api/cabinet/report?format=json|xlsx`
- `backend/app/analytics/report_text.py`
- frontend/src/pages/cabinet/ReportPage.tsx
- docs/LICENSES.md (openpyxl, MIT)

## Зависимости
- Зависит от: [T-241](T-241-api-kabineta-menedzhera-api-cabinet-overview-sig.md)
- Блокирует: —

## Что сделать
1. `report_text.py`: детерминированные шаблоны (ru/en, без LLM) для блока «Главное за период» (`summary_ru[]`, 3–5 предложений: что произошло, что изменилось, главная тема, предотвращено потерь, что требует внимания), подписей KPI («в норме / растёт / требует внимания») и заголовков-выводов графиков (`insight_ru` на график); юнит-тесты на формулировки и граничные случаи (нет данных, нулевой период).
2. `GET /api/cabinet/report?product_line=&period=&run_id=&format=json|xlsx`: один источник данных для обеих форм; JSON = overview + `summary_ru`, `kpi[] {label, value, unit, delta, verdict}`, `charts[] {title_insight, note}`, `top_problems[]` (словами + код в скобках), `attention[]`, `method {formula_ru, rules_version, app_version, run_public_id}`.
3. XLSX на `openpyxl`: листы «Главное», «KPI», «Сигналы», «Динамика», «Источники», «Регионы», «Методика»; подпись «синтетические данные»; без ПДн; размер ≤ 5 МБ.
4. Печатная форма `/cabinet/:productLine/report` (страница `ReportPage.tsx`): одна колонка A4, порядок блоков по ТЗ 24.5 (Главное → KPI → графики с выводами → Топ-5 проблем → Что требует внимания → Методика и термины), ECharts `renderer: 'svg'`, читаемость в ч/б (маркеры и штриховка), `@media print` скрывает навигацию и анимации, разрывы страниц между блоками, колонтитул с номером страницы и датой; кнопка «Сохранить PDF» → `window.print()`. Серверный PDF не добавляется.
5. Проверка понятности: e2e-смоук печатной формы (Playwright `page.pdf()` в headless Chromium как артефакт CI, визуальная проверка человеком по чек-листу 24.5 п. 1–7); тексты через i18n.

## Критерии приёмки
- [ ] JSON и XLSX согласованы с `overview` и между собой; `summary_ru` не пустой при наличии данных и корректен при их отсутствии.
- [ ] Печатная форма помещается на 2–3 страницы A4 без обрезки; первый блок — выводы словами; у каждого графика заголовок-вывод; внутренние коды только в скобках после расшифровки.
- [ ] Лицензия `openpyxl` указана; LLM не вызывается (тест: провайдер mock не получает запросов).
- [ ] `make lint && make test` зелёные; Definition of Done из AGENTS.md §8 выполнен.

## Как проверить
```bash
pytest backend/tests/integration/test_cabinet_report.py backend/tests/unit/test_report_text.py
curl -s -o /tmp/r.xlsx 'localhost:8000/api/cabinet/report?product_line=deposits&format=xlsx' && file /tmp/r.xlsx
cd frontend && npx playwright test e2e/cabinet-report.spec.ts
```

## Отчёт субагента
_Заполняется исполнителем: ветка/PR, что сделано, отклонения от карточки, затронутые контракты, скриншоты/логи, время._
