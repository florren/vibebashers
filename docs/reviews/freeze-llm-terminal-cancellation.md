# Terminal inference bookkeeping при повторной cancellation

## Проверенный дефект

Ограниченный настоящий native bench получил timeout через30006ms, после одного
inference HTTP. В private ledger attempt остался `reserved`, error_kind/finished_at
не были записаны. Это не успешный ответ и не подтверждённый нулевой расход.
Последующий read-only запрос подтвердил reserved после deadline.

У ProviderChain (`wait_for`) и native KeyScope (`asyncio.timeout`) собственные
близкие deadlines. Первая cancellation прерывает HTTP и начинает
`Ticket.unknown`; вторая может прервать его DB bookkeeping. Детерминированный
actual PostgreSQL regression воспроизводит ровно reserved/error_kind=NULL после
двух отмен. Настоящие native10s/30s tests воспроизводят обе cancellation без
изменения production timeout и без внешнего HTTP.

## Изменение и сохранённая policy

Только terminal `Ticket.unknown` после уже выданного Ticket запускается в
отдельной Task. `asyncio.shield` защищает её от повторной cancellation caller.
Leased connection/credential scope остаются открыты до завершения cleanup task.
Затем исходная cancellation/ProviderError пробрасывается как прежде; если новая
caller cancellation пришла во время cleanup после ProviderError, она тоже
пробрасывается после DB outcome, а unknown сохраняет первоначальный error_kind.
Self-cancelled child распознаётся отдельно и не вызывает бесконечного цикла.

Для terminal DB cleanup введена фиксированная неплатная grace3s. Она ограничивает
ожидание bookkeeping, а не продлевает inference deadline10s/30s, не создаёт
повторных HTTP и не повышает денежный/token/RPD budget. Запрос usage уже завершён
или отменён до этой grace. Если cleanup завис/не удался, сохраняется existing
fail-closed reservation/pending и штатная ошибка/log, а не выдуманный known/zero.
Cleanup Task полностью awaited до освобождения connection и не убегает в фоне.

Успешно observed known и reconciled attempts не переводятся в unknown. Ранее
подтверждённый расход и daily counters не уменьшаются. Правила reconciliation,
orphans acknowledgement, caps, DDL/API и выбор провайдера не меняются.

## Точные ограничения

Это исполнение ранее утверждённой unknown policy, только после выданного Ticket.
Crash/SIGKILL, durable admission до получения Ticket, потерянный ACK или недоступная
БД всё ещё могут оставить orphan. Они продолжают блокировать новые budgeted calls
и требуют явного operator review/reconciliation; diff их автоматически не очищает.
Существующий настоящий reserved attempt не переписывался и не исправлялся тестами.
DB bookkeeping может добавить до3s ожидания после inference cancellation плюс
штатное завершение cancellation/rollback драйвером; новых paid requests в это время нет.

## Проверки

- RED: actualPG repeatedcancel → reserved вместо unknown,1 failed.
- Native10/30s nested deadlines: обе отмены подтверждены, после cleanup unknown,
  следующий вызов заблокирован до HTTP; численные native timeouts не изменены.
- Single/double cancellation; observedknown остаётся known; DB transaction failure;
  caller cancellation после ProviderError и normalbody; hang3s и selfcancel;
  orphan остаётся fail-closed, cleanup task завершена до выхода scope.
- Changed-statement execution22/22=100%,10 native cases passed; stdlib trace/AST,
  не branch coverage и не полное покрытие проекта.
- 87 unit SDK/Giga balance/chain/timeouts passed; strict mypy accounting passed;
  Ruff check/format и diff-check проверяются перед commit.
- Финальный native accounting/Giga/OpenRouter matrix:76 passed за97.64s.

Все записи тестов выполнялись в отдельном `freeze-accounting-cancel-diagnostic`
и собственном PostgreSQL; coverage имел отдельный immutable source archive и БД.
Primary использовалась только для read-only диагностики конкретного attempt.
Никаких реальных inference/retry, counter reset или production data writes.

## Откат

Revert возвращает cancellation окно; сохранённые reservations/counters остаются
нетронутыми. DDL downgrade не нужен. Возврат к работе после unknown/orphan — только
штатный operator workflow с проверенной статистикой провайдера, без ручного zero.
