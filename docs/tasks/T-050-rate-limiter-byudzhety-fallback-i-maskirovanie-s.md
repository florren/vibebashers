# T-050 — Rate limiter, бюджеты, fallback и маскирование секретов

| Поле | Значение |
|---|---|
| Эпик | E4 LLM-слой |
| Субагент | `SA-LLM` (LLM-слой) |
| Оценка | S (≤ 0,5 дня) |
| Волна | 2 |
| Слой | `L1` Базис (владелец — см. docs/TEAM-SPLIT.md и CODEOWNERS) |
| В демо-минимуме | да |
| Статус | `todo` |

## Цель
Симуляция не останавливается при лимитах и сбоях провайдеров; расход прозрачен.

## Разделы ТЗ (docs/TZ.md)
§5.2, §16.4

## Контракты
- `db/schema.sql: llm_api_keys, agent_runs (outcome fallback_mock)`

## Зависимости
- Зависит от: [T-047](T-047-gigachat-provajder-s-pulom-klyuchej-i-uchetom-to.md), [T-048](T-048-openai-sovmestimyj-provajder-openrouter-i-lokaln.md), [T-049](T-049-mock-provajder-pravila-shablony-determinizm.md)
- Блокирует: [T-051](T-051-api-i-ui-profilej-llm-i-klyuchej.md), [T-129](T-129-benchmark-ranner-i-metriki.md)

## Что сделать
1. Token bucket per profile (rpm) + суточный счётчик (rpd) в llm_api_keys; очередь ожидания с таймаутом 20 с, затем fallback.
2. Политика fallback: main → fast → mock; результат помечается outcome=fallback_mock, в UI — бейдж.
3. Единый фильтр логов, маскирующий Authorization/api_key; тест на отсутствие ключей в логах.

## Критерии приёмки
- [ ] При искусственном 429 на main запрос уходит в fast, затем в mock без ошибок для пользователя.
- [ ] Остаток лимитов виден в /api/settings/llm-keys.
- [ ] `make lint && make test` зелёные; Definition of Done из AGENTS.md §8 выполнен.

## Как проверить
```bash
pytest backend/tests/unit/test_ratelimit.py
```

## Отчёт субагента
Доработка 29.10.2026: если все активные неизрасходованные ключи временно на cooldown после 429, KeyPool сообщает rate_limit с retry_after_s, а не исчерпанную quota. Существующее поведение смешанных quota/cooldown и авторизации сохранено. Ошибки ресурса не инициируют повтор той же операцией через другую модель.
