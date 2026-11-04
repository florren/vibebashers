# T-244 — Отчёт по направлению «для человека»: GET /api/cabinet/report (json|xlsx), выводы на русском без LLM, печатная форма A4 для PDF

| Поле | Значение |
|---|---|
| Эпик | E19 Кабинет менеджера продукта и продуктовый разрез [ЕТЗ] |
| Субагент | `SA-Analytics` (API кабинета, CSI и ВСП, индекс CX [ЕТЗ]) |
| Оценка | M (1–2 дня) |
| Волна | 9 |
| Слой | `L3` Агент и контуры (владелец — см. docs/TEAM-SPLIT.md и CODEOWNERS) |
| В демо-минимуме | нет — можно отложить |
| Статус | `in_progress` |

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
- [x] JSON и XLSX согласованы с `overview` и между собой; `summary_ru` не пустой при наличии данных и корректен при их отсутствии.
- [x] Печатная форма помещается на 2–3 страницы A4 без обрезки; первый блок — выводы словами; у каждого графика заголовок-вывод; внутренние коды только в скобках после расшифровки.
- [x] Лицензия `openpyxl` указана; LLM не вызывается (тест: провайдер mock не получает запросов).
- [ ] `make lint && make test` зелёные; Definition of Done из AGENTS.md §8 выполнен.

## Как проверить
```bash
pytest backend/tests/integration/test_cabinet_report.py backend/tests/unit/test_report_text.py
curl -s -o /tmp/r.xlsx 'localhost:8000/api/cabinet/report?product_line=deposits&format=xlsx' && file /tmp/r.xlsx
cd frontend && npx playwright test e2e/cabinet-report.spec.ts
```

## Отчёт субагента
Ветка `codex/T-244-cabinet-report`, база T-242 `5b34a5f`. Реализованы общий read-only JSON/XLSX producer, API 1.5.26 и трёхстраничная A4 форма с exact money values/deltas. [Контракт, лимиты и rollback](../reviews/T-244-report-contract-review.md).

Runtime `3898630`: 125 native unit/PG passed; production browser 5/5, 8 actual HTTP exports, large-money 2/2. Сохранены 24 PNG/PDF/XLSX artifacts, включая шесть PDF по 3 страницы. Fingerprint всех 107 таблиц unchanged во время чтения; LLM/external/non-GET attempts — 0. Cold stale-stats p95=272.497 мс; отдельный benchmark общего отчёта/направления — p95=242.665/32.591 мс, первые GET включены. Исторические failures явно сохранены в review.

Report coverage 205/209 (файлы byte-identical final), shared SQL helper 31/31. Lint: 416 frontend tests, Ruff 452 files, mypy 294 files, drift 193 methods. Обе production builds, contracts и generator idempotence зелёные. Исторический полный `make lint test` на `3f42ae8` отделён от final scoped proof. Approval/merge status ведётся в PR196; exact-head CI ещё требуется; T-249/T-262 не закрываются.

CI follow-up PR196: runtime `734c8a7` устраняет allocation overhead без изменения wire/API26/money semantics; strict403 fixture задана явно. Native affected125 passed, production browser5/5, full lint421frontend, helper coverage32/32; исходные CI380.888ms иsoft200 сохранены. [Source-qualified red→green proof](../reviews/T-244-ci-regressions.md). Карточка остаётсяin_progress до exact-head CI/merge.


### Регрессия empty report в nightly — 03.11.2026

В общем freeze QA PR #212 исправлен неправильный assertion «Нет»/«No» для daily без сохранённой экономики: теперь точное равенство правильному ru/en i18n key, включая отдельный noSavedEconomics. Предыдущий nightly41611773482 воспроизвёл2ru failures; продуктовый copy/денежные формулы не меняются. Проверки SVG/экспорта/scope/A4/read-only сохранены. Полный повтор demo/performance проверяется отдельно; evidence в docs/reviews/channel-chronology.md.

### Main CI cold rules query — 04.11.2026

CI41793839760: p95=371.295ms при300ms gate. Отдельный actual PG plan выявил
1125200intermediate rows в rules-version subquery (400incidents×2813signals);
показанные тестом26.314ms относились только к ленте сигналов. Материализованные
selected_edges сохраняют incident/signal/run triple до join planning. SQL rules
plan258.874→4.307ms; max node work1125200→2813; native30GET p95=117.612ms.
Исходный300ms gate/данные/первые GET/absence of stats сохранены. Новая work-bound
регрессия RED на исходном SQL → GREEN на исправлении; добавлена positive saved901
versus foreign-run902 проверка current/all. Native72PG и56unit passed; mypy329
прошёл. Контракты/деньги/DDL/LLM/UI не меняются. Полный CI обязателен до merge;
подробности/откат: [cold rule edges review](../reviews/T-244-cold-rule-edges.md).
