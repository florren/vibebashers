# T-121: предлагаемая внутренняя граница Telegram

Статус: service-to-service исключение явно одобрено пользователем 02.11.2026.
Начата реализация transport/helpers; окончательный API/DDL review ещё впереди. Никаких
Telegram HTTP, getMe или сообщений реальным людям не выполнялось.

## Проверенные исходные условия

`backend/app/api/public.py` принимает `POST /api/internal/tgbot/inbound`:
`chat_id`, `kind`, `text`, optional username/payload. Route открывает обычную
DB-транзакцию; проверки вызывающего сервиса нет. Обработчик доверяет переданному
chat_id. `docker-compose.yml` публикует backend `8000:8000`, а не отдельный
внутренний listener. Название internal само по себе не ограничивает доступ.
Сервиса tgbot пока нет; `_bot_drafts` хранит состояние диалога в памяти.

При реализации реальной доставки сохранение этой границы позволит отправлять
запросы от имени произвольного chat_id. Роли UI остаются пресетами, как требует
AGENTS.md §5.20; их нельзя использовать для защиты внутренних сообщений.

## Конкретное предлагаемое исключение

Только service-to-service проверка общего секрета, без пользователей, логина,
RBAC или изменения роли демонстратора. Новая переменная `TGBOT_INTERNAL_SECRET`
хранится существующим способом в `.env`; install генерирует не менее 32 случайных bytes.
Compose передаёт боту только его token, internal secret и адрес backend,
без DB/LLM/APP_SECRET. Секрет не входит в UI, API responses, логи и screenshots.

Запрос подписывает точные bytes тела через HMAC-SHA256. Headers:
`X-CX-Tg-Timestamp` (UTC epoch seconds) и `X-CX-Tg-Signature` (hex digest).
Подпись связывает protocol version, timestamp, method, path и SHA256 body.
Backend проверяет её constant-time до DB/обработки сообщения. Timestamp имеет
окно ±60 секунд; Telegram update_id дополнительно дедуплицируется в БД.
Невалидная/отсутствующая подпись — 401, выключенный/неполностью настроенный
бот — 503. При выключенном боте остальные контуры продолжают работать.

Это исключение из AGENTS.md §10 «Не добавлять аутентификацию» предлагается
только для внутреннего транспорта, способного инициировать внешнюю доставку.
Пользователь разрешил такую service-to-service проверку. Это не разрешение
на реальные Telegram вызовы или автоматическое принятие HITL решений.

## Контракт и хранение после review

Зарезервирован API 1.5.20, после T-240 1.5.19. Существующие варианты inbound
сохраняются; новые service events несут Telegram update_id и language_code,
backend определяет стадию диалога. Обязательность update_id для новых events,
401/503 и правила дедупликации будут отражены в OpenAPI до реализации route.
Публичная `/track` сохраняет существующие границы приватности.

Зарезервирована миграция 0015, после 0014 history; quota ledger получит0016,
behavior0017; файл с отсутствующим parent не создаётся. Durable receipts и состояние
внешнего канала не должны откатываться вместе с банковским baseline. Старый
signal_id после reset нельзя автоматически привязать к новой строке с тем же id:
проверяется исходный tracking token и принадлежность чату, иначе новый диалог.

Все ответы и статусы сначала фиксируются в notifications. Доставку выполняет
backend worker, который держит существующий maintenance writer lease на весь
внешний вызов; tgbot использует aiogram 3 long polling для входящих updates.
Это сохраняет drain/reset boundary без передачи БД-credentials боту.
Для каждого чата действует ограничение 1 сообщение/с. Telegram ошибки
не останавливают симулятор. Неоднозначный исход sendMessage не обозначается
успехом и не обещает exactly-once: нужны явный failed/unknown receipt и политика
повтора, которые будут включены в окончательный review.

`/status`, `/lang`, привязка вымышленного кода клиента и manager callbacks
добавляются с typed validation и idempotency, без расширения полномочий LLM.
T-189 имеет отдельное review границы HITL перед подключением решений.

## Проверки и ограничения

До публикации реализации: fake aiogram session и HTTP transport, duplicate
updates, invalid signature/time/body, process restart, failed/ambiguous delivery,
1 сообщение/с, ru/en, disabled token, maintenance/reset, отсутствие токенов
в traceback/URL/logs. Будут выполнены штатные lint/test/CI и container checks.
Это перечень запланированных проверок, а не отчёт об уже прошедших тестах.

Реальный Telegram smoke потребует отдельного разрешения с конкретными chat_id,
текстами и числом вызовов. Разрешение GigaChat к Telegram не относится.

## Проверенный checkpoint transport/storage (не готовый сервис)

Source transport `0f9796a`, затем main8b composition `83bfd64`.
31 verifier/ASGI unit, 19 SDK/HTTP/license tests, licenses530+36 зелёные.
Добавленный CLI проверен отдельно:33bot tests8.13s, mypy5source/Ruff green;
`--offline` и отсутствие конфигурации дают0HTTP, secrets исключены из repr,
upstream SDK records очищаются от args/traceback, permanent failure не ack updates.
CLI пока не включён в Compose и не запускался с реальным token.

`T-121-runtime-schema-proposal.sql` — только SQL-предложение для будущей0015,
не миграция Alembic и не изменение рабочего контракта. Encrypted state/response,
durable inbound и stable notification delivery_key не ссылаются FK на resettable
public. Worker/delivery ещё не реализованы. На собственной
`cx_t121_transport_revision`5actual PostgreSQL checks passed1.87s:
повтор schema proposal идемпотентен, новый объект/connection читает ciphertext,
три concurrent duplicate исполняют handler один раз, изменение body/chat того же
update_id отклоняется, failure/missing response откатывают draft/receipt/side effect.
Это не OS-restart, restore/drain или actual delivery proof; эти проверки впереди.
