# T-121 — Telegram-бот @CXPulseControlBot (aiogram)

| Поле | Значение |
|---|---|
| Эпик | E9 Лендинг, трекинг, Telegram-бот |
| Субагент | `SA-TgBot` (Telegram-бот) |
| Оценка | L (3–4 дня) |
| Волна | 4 |
| Слой | `L3` Агент и контуры (владелец — см. docs/TEAM-SPLIT.md и CODEOWNERS) |
| В демо-минимуме | нет — можно отложить |
| Статус | `todo` |

## Цель
Реальный внешний канал для финала: сценарий потенциального/неидентифицированного клиента, статусы в чат.

## Разделы ТЗ (docs/TZ.md)
§11.3, §18 сц. 4, §20.2 п. 3

## Контракты
- `api/openapi.yaml: internal/tgbot/inbound, public/bot/qr`

## Зависимости
- Зависит от: [T-062](T-062-uzel-act-kommunikacii-klientu-i-komandam.md), [T-120](T-120-stranica-trekinga-obrascheniya-i-dopolnenie.md)
- Блокирует: [T-122](T-122-qr-kod-bota-zhyuri-rezhim-i-instrukcii-dlya-fina.md), [T-157](T-157-yazyk-kommunikacij-s-klientom-i-en-shablony.md), [T-189](T-189-alert-o-missellinge-v-telegram-rukovoditelyu.md)

## Что сделать
1. tgbot/: aiogram 3 long polling; /start → «Вы клиент банка?» (кнопки) → свободный текст → уточнение региона/контакта → отправка в backend /api/internal/tgbot/inbound → ответ агента; привязка chat_id к signal/клиенту (clients.telegram_chat_id для «клиентов» по синтетическому коду из UI).
2. Backend: канал telegram_bot в notify_client (доставка через Bot API sendMessage), трекинг-ссылка и public_id в ответе; команды /status, /lang.
3. Отказоустойчивость: без токена сервис не стартует (compose profile), ошибки Bot API не влияют на симуляцию; rate limit 1 сообщение/с на чат.
4. Тексты ru/en по языку пользователя Telegram.

## Критерии приёмки
- [ ] Член жюри по QR проходит сценарий 4 до финального ответа; статусы приходят в чат.
- [ ] Все сообщения бота записаны в notifications с external_ref.
- [ ] `make lint && make test` зелёные; Definition of Done из AGENTS.md §8 выполнен.

## Как проверить
```bash
pytest tgbot/tests
ручной прогон с @CXPulseControlBot (лог в PR)
```

## Отчёт субагента
_Заполняется исполнителем: ветка/PR, что сделано, отклонения от карточки, затронутые контракты, скриншоты/логи, время._
