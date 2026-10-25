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
Ветка `feat/T-048-openrouter-chain` (коммит и PR не делались).

Цепочка по умолчанию: `gigachat,openai_compat,replay,mock`. Офлайн без сети остаётся `replay,mock` (`./install.sh --offline` и ручной `LLM_CHAIN=replay,mock` не переписывались). Бюджет платных моделей: `OPENROUTER_BUDGET_USD=10`.

OpenAI-совместимый провайдер оставлен на httpx; пакет openai SDK не добавлялся (отклонение от формулировки карточки и AGENTS §6.3).

Чужие файлы (cross-layer разрешён): `backend/app/api/setup.py` (L3), `backend/app/api/settings.py` (L3), `data/llm_profiles.yaml` (L2). Контракты не менялись.

Живой smoke трёх моделей не запускался. Проверки — юнит на `httpx.MockTransport`.
