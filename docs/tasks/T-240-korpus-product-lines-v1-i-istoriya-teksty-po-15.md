# T-240 — Корпус product_lines_v1 и история: тексты по 15 направлениям, импорт отзывов с source_url, product_signal_history (12 мес.), справочник площадок

| Поле | Значение |
|---|---|
| Эпик | E19 Кабинет менеджера продукта и продуктовый разрез [ЕТЗ] |
| Субагент | `SA-Signals` (тексты и предыстория сигналов) |
| Оценка | M (1–2 дня) |
| Волна | 8 |
| Слой | `L2` Симулятор и данные (владелец — см. docs/TEAM-SPLIT.md и CODEOWNERS) |
| В демо-минимуме | нет — можно отложить |
| Статус | `todo` |

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
- [ ] Покрытие: ≥ 1 сигнал на направление × канал; `test_coverage` и `test_no_pii` зелёные.
- [ ] Два запуска с одним сидом дают одинаковую историю.
- [ ] Хвост истории согласован с реальными 14 днями.
- [ ] `make lint && make test` зелёные; Definition of Done из AGENTS.md §8 выполнен.

## Как проверить
```bash
make seed PROFILE=lite && pytest backend/tests/integration/test_coverage.py backend/tests/unit/test_product_history.py
pytest backend/tests/unit/test_no_pii.py
```

## Отчёт субагента
_Заполняется исполнителем: ветка/PR, что сделано, отклонения от карточки, затронутые контракты, скриншоты/логи, время._
