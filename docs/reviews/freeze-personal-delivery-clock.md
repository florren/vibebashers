# Personal chat: время доставки в истории

## Дефект и исправление

`GET /api/personal/messages` возвращал `answers[].at` из
`notifications.created_at`, то есть PostgreSQL `now()` начала транзакции.
Если транзакция обработчика началась до получения нового вопроса, это время
предшествует `signals.received_at`, хотя фактическая доставка `sent_at` происходит
после вопроса. PersonalChat сортирует сообщения по wall clock и показывал ответ
перед вопросом. Исправленная producer clock в notify_client сама по себе эту
ошибку consumer не устраняла.

Теперь существующее поле `answers[].at` использует
`coalesce(notifications.sent_at, notifications.created_at)`. Journey уже
использует sent_at. DTO, схема, статусы и stored history не меняются.
Никаких GREATEST с временем вопроса, переписывания timestamps или выдуманной
доставки нет. У legacy sent/delivered без sent_at сохраняется прежний fallback;
историческая причинность таких строк этим исправлением не доказывается.
Queued/failed/unknown/suppressed в историю ответов по-прежнему не попадают.

Размеры, формулы, лимиты и HITL не затронуты. Это read-only projection, но смысл
существующего at уточняется с creation на фактическую delivery там, где она
известна. API/DDL/version bump не требуется: тип и форма ответа прежние.

## Проверка

Нативный RED: настоящий personal POST/GET и notify_client на PG16. Транзакция
обработчика открывается до POST вопроса, затем доставка выполняется в ней.
`created_at = transaction_start < question.received_at <= sent_at`.
Endpoint ошибочно возвращал created_at:1failed10.54s.

Тест `test_personal_display_chronology.py` проверяет все шесть эмулируемых
каналов, неизменный фильтр недоставленных статусов и fallback legacy delivered
без sent_at. Сеть провайдеров и Telegram выключена, реальные клиенты не участвуют.

- GREEN/composition:26passed185.17s:6 новых channel/legacy/filter случаев,
  существующие personal API,15 channel chronology и два twin child graph случая.
- Отдельный instrumented прогон:6passed47.07s. Две изменённые executable producer
  строки241(SQL) и248(response projection) выполнены:2/2=100%. Это stdlib line
  trace с включёнными worker threads, не branch/full-project coverage. SQL literal
  внутри await не считается новым AST statement start, поэтому этот метод явно
  включает изменённую executable SQL строку.
- Ruff check/format и git diff --check passed.
- Exact personal.py SHA256:
  aec37946f973223561fc95122252eb0f09456f463e259c936323a1a58ddbbf27.

Доказательства: .runtime/freeze-sim-control-personal-display-{red,green,coverage}.log,
.runtime/freeze-personal-delivery-coverage.json. Все собственные PG остановлены.
Изменение root checkout и primarybank/ledger не выполнялось. Actual browser после
этого producer patch отдельно не запускался; frontend не менялся, существующие
PersonalChat DOM tests проверяют microseconds и RFC3339 offsets.

## Откат и границы

Откатить только projection в app/api/personal.py; миграций и восстановления БД
не нужно. Откат возвращает ошибочное создание timestamp для новых доставок.
Сортировка UI сохраняет UTC offsets и PostgreSQL microseconds; равные timestamps
не являются доказательством порядка отдельных внешних доставок. Старые реальные
unknown/delivery receipts не изменяются. Полного покрытия всех возможных
межканальных расписаний этот набор не утверждает.
