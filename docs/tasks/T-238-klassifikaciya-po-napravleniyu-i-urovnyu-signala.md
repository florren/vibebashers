# T-238 — Классификация по направлению и уровню сигнала: product_line, signal_level, промпт vN, набор product_lines_v1

| Поле | Значение |
|---|---|
| Эпик | E19 Кабинет менеджера продукта и продуктовый разрез [ЕТЗ] |
| Субагент | `SA-Prompts` (промпты и классификатор) |
| Оценка | M (1–2 дня) |
| Волна | 8 |
| Слой | `L3` Агент и контуры (владелец — см. docs/TEAM-SPLIT.md и CODEOWNERS) |
| В демо-минимуме | нет — можно отложить |
| Статус | `todo` |

## Цель
Каждый сигнал получает направление из 15 и подпись уровня (ЕТЗ FR-2.4–2.5, ТЗ 24.3) с точностью ≥ 0,80.

## Разделы ТЗ (docs/TZ.md)
§24.3, §7, §14.3

## Контракты
- `events/agent/classification.schema.json (product_line, secondary_lines, confidence)`
- `data/bench/product_lines_v1.jsonl`

## Зависимости
- Зависит от: [T-060](T-060-uzel-classify-i-prompty-v1.md), [T-237](T-237-kontrakty-kabineta-csi-i-vsp-migraciya-0005-open.md), [T-236](T-236-spravochnik-product-lines-15-napravlenij-data-pr.md)
- Блокирует: [T-241](T-241-api-kabineta-menedzhera-api-cabinet-overview-sig.md)

## Что сделать
1. Новая версия промпта классификации (`prompts/vN/classify.md`): список направлений из `product_lines.yaml`, примеры уровней из ЕТЗ 3.3, запрет придумывать направление, `other` при низкой уверенности.
2. Детерминированные подсказки до LLM: `product_code`/`system_code`/`error_code`/канал → кандидаты направления; mock-провайдер использует те же правила.
3. Подписи уровня (`criticality` → «Высокий/Средний/Низкий») в представлении и API без нового перечисления; таблица соответствия в коде и тесте.
4. Набор `data/bench/product_lines_v1.jsonl` (≥ 150 текстов, все 15 классов, 20 % с сарказмом/опечатками; без реальных брендов и ПДн), метрика accuracy и матрица ошибок в `make bench SET=product_lines_v1`; gate по версии промпта.
5. Запись `product_line` в `signals.product_line_code` только через инструмент классификации/нормализатор (правило 2).

## Критерии приёмки
- [ ] accuracy ≥ 0,80 на основном провайдере; mock измеряется без порога.
- [ ] Сигнал получает `product_line` и подпись уровня; `other` не превышает 10 % на наборе.
- [ ] Версия промпта записывается в `agent_runs.prompt_version`.
- [ ] `make lint && make test` зелёные; Definition of Done из AGENTS.md §8 выполнен.

## Как проверить
```bash
make bench SET=product_lines_v1
pytest backend/tests/unit/test_product_line_classifier.py
```

## Отчёт субагента
_Заполняется исполнителем: ветка/PR, что сделано, отклонения от карточки, затронутые контракты, скриншоты/логи, время._
