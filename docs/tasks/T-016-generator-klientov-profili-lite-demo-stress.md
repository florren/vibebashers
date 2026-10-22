# T-016 — Генератор клиентов (профили lite/demo/stress)

| Поле | Значение |
|---|---|
| Эпик | E2 Справочники и генераторы данных |
| Субагент | `SA-Clients` (клиенты и операции) |
| Оценка | M (1–2 дня) |
| Волна | 2 |
| Слой | `L2` Симулятор и данные (владелец — см. docs/TEAM-SPLIT.md и CODEOWNERS) |
| В демо-минимуме | да |
| Статус | `todo` |

## Цель
Синтетические клиенты с сегментом, психотипом, географией и контактами без ПДн.

## Разделы ТЗ (docs/TZ.md)
§4.4, §3.1, §3.2, §4.5, §13

## Контракты
- `db/schema.sql: clients`

## Зависимости
- Зависит от: [T-005](T-005-primenenie-schema-sql-sqlalchemy-modeli-sessii.md), [T-011](T-011-spravochnik-subektov-i-gorodov-rf-svg-karta.md), [T-012](T-012-segmenty-psihotipy-doli-psihotipov-po-segmentam.md)
- Блокирует: [T-003](T-003-install-sh-ustanovka-odnoj-komandoj.md), [T-009](T-009-api-mastera-nastrojki-i-proverok-podklyucheniya.md), [T-017](T-017-produkty-klientov-i-14-dnej-operacij.md), [T-022](T-022-testy-dannyh-no-pii-pokrytie-idempotentnost-proi.md), [T-178](T-178-korpus-publichnyh-otzyvov-i-nabor-reviews-v1.md)

## Что сделать
1. scripts/seed/clients.py: распределение по регионам пропорционально населению с поправкой (столицы ×1.3), по сегментам из segments.yaml, психотип по segment_psychotype_mix; seeded RNG.
2. Синтетические имена из списков data/names_*.txt (вымышленные), телефоны +7 900 000-00-00…+7 900 009-99-99, email @example.ru, ник; clv_estimate в диапазоне сегмента; activity_baseline по сегменту.
3. Профили: lite 1 000, demo 5 000, stress 20 000; пакетная вставка COPY/executemany.
4. Отчёт распределений в лог (сегменты, округа, психотипы).

## Критерии приёмки
- [ ] demo генерируется ≤ 20 с; распределения в пределах ±2 п. п. от заданных.
- [ ] Тест no-PII проходит.
- [ ] Повторный запуск без --reset не дублирует клиентов.
- [ ] `make lint && make test` зелёные; Definition of Done из AGENTS.md §8 выполнен.

## Как проверить
```bash
python scripts/seed/clients.py --profile lite --check
pytest backend/tests/unit/test_no_pii.py
```

## Отчёт субагента
Ветка main, коммит B21. `scripts/seed/textgen.py` — генератор текстов из `data/corpus/signal_templates.yaml` (10 типов × 4 продукта, ≥ 1 шаблон на пару) со стилями plain/sarcasm/slang/typos/caps (доля «трудных» ≈ 39 %, порог 25 %); gold-разметка (sentiment, negativity, flags, system, error_code). `clients.py::seed_history_signals` — история сигналов/инцидентов в `sim_runs` kind=baseline: все 440 комбинаций тип×продукт×канал, каждая ячейка SLA ≥ 5 инцидентов, статусы closed/resolved/in_progress/routed/awaiting_client/escalated/verifying/new, outcome_class и sla_breached. `coverage.py` → `settings.coverage`; exit code 2 при неполном покрытии. Тест `tests/integration/test_coverage.py`. Время: ~50 мин.
