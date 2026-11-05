# Tick COMMIT: cancellation после результата durability

## Причина и минимальная граница

Полный gate обнаружил failure shutdown после настоящего SIGKILL/recover:
`_park_runtime → sim.control('pause') → _require_current → StaleSimulatorError`.
Recovery тела уже завершилось; ошибка возникла при завершении lifespan.

Подтверждённое окно: PostgreSQL уже выполнил COMMIT, но coroutine psycopg ещё не
вернулась в `_step_chunk_locked`. Прежний `_stop_loop` отменял sim-loop в этом
окне. Обработчик BaseException восстанавливал memory clock/RNG к t0, а rollback
уже не мог отменить зафиксированный DB tick t1. Последующий stale guard честно
отказывал, предотвращая перезапись t1 прежними часами.

Теперь только `conn.commit()` tick выполняется отдельной Task через
`asyncio.shield`. Caller cancellation, включая повторную, не отменяет commit task.
Tick дожидается результата. После успешного COMMIT cancellation пробрасывается
вне transactional rollback-ветки: time/RNG/stats уже соответствуют сохранённым
эффектам. Если сам commit завершился ошибкой, прежний rollback memory/DB сохраняется;
ошибка хранения имеет приоритет над отложенной cancellation. Вся оставшаяся часть
незавершённого tick по-прежнему отменяется и откатывается сразу.

`_stop_loop`, lock ordering, current/time/RNG/status guards не меняются.
Прямой cancel шага/API получает ту же защиту, что Stop/Pause/shutdown.
Нет общего drain тяжёлого tick, автоматического reload, stale override и новых retry.
Защита transient: DDL и persisted flags не добавляются.

Суммы, формулы, API/DDL, caps и HITL не меняются. История не переписывается.
Подтверждение cancellation может отложиться до завершения уже начатого COMMIT,
что сохраняет атомарность tick и согласованность memory с его durable результатом.

## Точные пределы гарантии

Shield охватывает только COMMIT в `_step_chunk_locked`: обычный sim-loop,
прямой step, target/jump и prepared step через этот метод. Отдельные COMMIT
control start/resume, baseline и prepare этим diff не защищаются.

После успешного durable commit отмена может прервать `_publish_tick`:
гарантируется согласованность DB и memory time/RNG/stats, а не exactly-once
WebSocket publication. Lost ACK или transport-unknown результата COMMIT не
превращаются в выдуманный success; сохраняются существующие ошибки и stale guards.
Тесты commit errors вводят синтетическую ошибку до durability и не моделируют
восстановление неизвестного серверного commit outcome.

Review распространяется на эту tick boundary, а не на все транзакции приложения.

## Проверки

Детерминированный actual PostgreSQL тест блокирует возврат coroutine после
настоящего COMMIT и запускает pause/stop. На прежнем producer оба пути дают
ровно исходный StaleSimulatorError engine.py:181 (2 failed). После fix оба пути
сохраняют t1, native RNG, один tick и правильные paused/stopped/running=false.
Дополнительно подтверждён RED прямого cancellation после durable COMMIT:
прежний producer откатывал memory к t0. Финальный regression проверяет также
повторный cancel без отмены inner commit, failed commit с/без caller cancel,
полный rollback до durability и успешный следующий tick.
Не используются задержки как способ попасть в основную гонку; окно управляется Events.

Дополнительные PG регрессии: stale guards, control/tick serialization,
target/cancel/RNG, full worker/end/lock ordering, настоящий SIGKILL/restart.
Unit shutdown/baseline: 15 passed на финальном general producer.
Адресный native набор: 9 passed (pause/stop/direct/repeated cancellation,
ошибки commit, partial rollback, worker lock ordering).
Changed-statement execution: 11/12 = 91.67%, stdlib sys.settrace + bytecode/AST;
6 native tests passed. Это не branch coverage и не полное покрытие проекта.
Ruff format/check и strict mypy engine passed.
Финальный subsystem PG набор: 42 passed за273.36s, включая настоящий SIGKILL/recover/graceful restart.

Все проверки выполняются в отдельном freeze-resume-diagnostic и собственном
PostgreSQL. Реальных LLM/Telegram вызовов, primary/fullgate DB writes нет.

## Откат

Revert возвращает прежнюю cancellation гонку. Схемы и сохранённые данные не
требуют downgrade. При проявлении stale guard следует штатно загрузить актуальный
контроллер, а не переписывать clock/RNG вручную.

Пользователь подтвердил эту tick cancellation границу ответом
«Подтверждаю после зелёного CI». Условие итогового CI сохраняется.
[Измерение новых statements](freeze-sim-stop-commit-coverage.json): 11/12
(91,67%); это не branch/full-project coverage.
