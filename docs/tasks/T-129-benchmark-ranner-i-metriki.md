# T-129 — Бенчмарк-раннер и метрики

| Поле | Значение |
|---|---|
| Эпик | E10 Бенчмарки и экономика |
| Субагент | `SA-Bench` (бенчмарки) |
| Оценка | L (3–4 дня) |
| Волна | 3 |
| Слой | `L3` Агент и контуры (владелец — см. docs/TEAM-SPLIT.md и CODEOWNERS) |
| В демо-минимуме | да |
| Статус | `review` |

## Цель
Прогон золотого набора по профилям LLM с метриками ТЗ 14.2, прогнозом расхода и соблюдением лимитов.

## Разделы ТЗ (docs/TZ.md)
§14.2, §14.3, §5.2

## Контракты
- `api/openapi.yaml: bench/*`
- `db/schema.sql: bench_*`

## Зависимости
- Зависит от: [T-060](T-060-uzel-classify-i-prompty-v1.md), [T-050](T-050-rate-limiter-byudzhety-fallback-i-maskirovanie-s.md), [T-021](T-021-zolotoj-nabor-benchmarka-golden-v1-i-lite-v1.md)
- Блокирует: [T-066](T-066-versionirovanie-promptov-i-gate-na-lite-benchmar.md), [T-130](T-130-ui-benchmarkov.md), [T-191](T-191-benchmark-detektora-missellinga-i-stt-ranner-met.md), [T-210](T-210-trehklassnaya-tonalnost-sentiment-prompt-soglaso.md)

## Что сделать
1. app/bench/runner.py: фоновые прогоны с конкурентностью по профилю (учёт rpm), repeats для стабильности, запись bench_results; metrics.py: accuracy по полям, recall критичных, json_valid_rate, tool_success_rate, retries, fallback_rate, p50/p95, токены, cost, stability (согласованность между повторами).
2. Прогноз расхода (dry_run): токены по средней длине промпта, запросы vs rpd_limit и остаток токенов ключа; предупреждение при превышении.
3. Экспорт CSV/JSON; отмена прогона.

## Критерии приёмки
- [ ] Прогон lite_v1 на mock ≤ 30 с; на Lightning — без превышения лимитов.
- [ ] Метрики воспроизводимы на mock (тест).
- [ ] `make lint && make test` зелёные; Definition of Done из AGENTS.md §8 выполнен.

## Как проверить
```bash
pytest backend/tests/unit/test_bench.py
make bench DATASET=lite_v1 PROFILE=mock
```

## Отчёт субагента
Ветка: `codex/t129-bench-jobs` (PR с этой веткой, 28.10.2026).

Реализован `BenchService`: отдельный фоновый прогон каждого выбранного активного профиля, последовательная очередь внутри профиля, общий RPM/RPD limiter, прогноз и повторная проверка квот после очереди, сохранение `bench_runs`/`bench_results`, WS `bench.progress`, отмена и восстановление после перезапуска. Выбранный провайдер не подменяется mock при ошибке. Расход ключа и результаты сохраняются одной транзакцией; откат не удваивает счётчики. Исправлены преобразование PostgreSQL Decimal для стоимости и метрика успешности structured output. CSV включает токены; `make bench DATASET=lite_v1 PROFILE=mock` запускает локальный mock-раннер.

Проверено: `make lint`; 18 targeted unit-тестов; 7 integration-тестов (выбранные профили, WS, повторы/стабильность, стоимость, экспорт, перезапуск, отмена, невалидные наборы и лимиты, ошибка провайдера, откат учёта ключа); покрытие нового `service.py` — 85%; mock CLI; frontend lint/typecheck, 75 Vitest и build. Полный `make test` и CI проверяются перед merge, результат фиксируется в PR.

Контракты не менялись. `cross-layer` согласован пользователем: API и lifecycle (`backend/app/api/bench.py`, `backend/app/main.py`), общий лимитер (`backend/app/llm/ratelimit.py`), Makefile и документация. Пакеты и переменные окружения не добавлены. Бенчмарк classify показывает только непустые наборы с `gold.signal_type` в каждом кейсе; sentiment-отчёт не выдаёт accuracy классификации за macro-F1. CLI для немоковых профилей выдаёт только прогноз, живые вызовы доступны через API.

Ограничения: процесс один (как предусмотрено AGENTS.md), суточный счётчик профиля хранится в общем лимитере процесса; расход сохранённых ключей переживает рестарт. Live GigaChat/Lightning в рамках проверки не вызывались; проверены только mock/синтетические провайдеры. Нагрузочный прогон с живыми ключами остаётся отдельной проверкой.
