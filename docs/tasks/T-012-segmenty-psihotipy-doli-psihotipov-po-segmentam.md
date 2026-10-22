# T-012 — Сегменты, психотипы, доли психотипов по сегментам

| Поле | Значение |
|---|---|
| Эпик | E2 Справочники и генераторы данных |
| Субагент | `SA-Refs` (справочники) |
| Оценка | S (≤ 0,5 дня) |
| Волна | 1 |
| Слой | `L1` Базис (владелец — см. docs/TEAM-SPLIT.md и CODEOWNERS) |
| В демо-минимуме | да |
| Статус | `todo` |

## Цель
Параметры из ТЗ 3.1 и 4.5 в YAML и БД.

## Разделы ТЗ (docs/TZ.md)
§3.1, §4.5

## Контракты
- `db/schema.sql: segments, psychotypes, segment_psychotype_mix`
- `events/behavior/psychotype_params.schema.json`

## Зависимости
- Зависит от: —
- Блокирует: [T-015](T-015-shablony-uvedomlenij-spravochnik-podarkov-stavki.md), [T-016](T-016-generator-klientov-profili-lite-demo-stress.md), [T-019](T-019-biblioteka-tekstov-signalov.md), [T-161](T-161-parametricheskaya-model-sostoyanij-klienta.md)

## Что сделать
1. data/segments.yaml: 7 сегментов с долями (55/15/10/7/8/4/1), SLA первого ответа, множители, CLV-диапазоны, тон, флаги HITL/менеджер.
2. data/psychotypes.yaml: 8 психотипов с параметрами по схеме psychotype_params (значения из таблицы ТЗ 4.5, веса каналов, базовый hazard, чувствительности).
3. Доли психотипов по сегментам из ТЗ 4.5; валидация суммы = 1 по каждому сегменту.
4. Загрузчик scripts/seed/refs_segments.py.

## Критерии приёмки
- [ ] Каждый params проходит валидацию по JSON-схеме (тест).
- [ ] Суммы долей = 1.
- [ ] Значения совпадают с ТЗ 4.5 (ревью техлида).
- [ ] `make lint && make test` зелёные; Definition of Done из AGENTS.md §8 выполнен.

## Как проверить
```bash
pytest backend/tests/unit/test_refs_psychotypes.py
```

## Отчёт субагента
Ветка main, коммит B21. `data/segments.yaml` (7 сегментов, доли 55/15/10/7/8/4/1 = 1.0, первый ответ, множитель приоритета, CLV-диапазон, тон, HITL для ultra_vip), `data/psychotypes.yaml` (8 психотипов; params по `behavior/psychotype_params.schema.json`: p_complain, задержки, терпение, веса заботы, веса каналов, эластичности, base_churn_hazard; segment_mix по ТЗ 4.5, сумма по сегменту = 1.0). Загрузка `scripts/seed/refs.py::seed_segments` (upsert). Тесты: `tests/unit/test_textgen.py::test_reference_yaml_consistency`, `tests/integration/test_coverage.py::test_reference_counts`. Время: ~15 мин.
