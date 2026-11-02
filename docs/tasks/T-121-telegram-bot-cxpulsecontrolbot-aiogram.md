# T-121 — Telegram-бот @CXPulseControlBot (aiogram)

| Поле | Значение |
|---|---|
| Эпик | E9 Лендинг, трекинг, Telegram-бот |
| Субагент | `SA-TgBot` (Telegram-бот) |
| Оценка | L (3–4 дня) |
| Волна | 4 |
| Слой | `L3` Агент и контуры (владелец — см. docs/TEAM-SPLIT.md и CODEOWNERS) |
| В демо-минимуме | нет — можно отложить |
| Статус | `in_progress` |

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

## Ревизия T-121: подготовка границы сервиса

Ветка codex/T-121-telegram-service от maindfbf47a. Проверены существующий internal inbound, in-memory drafts и опубликованный backend port; отдельного tgbot сервиса нет. Конкретный проект service-to-service HMAC, durable dialog/receipts и backend delivery worker подmaintenance lease описан в docs/reviews/T-121-internal-boundary-proposal.md. API1.5.20/DDL0015 только зарезервированы, код/контракт/DDL пока не менялись. Требуется явное исключение из AGENTS§10 «Не добавлять аутентификацию» для внутреннего транспорта; UI роли остаются пресетами. Реальные Telegram calls/messages не выполнялись. После решения — реализация/fake tests и отдельное финальное contract review; это не готовый сервис.

## Одобренная внутренняя граница и первый checkpoint

Пользователь02.11.2026 разрешил только service-to-service HMAC исключение.
Реализованы чистый verifier и bounded ASGI middleware (31unit passed0.07s),
aiogram3 stateless adapter/custom public polling и signed backend transport
(19fake SDK/HTTP/license tests passed1.98s), без реальных Telegram запросов.
Бот имеет отдельный frozen uv environment (36distributions), чтобы aiogram
Pydantic<2.14 не понижал backend2.14.1. License gate530backend/npm+36bot green;
46backend signature/license tests passed0.11s. CI/Makefile включают bot checks.
Ни middleware, ни новый event transport пока не подключены к действующему route;
durable dialog/receipts/delivery, CLI/Compose и final API/DDL review ещё в работе.
Это checkpoint модулей, сервис не объявляется готовым.
