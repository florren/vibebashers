# Перечитывание первичного seed установщиком

## Причина дефекта

`install.sh` поднимает backend и ждёт health до запуска seed. `Simulator.load_state()` на пустой БД создаёт `sim_state` с пустым current pointer и сохраняет `run_id=None` в памяти. Первичный seed затем создаёт completed baseline и записывает его pointer в БД. Прежний установщик объявлял успех, хотя API продолжал возвращать `None`; штатный Start закономерно отклонял устаревшую память.

Защита `StaleSimulatorError` сохраняется без изменений. Engine не получает autoload, retry или новую логику Start.

## Изменение жизненного цикла

После успешного seed новый `/scripts/install_seed_state.py` сравнивает память существующего `/api/sim/state` с PG current pointer через отдельное read-only соединение. Совпадающий pointer означает no-op, в том числе при активном World, pending signals и агенте.

Только явный memory `None`, остановленный симулятор, completed baseline в БД, `running=false` и отсутствие активных agent runs/pending signals разрешают exit3: установщик один раз выполняет `docker compose restart --no-deps --timeout 120 backend`. Отсутствующий API field, неизвестный run и прочие mismatch завершаются явной ошибкой без автоматического restart. После restart выполняется health с общим бюджетом 120 секунд, ограничивающим также curl и sleep; затем повторяется сравнение pointer. HTTP state и подключение к PG ограничены пятью секундами, SQL statement — пятью секундами. Состояние БД не записывается helper.

Ненулевой seed, ошибка сравнения, restart, health или повторный mismatch не допускают сообщения о готовности, personal/Tuna-этап. No-op seed с согласованной памятью не прерывает активный World. Проверка — снимок на момент сравнения, она не заменяет организационное отсутствие конкурентного управления во время установки.

Полный backend restart также выполняет прежний application startup, включая существующий идемпотентный ABS backfill из уже исправленного main; этот пакет не меняет его алгоритм. Native fingerprint assertion ниже относится к `Simulator.load_state()`, а не выдаётся за проверку отсутствия всех startup effects.

Helper включён существующим `COPY scripts/ /scripts/` в backend Dockerfile. API, DDL, деньги, HITL и simulator guards не меняются.

## Проверки

На прежнем installer: **7 failed/1 passed** в новых lifecycle shell-regressions. Исправленный targeted installer набор: **51 passed**. Проверены fresh reload order, same-pointer no-op, seed/helper/active mismatch/restart/health/persistent mismatch failures, malformed API и защитные условия. Отдельный настоящий молчащий HTTP endpoint на собственном динамическом loopback-порту подтвердил ограничение health budget.

Native PG regression: **1 passed, 15.66s**. Старая память действительно сохраняется до настоящего seed CLI (200 синтетических клиентов), `check_state` читает настоящую PG readonly и получает old/new `Simulator.state_dict()` через явно заменённый HTTP transport. Старый Start даёт `StaleSimulatorError`; новый Simulator после load совпадает с persisted baseline, а hashes всех таблиц четырёх схем, часы и raw RNG до Start сохранены. Далее настоящий Start запускает штатный World task, совпавшее running-состояние не прерывается, native ticks/step дают операции и сигналы. Собственный PG остановлен, primary не использован.

Полные обязательные проверки этого commit выполняются отдельно после фиксации source; их результат публикуется в PR. Live LLM, Telegram, primary seed/reset/restart в этой проверке не запускались.

## Откат и ограничения

Откат installer не меняет БД, но возвращает исходный риск stale memory после первого seed. До применения исправления требуется контролируемый backend restart после успешного первичного seed; повторный reset для этого не нужен. Restart может ждать до 120 секунд graceful shutdown и затем ещё до 120 секунд readiness. Начальный существующий pre-seed health loop этим пакетом не изменён.
