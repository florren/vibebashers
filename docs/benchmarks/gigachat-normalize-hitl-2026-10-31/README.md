# GigaChat: нормализация и продолжение HITL, 31.10.2026

Проверен текущий стенд, Fast=GigaChat-3-Lightning, Main=GigaChat-3-Ultra.
Ключи оставались внутри backend-контейнера и не записывались в артефакты.
Бенчмарк не создаёт сигналы, не меняет настройки и БД. Использованы штатные
system/normalize-промпты и JSON Schema, ответы прошли валидацию провайдера.

## Набор и метод

`cases.json`: 8 sentiment_v1, 8 hidden_negativity_v1, два текста предыдущего live E2E,
англоязычный вопрос и длинное формальное обращение (20 кейсов). Синтетические тексты,
включая жалобы, сарказм, угрозу ухода, благодарность, вопросы, суммы и ошибки.

Baseline: по две попытки на кейс с бюджетом 8 и 10 секунд, порядок чередовался,
кэш OAuth общий внутри процесса. `results.json` содержит все 40 результатов,
включая неуспехи; прогревочные отказы не исключались.

- 8 секунд: 19/20, timeout на sent-001 (8,011 с).
- Простые 10 секунд: 19/20, timeout на sent-001 (10,011 с).
- Остальные ответы валидны, иногда после штатного переключения Lightning → Ultra
  из-за bad_output. Это оставалось live GigaChat, не mock.

Кандидат: normalization=10 секунд, первичная попытка максимум 5 секунд, основная
модель получает остаток общего дедлайна; на timeout разрешено live-переключение.
Отдельный процесс и новый клиент/OAuth, тот же набор. `candidate-results.json`:
**20/20**, p95 (nearest rank) **4,323 с**, максимум **5,644 с**;
12 ответов Lightning, 8 Ultra, mock/replay отсутствуют. Переключение после timeout
отдельно проверено unit-тестом с управляемыми часами; live-сеть намеренно не задерживалась.

## Воспроизведение

Из окружения backend с локально настроенными ключами; результаты не содержат ключей:

```bash
backend/.venv/bin/python scripts/bench_normalization_timeouts.py \
  --dataset docs/benchmarks/gigachat-normalize-hitl-2026-10-31/cases.json \
  --output /tmp/normalization-baseline.json --context fast_path --limits 8 10
backend/.venv/bin/python scripts/bench_normalization_timeouts.py \
  --dataset docs/benchmarks/gigachat-normalize-hitl-2026-10-31/cases.json \
  --output /tmp/normalization-candidate.json --context normalization --limits 10
```

В baseline сохранена прежняя политика fast_path. В live-эксперименте кандидата
менялся класс цепочки только отдельного тестового процесса; работающий backend
на протяжении сравнения оставался прежним. Конкурентная нагрузка не моделировалась.

## Регрессии

`test_normalization_budget.py`: резерв основной модели, timeout/bad_output,
сохранение поведения auth/quota/rate_limit, общий дедлайн 10 секунд, отдельный context.
`test_resume_recording.py`: пустая/непустая история, отсутствие запуска.
`test_resume_usage.py`: нормальный HITL, восстановление испорченного итога из шагов,
два follow-up без потери/повторного сложения токенов, latency и известной стоимости.

## Live HITL на текущей БД из образа кандидата

`SIG-105869 → AR-002121 → HD-001890 → INC-001394`, запуск 11 на паузе.
Тестовое решение accept отмечено codex_e2e и исключено из few-shot.
Lightning получил timeout после 5,003 с; Ultra завершил normalization, весь шаг занял
7,830 с. Classify — Ultra 3,955 с, decide — Ultra 4,262 с, mock/replay не использованы.

До HITL: prompt 7995, completion 1317, total **9312**, latency **16047 мс**.
После HITL: те же **9312** и **16047 мс**, равны сумме agent_steps. Cost сохранён
(в текущем профиле нулевой тариф); ненулевая стоимость проверена детерминированной
регрессией. Проводок ledger_entries для этого AR — 0.
Результат сохранён в `live-candidate.json`. Код кандидата работал в отдельном контейнере
с разобранным окружением стенда; работающий сервис не заменялся до merge.

Проверки: make lint (ruff/format/mypy/OpenAPI drift), make test, контракты,
регрессии бюджетов и HITL/follow-up. Локально: 614 unit passed/17 skipped,
142 integration passed/4 skipped, 22 scenarios passed/2 skipped. После добавления
регрессий неизменности fast_path/default финальный unit-прогон: 617 passed/17 skipped.
