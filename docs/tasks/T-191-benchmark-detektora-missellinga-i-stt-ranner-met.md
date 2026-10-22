# T-191 — Бенчмарк детектора мисселлинга и STT: раннер, метрики, UI

| Поле | Значение |
|---|---|
| Эпик | E16 Аудиомониторинг отделения и мисселлинг [BRD] |
| Субагент | `SA-Bench` (бенчмарки) |
| Оценка | M (1–2 дня) |
| Волна | 4 |
| Слой | `L3` Агент и контуры (владелец — см. docs/TEAM-SPLIT.md и CODEOWNERS) |
| В демо-минимуме | нет — можно отложить |
| Статус | `todo` |

## Цель
Выбор модели детектора по F1 и латентности; сравнение STT-провайдеров по WER и задержке на экране бенчмарков (ТЗ 14.3, 22.4).

## Разделы ТЗ (docs/TZ.md)
§14.1, §14.3

## Контракты
- `db/schema.sql: bench_*, stt_metrics`
- `api/openapi.yaml: bench/*, stt/test`

## Зависимости
- Зависит от: [T-185](T-185-llm-detektor-missellinga-lightning-podtverzhdeni.md), [T-190](T-190-dialogi-otdeleniya-nabor-misselling-v1-predzapis.md), [T-129](T-129-benchmark-ranner-i-metriki.md), [T-130](T-130-ui-benchmarkov.md)
- Блокирует: —

## Что сделать
1. Тип набора misselling в бенчмарк-раннере: прогон по провайдерам (mock, Lightning, Ultra, OpenRouter-профили), precision/recall/F1 по категориям, доля ложных на чистых фразах, латентность p50/p95, токены.
2. scripts/stt_bench.py и вкладка «STT» на /bench: WER, partial/final latency по провайдерам на stt_v1.
3. UI: таблица и радар по категориям; рекомендация модели детектора по правилу F1 ≥ 0,8 с минимальной латентностью.

## Критерии приёмки
- [ ] Отчёт бенчмарка misselling_v1 по ≥ 3 провайдерам в PR.
- [ ] Экран показывает выбранную модель и причину выбора.
- [ ] `make lint && make test` зелёные; Definition of Done из AGENTS.md §8 выполнен.

## Как проверить
```bash
make bench DATASET=misselling_v1
cd frontend && npm run test -- bench
```

## Отчёт субагента
_Заполняется исполнителем: ветка/PR, что сделано, отклонения от карточки, затронутые контракты, скриншоты/логи, время._
