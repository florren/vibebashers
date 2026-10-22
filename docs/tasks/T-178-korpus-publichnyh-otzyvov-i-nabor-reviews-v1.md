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
Ветка main, коммит B21 (данные). `data/corpus/mock_feed.yaml` — 30 публичных постов (vk/ok/telegram_comments/review_portal) с gold (sentiment, hidden_negativity, flags), включая feed-0001 (сценарий 11, сарказм + повтор + churn_intent) и feed-0002 (сценарий 8, комиссия за QR 450 ₽, Воронеж); `data/corpus/signal_templates.yaml` — шаблоны обращений 10 типов × 4 продукта + обёртки сарказма/сленг/опечатки; бенчи `data/bench/sentiment_v1.jsonl` (300), `hidden_negativity_v1.jsonl` (120), `summary_v1.jsonl` (60), `golden_v1.jsonl` (120) — генерируются `scripts/seed/gen_corpora.py` (детерминировано) и загружаются в bench_datasets/bench_cases. Отклонение: отдельный reviews_v1 не выделен — публичные отзывы входят в mock_feed и sentiment_v1 (tags=feed); эмулятор площадки (public_posts) — карточка L3. Время: ~30 мин.
