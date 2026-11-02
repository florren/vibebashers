# T-240 — Корпус product_lines_v1 и история: тексты по 15 направлениям, импорт отзывов с source_url, product_signal_history (12 мес.), справочник площадок

| Поле | Значение |
|---|---|
| Эпик | E19 Кабинет менеджера продукта и продуктовый разрез [ЕТЗ] |
| Субагент | `SA-Signals` (тексты и предыстория сигналов) |
| Оценка | M (1–2 дня) |
| Волна | 8 |
| Слой | `L2` Симулятор и данные (владелец — см. docs/TEAM-SPLIT.md и CODEOWNERS) |
| В демо-минимуме | нет — можно отложить |
| Статус | `in_progress` |

## Цель
Данные для кабинета: размеченные тексты по направлениям, справочник площадок с названиями, детерминированная история 12 месяцев, согласованная с реальными 14 днями (ТЗ 24.5, 20.7 № 36, 50, 70).

## Разделы ТЗ (docs/TZ.md)
§24.2, §24.5, §4.4, §3.7

## Контракты
- `data/corpus/reviews/product_lines_v1/`
- `data/import/messages/`
- `data/platforms.yaml`
- `data/baseline/*.dump (пересоздание)`

## Зависимости
- Зависит от: [T-236](T-236-spravochnik-product-lines-15-napravlenij-data-pr.md), [T-237](T-237-kontrakty-kabineta-csi-i-vsp-migraciya-0005-open.md), [T-019](T-019-biblioteka-tekstov-signalov.md)
- Блокирует: —

## Что сделать
1. Корпус: ≥ 150 синтетических отзывов (по 54 из пропорций ЕТЗ + расширение), эталон `product_line` и уровень, поле `source_platform` (код из `data/platforms.yaml`) и синтетический `source_url`; нет реальных названий банков и ПДн (`test_no_pii`).
2. Справочник `data/platforms.yaml` (20.7 № 70): код, отображаемое название площадки (ru/en), тип `review_portal|telegram_channel|app_store|forum|other`; названия показываются в UI текстом, без логотипов и внешних ссылок; тест на отсутствие URL реальных страниц в UI-полях.
3. Импорт датасета отзывов (JSON/CSV/XLSX) через `app/ingest/normalizer.py` с сохранением `source_url` и `date`; идемпотентность `(source_code, external_id)`; живого парсинга нет.
4. Генератор `product_signal_history` (12 месяцев) от `sim_state.seed` через `app/sim/rng.py`: сезонность, всплески на сбоях; хвост согласован с реальными сигналами baseline (тест расхождения ≤ 2 %).
5. Расширение матрицы покрытия: ≥ 1 сигнал на каждое направление × канал; пересоздание baseline-дампа `data/baseline/<profile>.dump` процедурой `app/sim/baseline.py` (T-032), обновить `settings.coverage`.

## Критерии приёмки
- [x] Покрытие: ≥ 1 сигнал на направление × канал; `test_coverage` и `test_no_pii` зелёные.
- [x] Два запуска с одним сидом дают одинаковую историю.
- [x] Хвост истории согласован с реальными 14 днями.
- [ ] `make lint && make test` зелёные; Definition of Done из AGENTS.md §8 выполнен.

## Как проверить
```bash
make seed PROFILE=lite && pytest backend/tests/integration/test_coverage.py backend/tests/unit/test_product_history.py
pytest backend/tests/unit/test_no_pii.py
```

## Отчёт субагента

Реализованы 162 осмысленных синтетических отзыва с точными долями 3×54,
ограниченный импорт JSON/CSV/XLSX через normalizer и отдельная проекция trusted
seed. Generic CLI игнорирует gold; editorial sentiment: 139/14/9. OpenAPI 1.5.19
публикует только известный SourcePlatform DTO; лента и карточка показывают ru/en
название текстом, без URL/href/логотипа.

Миграция 0014 после actual P1/0013 сохраняет legacy NULL owner/quality. Новые
записи требуют известный run_id и согласованные counts/coverage; FK CASCADE,
missing sentiment не считается neutral, loss_rub остаётся NULL. Mixed legacy
aggregate возвращает unknown/NULL. Денежные формулы и HITL не менялись.

Default lite, 1000 клиентов: 24000 операций и 1168 сигналов — исходные 800 T019,
162 отзыва, 151 экземпляр покрытия, 53 настоящих hard и 2 noise. Покрыты все
180 direction×channel и прежние 480 cells; hard_share=0.25, noise denominator
сохранён. Два свежих builder-вызова равны 180 persisted rows; хвост 313 совпадает
по каждой line/source/severity ячейке (0%). Ещё 855 unmapped не приписаны продукту.
CSI: 84 строки (69 исходных + 15 новых с реальными branch FK); 480 — размер
матрицы, не число CSI. Voice/branch — synthetic text, без фиктивного audio/STT.
Повтор seed и native PG16 dump/restore сохраняют историю и счётчики; immutable
архив/sidecars, SHA и область схемы 0014 записаны в proof JSON.

Проверен source-qualified regression union: 1961 backend passed / 24 skipped,
225 frontend. Полный make выявил шесть устаревших fixture expectations; после
исправлений 9 affected tests зелёные. Scenarios: 42/2 skip и исправленный explicit
replay/Pro сценарий 09 дают 43/2 skip; compliance — 31 passed. Assertions,
кассеты, responses/hashes сохранены. Final make lint: Ruff 413, mypy 275,
drift 192/192; licenses 550, contracts 45/162, Alembic zero drift. Обе production
сборки успешны. Changed coverage: 776/815=95.21%. Actual UI ru/en×themes:
4 screenshots, 85 table fingerprints неизменны, 0 LLM/external/writes.

Ограничения: explicit linked-fault spike mechanism unit-tested, но baseline не
содержит подтверждённых fault→physical-line bindings (0 linked months); они не
выдумываются. T241 cabinet API и будущие 0015/16/17 этим не проверены. Canonical/prod
не тронуты. **Не done до exact-head CI, final contract/cross-layer review и parent
PR/merge**; один успешный полный make на final head не заявляется.

Доказательства: [history/contract review](../reviews/T-240-history-contract.md),
[default lite proof](../reviews/T-240-default-lite-proof.json),
[coverage](../reviews/T-240-changed-coverage.json),
[actual UI proof](../reviews/T-240-platform-ui-proof.md).
