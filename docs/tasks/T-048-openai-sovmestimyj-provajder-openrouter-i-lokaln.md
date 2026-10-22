# T-048 — OpenAI-совместимый провайдер: OpenRouter и локальная модель

| Поле | Значение |
|---|---|
| Эпик | E4 LLM-слой |
| Субагент | `SA-LLM` (LLM-слой) |
| Оценка | M (1–2 дня) |
| Волна | 1 |
| Слой | `L1` Базис (владелец — см. docs/TEAM-SPLIT.md и CODEOWNERS) |
| В демо-минимуме | да |
| Статус | `todo` |

## Цель
Бесплатные модели OpenRouter и любая локальная модель по OpenAI API без изменений кода.

## Разделы ТЗ (docs/TZ.md)
§5.2, §14.3, §20.2 п. 1–2

## Контракты
- `db/schema.sql: llm_profiles`

## Зависимости
- Зависит от: [T-046](T-046-interfejs-llm-provajdera-i-strukturirovannyj-vyv.md)
- Блокирует: [T-050](T-050-rate-limiter-byudzhety-fallback-i-maskirovanie-s.md)

## Что сделать
1. openai SDK с base_url из профиля; заголовки HTTP-Referer/X-Title для OpenRouter; поддержка моделей nvidia/nemotron-3-ultra-550b-a55b:free, openrouter/owl-alpha, openai/gpt-oss-120b:free по умолчанию.
2. Проверка доступности id через GET /api/v1/models при старте и в мастере; предложение замены (nvidia/nemotron-3-super-120b-a12b:free или первая из коллекции free).
3. Чтение баланса и лимитов GET /api/v1/key → LlmApiKey.balance_usd, rpd_limit; бюджетный лимит платных моделей (settings.llm.openrouter_budget_usd, по умолчанию 10).
4. Профиль local_openai: base_url из LOCAL_LLM_BASE_URL, без ключа или с ключом.

## Критерии приёмки
- [ ] Smoke-тест на трёх моделях по умолчанию возвращает валидный JSON классификации (лог в PR).
- [ ] Исчезновение модели не ломает запуск — профиль деактивируется с предупреждением.
- [ ] `make lint && make test` зелёные; Definition of Done из AGENTS.md §8 выполнен.

## Как проверить
```bash
python -m app.llm.smoke --profile or_gpt_oss_120b
```

## Отчёт субагента
_Заполняется исполнителем: ветка/PR, что сделано, отклонения от карточки, затронутые контракты, скриншоты/логи, время._
