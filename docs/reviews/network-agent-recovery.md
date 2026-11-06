# Восстановление Agent LISTEN после разрыва соединения

## Граница изменения

`process_signal` сериализует создание нового AgentRun по row lock `signals.id`.
Проверка существующего прохода и INSERT AgentRun выполняются в одной короткой
транзакции. Claim завершён до `load_deps`, графа и любого HTTP: внешний вызов не
держит блокировку сигнала. Обычный вход сохраняет прежнюю возможность явного
повтора `failed`.

Внутренний режим `new_only` нужен только для catch-up: он повторно проверяет
`status=new`, отсутствие **любого** AgentRun и текущий активный запуск под тем же
claim. Поэтому два listener/process caller не создают два AR; `failed`,
`awaiting_human`, незавершённый AR и прежний проход с unknown usage не становятся
разрешением повторить платный запрос. HTTP/OpenAPI/DDL не меняются.

Пропуск входа откатывает собственную транзакцию или SAVEPOINT. При вложенном
caller transaction ранее сделанные caller записи сохраняются, а приобретённый
claim освобождается; пропуск не делает чужой COMMIT.

## LISTEN и catch-up

LISTEN регистрируется до startup recovery и поиска пропущенных сигналов.
Обрыв/неудача подключения приводит к reconnect с задержкой 1, 2, 4 … до 30 секунд;
подключение ограничено 3 секундами. После подключения listener обрабатывает окна
NOTIFY до 2 секунд/20 уведомлений и снова проверяет durable очередь. За один
поиск добавляется не более 20 проходов с учётом уже активных `_by_signal`, с
кооперативным yield. Сессия здорового LISTEN при этом не пересоздаётся.

Catch-up требует одновременно `enabled`, локальные `sim.clock.running` и тот же
run, `sim_state.running`, текущий run и `sim_runs.status=running`. PostgreSQL-флаг
сам по себе не включает симуляцию. После ручной Pause/Stop новые catch-up entries
не допускаются; уже допущенный проход сохраняет прежнюю политику завершения.
Старые исторические seed/mock источники исключены прежним фильтром.

Если первичное startup recovery оборвалось из-за PostgreSQL
`OperationalError`/`InterfaceError`, оно повторяется после нового LISTEN. Его
существующий checkpoint/AR протокол не расширяется. Legacy/corrupt checkpoint и
другие ошибки остаются диагностикой для ручного разбора, без бесконечного replay.
Catch-up не возобновляет уже созданные orphan AR; их штатный checkpoint recovery
остаётся отдельной границей.

## Платные API и другие процессы

Новые HTTP retry, смена caps, reconciliation или новый app-origin не добавлены.
Существующий private ledger сохраняет unknown/reserved fail-closed. Изменения
касаются доставки hints и атомарного normal entry, а не платёжной политики.
Providers, frontend WS, Telegram и Tuna этим diff не меняются. Tuna 0.39.0 уже
имеет native reconnect; новый watchdog или внешний probe не выполнялся.

## Проверки и откат

До изменения два независимых PG-соединения воспроизводили race normal entry
(autocommit false/true): **RED 2 failed**. Тесты используют отдельную PG и
синтетические провайдеры, без внешнего HTTP.

Финальный targeted native/unit набор: **32 passed**; затем набор с ближайшими
полными Mock-графами и native provider/accounting recovery: **39 passed**.
Проверены independent connection normal/catch-up races (autocommit false/true),
свободный rowlock до load_deps/графа, ANY-AR skip, ручной failed retry,
Pause/foreign owner, вложенный caller SAVEPOINT и реальный PostgreSQL
LISTEN disconnect → пропущенный NOTIFY → reconnect → ровно один AgentRun.
Ruff check/format — PASS; mypy — PASS (331 source files).
Changed-statement execution: **78/91 (85,71%)**, stdlib trace/AST, не branch coverage.
Полный composition gate выполняется отдельно; результат полного проекта этим
документом не заявляется.

Откат — возврат source-изменения при остановленных app writers; DDL и преобразования
истории отсутствуют. Откат возвращает прежний LISTEN gap/race и не должен очищать
операционный ledger или исправлять исторические AgentRun автоматически.
