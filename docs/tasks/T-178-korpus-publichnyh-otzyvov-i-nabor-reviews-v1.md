# T-178 — Корпус публичных отзывов и набор reviews_v1

| Поле | Значение |
|---|---|
| Эпик | E15 Внешние площадки и автономный возврат [BRD] |
| Субагент | `SA-Signals` (тексты и предыстория сигналов) |
| Оценка | M (1–2 дня) |
| Волна | 2 |
| Слой | `L2` Симулятор и данные (владелец — см. docs/TEAM-SPLIT.md и CODEOWNERS) |
| В демо-минимуме | нет — можно отложить |
| Статус | `todo` |

## Цель
300+ синтетических отзывов под никами (сарказм, агрессия, суммы, маскированные карты) и размеченный набор для метрик нормализации и матчинга (ТЗ 14.3, 15 SA-Reviews).

## Разделы ТЗ (docs/TZ.md)
§14.3, §15, §21.3

## Контракты
- `events/agent/normalization.schema.json`
- `db/schema.sql: bench_datasets, bench_cases, external_posts`

## Зависимости
- Зависит от: [T-016](T-016-generator-klientov-profili-lite-demo-stress.md), [T-019](T-019-biblioteka-tekstov-signalov.md), [T-021](T-021-zolotoj-nabor-benchmarka-golden-v1-i-lite-v1.md)
- Блокирует: [T-209](T-209-adaptery-istochnikov-ingest-sources-rest-polling.md), [T-219](T-219-korpusa-dtz-transcripts-v1-20-transkriptov-json.md)

## Что сделать
1. data/corpus/reviews/*.yaml: шаблоны по типам (комиссия, двойное списание, уведомления, акция, благодарность, вопрос) × тон × психотип; часть авторов сопоставима с клиентами (ник/карта из сида), часть — нет.
2. Набор reviews_v1 (100 кейсов) с эталонами negativity, intents, entities, contacts_hint, true_client_id; метрики: MAE негатива, F1 намерений/сущностей, точность матчинга.
3. Фоновые посты для /feed: генератор с интенсивностью из настроек.
4. Тест no-PII на корпус.

## Критерии приёмки
- [ ] Набор загружается бенчмарк-раннером (T-129) и даёт отчёт по провайдерам.
- [ ] ≥ 25 % отзывов с сарказмом/сленгом/опечатками.
- [ ] `make lint && make test` зелёные; Definition of Done из AGENTS.md §8 выполнен.

## Как проверить
```bash
pytest backend/tests/unit/test_reviews_corpus.py
make bench DATASET=reviews_v1 PROFILE=mock
```

## Отчёт субагента
Ветка main, коммит B21. `data/tariffs.yaml` (12 строк Mock-АБС: QR/СБП 0 %, снятие с кредитки 3,9 % + 390 ₽ и т. д.), `data/rules.yaml` (RULE-QR-FEE-001 → refund_fee с лимитами 5 000 ₽/3 за 30 дн., RULE-DOUBLE-DEBIT-001, RULE-PROMO-RATE-001, RULE-NOTIF-DUP-001, RULE-REPEAT-7D-001), `data/branches.yaml` (10 ВСП × 6 столов, ВСП № 0042 Самара: стол 3 — Петров П. П., стол 5 — Сидорова А. А.), загрузка `refs.py::seed_abs_rules/seed_branches`. Движок правил (app/rules/engine.py) — отдельная карточка, здесь только данные. Время: ~20 мин.
