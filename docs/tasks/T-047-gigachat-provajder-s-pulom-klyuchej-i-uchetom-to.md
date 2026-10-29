# T-047 — GigaChat-провайдер с пулом ключей и учётом токенов

| Поле | Значение |
|---|---|
| Эпик | E4 LLM-слой |
| Субагент | `SA-LLM` (LLM-слой) |
| Оценка | M (1–2 дня) |
| Волна | 1 |
| Слой | `L1` Базис (владелец — см. docs/TEAM-SPLIT.md и CODEOWNERS) |
| В демо-минимуме | да |
| Статус | `done` |

## Цель
Работа с GigaChat-3-Ultra/Pro/Lightning по Authorization key, два ключа, лимит 50 млн токенов на ключ.

## Разделы ТЗ (docs/TZ.md)
§5.2, §20.1 п. 5–6

## Контракты
- `db/schema.sql: llm_api_keys`

## Зависимости
- Зависит от: [T-046](T-046-interfejs-llm-provajdera-i-strukturirovannyj-vyv.md)
- Блокирует: [T-050](T-050-rate-limiter-byudzhety-fallback-i-maskirovanie-s.md), [T-185](T-185-llm-detektor-missellinga-lightning-podtverzhdeni.md), [T-194](T-194-provajder-replay-kassety-zapisannyh-otvetov-mode.md)

## Что сделать
1. langchain-gigachat (или прямой REST): получение access token по Authorization key + scope, автообновление за 60 с до истечения, сертификаты НУЦ Минцифры в образе (verify) с переключателем.
2. Пул ключей: выбор по максимальному остатку; при 429/квоте — переключение и пометка last_error; учёт usage в tokens_used после каждого ответа; предупреждение в UI при остатке < 10 %.
3. Поддержка function calling и стриминга; маппинг моделей GigaChat-3-Ultra/Pro/Lightning.
4. Маскирование ключей в логах.

## Критерии приёмки
- [ ] Ручной тест с реальным ключом: классификация примера из golden → валидный JSON; usage записан.
- [ ] При исчерпании первого ключа второй подхватывается без ошибки запроса (тест с мок-сервером).
- [ ] `make lint && make test` зелёные; Definition of Done из AGENTS.md §8 выполнен.

## Как проверить
```bash
pytest backend/tests/unit/test_gigachat.py
python -m app.llm.smoke --profile gigachat_lightning
```

## Отчёт субагента
Коммит B02. `app/llm/gigachat.py` — REST-клиент httpx: OAuth (`Authorization: Basic <auth_key>`, RqUID, scope → access_token с кэшем и обновлением за 60 с до истечения), `chat/completions` (обычный и SSE-поток), классификация ошибок (401→auth+сброс токена, 429→rate_limit c Retry-After, 402/квота→quota). `app/llm/keys.py` — `KeyPool`: выбор ключа с максимальным `tokens_limit − tokens_used`, учёт usage после каждого ответа, 429 → пауза ключа, quota → ключ исчерпан, auth → неактивен; `from_env(GIGACHAT_AUTH_KEY_1/2)`. Тест `test_gigachat_oauth_key_rotation_and_repair`: ключ k1 получает 429 → k2 подхватывается в том же запросе; кривой JSON → повтор с ошибками → валидный; OAuth не дёргается при кэшированном токене. Отклонение от AGENTS §6.3: вместо langchain-gigachat — httpx (меньше зависимостей, единый транспорт с replay/openai_compat, полный контроль usage и чанков). Ручной тест с реальным ключом не выполнялся (ключей в среде нет) — выполнить `python -m app.llm.smoke` с заполненным .env. Синхронизация пула с таблицей `llm_api_keys` (pgp_sym_encrypt) — в карточке мастера настройки T-009.

Доработка 29.10.2026 по расследованию mock-нормализации: конкурентное обновление OAuth одного ключа сериализовано, кэш токена проверяется под lock. Это предотвращает всплеск OAuth-запросов при старте очереди; найденные в журналах oauth 429 не выдаются за ошибку качества модели. Регрессия: восемь конкурентных запросов получают один refresh. Контракт провайдера и TLS сохранены.
