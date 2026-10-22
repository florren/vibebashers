# T-047 — GigaChat-провайдер с пулом ключей и учётом токенов

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
_Заполняется исполнителем: ветка/PR, что сделано, отклонения от карточки, затронутые контракты, скриншоты/логи, время._
