# T-210 — Трёхклассная тональность sentiment: промпт, согласование с порогами negativity, набор sentiment_v1 и бенчмарк ≥ 80 %

| Поле | Значение |
|---|---|
| Эпик | E18 Приём транскриптов, роутер-инструменты, «красные фразы», зоны карты [ДТЗ] |
| Субагент | `SA-Prompts` (промпты и классификатор) |
| Оценка | M (1–2 дня) |
| Волна | 3 |
| Слой | `L3` Агент и контуры (владелец — см. docs/TEAM-SPLIT.md и CODEOWNERS) |
| В демо-минимуме | да |
| Статус | `todo` |

## Цель
Каждый сигнал получает sentiment ∈ {positive, neutral, negative}; на sentiment_v1 основной провайдер даёт accuracy ≥ 0,80 (ДТЗ FR-2.1, ТЗ 7, 14.3, критерий 27).

## Разделы ТЗ (docs/TZ.md)
§7, §14.3, §19, §20.6

## Контракты
- `events/agent/normalization.schema.json: sentiment`
- `events/agent/classification.schema.json: sentiment`
- `api/openapi.yaml: GET /api/bench/sentiment, SentimentBenchReport`
- `db/schema.sql: signals.sentiment`

## Зависимости
- Зависит от: [T-059](T-059-uzly-ingest-normalize-identify-client-gather-con.md), [T-060](T-060-uzel-classify-i-prompty-v1.md), [T-129](T-129-benchmark-ranner-i-metriki.md), [T-207](T-207-edinaya-shema-soobscheniya-i-normalizator-ingest.md)
- Блокирует: [T-211](T-211-detektor-skrytogo-negativa-few-shot-prompt-hidde.md), [T-212](T-212-problem-summary-problem-severity-suggested-team.md)

## Что сделать
1. Промпт normalize v1.1: инструкция по трём классам с примерами пограничных случаев; structured output с sentiment; сервис сверяет с порогами negativity (≤33/34–66/≥67), расхождение → метрика threshold_agreement и лог.
2. Набор data/bench/sentiment_v1.jsonl: 300 текстов (100/100/100), 20 % с сарказмом/сленгом, все каналы, без ПДн; разметка перекрёстно двумя генераторами + ручная проверка 50 примеров.
3. Раннер бенчмарка (расширение раннера T-129): accuracy, macro-F1, матрица ошибок по провайдерам; отчёт в data/bench/reports/sentiment_<date>.json; GET /api/bench/sentiment; карточка на экране бенчмарков.
4. Сигнал: signals.sentiment пишется после normalize; фильтр sentiment в GET /api/signals и /api/incidents.
5. Если основной провайдер < 0,80 — итерация промпта (не более 3) с отчётом по каждой.

## Критерии приёмки
- [ ] Отчёт бенчмарка с accuracy ≥ 0,80 для основного провайдера лежит в репозитории.
- [ ] Сарказм из сценария 11 → negative.
- [ ] `make lint && make test` зелёные; Definition of Done из AGENTS.md §8 выполнен.

## Как проверить
```bash
make bench SET=sentiment_v1
pytest backend/tests/unit/test_sentiment_thresholds.py
```

## Отчёт субагента
Ветка `feat/b04-agent`. Трёхклассная тональность: normalize → sentiment positive/neutral/negative согласован с negativity (≤33/≤66/>66), сарказм/угроза ухода → negative; classify наследует sentiment нормализации и правит tone; пишется signals.sentiment (фильтр /api/incidents?sentiment= через v_tickets). Промпт `normalize.md` описывает критерии и скрытый негатив. **Отклонение:** прогон бенча sentiment (data/bench/*) и метрики — в T-129 (bench-раннер). Время: ~20 мин.
