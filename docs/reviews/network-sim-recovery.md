# Восстановление tick после разрыва PostgreSQL

## Причина и граница

Первопричина остановки стенда в 08:33 не установлена: доступный журнал не содержит ошибки соединения tick. Обычная ошибка `_loop` сама по себе не выключает локальные часы; `running=true` в БД не доказывает намерения продолжать после ручной Pause/Stop. Это исправление не включает часы по состоянию БД и не обещает устранить неизвестную причину того случая.

После подтверждённого разрыва соединения действующий автономный loop может переподключиться только при сохранении собственного task/run и поколения локального намерения. Новый connect ограничен `connect_timeout=3`, вся readonly проверка — 8 секундами; backoff 2 секунды отменяется и не держит Python lock. Проверка не вызывает `load_state`, не меняет статус запуска и не записывает данные.

Автоматический повтор разрешён только при точном совпадении durable PRE: current run, sim time, day, seed, raw RNG и running/status. Перед эффектами повторного tick этот же PRE повторно проверяется под `sim_state FOR UPDATE`; это закрывает гонку между readonly проверкой и новым writer transaction. Восстанавливаются исходные stats и legacy pending/faults; новый World читает native Team journal. Генераторы, формулы, финансовые лимиты и HITL не меняются.

Повторяемые ошибки: psycopg connection/interface errors без terminal SQLSTATE, класс 08 и PostgreSQL shutdown/recovery 57P01/57P02/57P03. Ошибки с явным terminal SQLSTATE (включая аутентификацию, конфигурацию и SQL) не повторяются как reconnect. OperationalError без SQLSTATE при отсутствии/закрытии соединения остаётся неоднозначной transport-ошибкой: проверка может повторяться до ручной остановки; текст исключения для классификации не разбирается. Tick использует PostgreSQL и локальный TextGen; engine retry не инициирует provider HTTP. Платные unknown-attempt barriers агента и внешняя доставка не меняются.

## Неизвестный COMMIT и ручное управление

POST или другой durable owner/time/RNG не принимаются за PRE. Loop останавливает локальные часы, сохраняет БД и выдаёт диагностический transition без DSN, SQL, payload и текста исключения. Последующие controls получают существующий `StaleSimulatorError` с указанием перезапустить backend **без reset**, затем явно возобновить текущий запуск. Одного нажатия Resume на старом процессе недостаточно. Не выполняются автоматический rollback истории, adoption POST или создание нового run.

Pause/Stop меняют поколение намерения до I/O и отменяют connect/backoff. Они не запускают часы при возврате сети. Даже отмена проверки неизвестного COMMIT оставляет PRE guard для последующего direct tick. При недоступной БД сам control может завершиться ошибкой; локальное намерение остановки сохраняется.

## Проверка и откат

Регрессии используют отдельную PostgreSQL 16, Mock и запрет внешнего egress: настоящий `pg_terminate_backend` после native uncommitted operations; PRE reconnect с legacy pending/Team и behavior policy; настоящий COMMIT с потерянным ack; Pause/Stop во время connect/backoff; foreign pointer/status/RNG; конкурирующий native tick после PRE; отмена неизвестного COMMIT до классификации; terminal auth.

Полные fingerprints таблиц public/langgraph/llm_runtime/channel_runtime подтверждают отсутствие записей при проверке/отказе. Sequences не откатываются PostgreSQL и могут иметь пропуски после отменённой попытки. Это не подтверждение сетевой отказоустойчивости реального провайдера/Telegram.

Откат — возврат только кода после штатной остановки backend; схема и история не меняются. При неизвестном COMMIT сначала сохранить backup и перезагрузить backend без reset, не возвращать старые sim time/RNG вручную. Включение на основном стенде требует отдельного review финансовой transaction boundary.

Проверено на frozen source от main `957d1d7`: 34 native PG tests PASS (17 новых и 17 соседних commit/control), 225.39 s. Старый engine даёт причинный RED на lost COMMIT acknowledgement (loop не завершается безопасным отказом); новый проходит этот же сценарий. Новые executable statements: 110/114 = 96.49% (stdlib trace + innermost AST statement spans по diff; это не branch/full-project coverage). Ruff check/format, targeted mypy engine и `git diff --check` PASS. Own PG остановлен, blocked egress events 0. Полный combined-project gate/CI и rollout этим target не заменяются.
