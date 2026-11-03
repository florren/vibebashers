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

## Checkpoint durable transport и доставки (02.11.2026)

API1.5.20/actualDDL0015, signed-before-DB inbound, durable encrypted dialogue/receipt,
opt-in signal/client grants, aiogram polling, backend delivery worker и optional
Compose profile реализованы; обзор: docs/reviews/T-121-delivery-review.md.
Это checkpoint, статус in_progress: новый полный набор, coverage, final UI proof,
финальный contract review/CI и merge ещё впереди. Реальных Telegram calls не было;
ручной критерий жюри остаётся непроверенным. Старые подразделы выше описывают историю
подготовки, а не текущую степень реализации.

## Результат реализации и полные проверки

API20/actual0015, durable signed dialogue/outbox, real-capable deliveryworker,
opt-in grants, explicitinstall/Compose реализованы. Fullsource7acce1b:2097backend
passed/22skip,331front,34bot. Currentmaincomposition3450afe:1640unit/18skip,
348front/lint,15PG93.85s, licenses550+36; добавленныйbackend575/62392.30%,
bot209/21995.43%. Actual4ru/en/themeUI,94tablesunchanged/noexternal/LLM.
Источники, границы и rollback:docs/reviews/T-121-{delivery-review.md,final-verification.json}.
Статусin_progress доcontractreview/CI/merge; настоящийжюриTelegramсценарийне
проверялся и неавторизован. T122readiness/QR иT189managerHITL — отдельные карточки.

## Contract-change review

Метка: `contract-change`. OpenAPI1.5.20 и actual0015 меняют обязательные inbound
headers/body и notification status. Конкретный final diff, paired rollout,
forward-only rollback и проверки: docs/reviews/T-121-delivery-review.md.
Согласование service-to-service исключения не заменяет этот final review.


### Проверка хронологии перед фризом — 03.11.2026

Ветка `codex/channel-chronology`: исправлены общие wall-clock даты /feed, transaction-start timestamp публичного ответа, сортировка PersonalChat с offsets/microseconds и own-run clock Telegram ACK. API/DDL без изменений. 2178 unit / 19 skipped, 579 frontend, 13 финальных новых PG, 52 смежных PG regression и 4 browser cases. Реальные внешние вызовы не выполнялись. Один legacy gift timestamp остаётся открытым; 100% покрытия/чистоты истории не заявляется. Границы доказательств и повторяемый audit: `docs/reviews/channel-chronology.md`.
