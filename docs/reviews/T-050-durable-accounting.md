# T-050 P2: operational quota и неизвестный расход

Операторская процедура восстановления и проверки штатного consumer:
[LLM-RECOVERY.md](../LLM-RECOVERY.md). Сверка operational state не заменяется
коммитом `.env`, dump или индивидуальных счётчиков в репозиторий.

Рестарт сервера и банковский restore больше не возвращают allowance. RPD считается по фактическим inference attempts, а не по успешным результатам benchmark. Ошибки/JSON repair/native-format retry/SSE не исчезают из учёта; отсутствие usage не превращается в 0. Пример: при cap 2 два POST исчерпывают allowance, третий не доходит до provider даже через другой alias, после рестарта или банковского restore.

## Что меняется

Миграция 0016 создаёт private `llm_runtime` (7 таблиц) без FK к восстанавливаемым public configuration/AR и private `llm_profiles.quota_uid`. Банковский dump исключает operational namespace; restore обновляет только derived compatibility columns до возобновления writers. Стабильный profile UUID сохраняется при rename/изменении лимита/restore той же конфигурации; новый профиль с повторно использованным numeric ID получает unknown quota. UUID/verifier/ciphertext не попадают в public API, settings JSON export или role snapshots.

Physical identity — private keyed verifier provider+credential (keyless local — endpoint). APP_SECRET rotation не сбрасывает счётчики: отказ до reviewed identity migration. Aliases одинакового physical key с одинаковыми active limits делят один ledger; разные active limits означают отказ, без min/max policy. Перед wire повторно проверяется выбранная current binding; explicit/implicit stored ID сохраняется и в Setup, deactivate/delete race не разрешает env fallback или metadata HTTP.

Короткая SQL transaction после ordered locks читает реальный UTC clock и атомарно резервирует key/profile daily attempt. Session lease сериализует неопределённость одного ключа, но SQL transaction через HTTP не держится. Reservation commit перед HTTP консервативно учитывает возможный запрос даже при потере процесса между commit/send; exactly-once DB+HTTP не заявлен. Повтор reservation UUID не разрешает повтор HTTP. OAuth/models/balance GET не являются inference RPD; новых таких HTTP не добавлено.

Validated cumulative usage сохраняет floor по delta один раз. Missing/invalid usage → unknown, interrupted stream сохраняет validated lower observation, а не обещает полноту. Budgeted unknown calls fail-closed до reconciliation; validated usage 0 допустим. После HTTP response без usage structured result не выдаёт фиктивный Usage 0, включая free/local. Stream не смешивает fallback после prefix и не отменяет consumer во время обработки чанка: absolute deadline ограничивает await setup/I/O/anext.

## Compatibility и operator flow

API 1.5.21: optional readonly `observed_tokens_floor`, `usage_known/source/as_of`, `requests_known/day`, nullable `tokens_remaining/requests_remaining`. `tokens_used` до reconciliation сохраняет legacy hint 17 и не означает полный расход; подтверждённый floor отдельный. После reconciliation поле показывает declared/app-observed floor. UI показывает Unknown/Неизвестно и использует server remaining, не arithmetic по hint. Provider-reported env tier нельзя выдавать за configured application cap; profile scopes независимы.

`python -m app.llm.accounting_cli status --profile-id ID --key-id ID` показывает key и общий profile UTC counters. Вместо key ID — explicit `--env-slot gigachat1|gigachat2|openrouter|local`; raw key в argv не принимается. Reconcile требует UUID, timezone-aware as_of текущих UTC суток, tokens/key requests/profile requests, `--confirm --reviewed-unknown-origin`; expired orphan требует отдельный acknowledge. Ниже подтверждённого wire floor/counter объявить нельзя. Audit сохраняет source/as_of, старые known/source, legacy token/day hints и явное подтверждение. Новый бюджет «с момента cutover» не вводится; регистрация не создаёт known 0.

Legacy hint не объявляется подтверждённым расходом: старый quota-health path мог присвоить ему limit. Известные canonical mirrors теперь только derived, benchmark не начисляет их снова. Forecast использует тот же operational profile day/server known state и дедупликацию aliases. Unbound env source остаётся явной legacy совместимостью; current saved aliases определяют key caps, profile limits применяются отдельно. Другие внешние клиенты/ручные инструменты не объявляются автоматически учтёнными provider-global usage.

## Recovery и границы

0016 forward-only; автоматический downgrade не удаляет operational history. Изменение schema/миграции меняет DB-contract fingerprint: старый baseline должен быть пересоздан штатным reviewed flow, его несовместимость нельзя обходить ручным изменением digest. Полный disaster-recovery backup должен сохранять `llm_runtime`; банковский baseline намеренно его не содержит. При потерянном/недоступном ledger или смене APP_SECRET budgeted вызов не получает silent allowance. Старый writer/binary, игнорирующий operational admission, не является поддержанным rollback. Если registry ciphertext не изменился, восстановление прежнего APP_SECRET возвращает прежнюю identity; осознанная ротация требует отдельной reviewed migration с сохранением UID/floor.

Нет новых цен, численных лимитов, банковских/refund/HITL политик или auth. Global OpenRouter budget loader/selected-key metadata guard сохранены. Существующий отдельно запускаемый T048 synthetic CLI — явное no-DB диагностическое исключение: 3 fixed models / 6 total HTTP / 128 output tokens, fixed text, прежний budget loader; не automatic server path и здесь не вызывался. Новая live acceptance P2 не заявлена. Credential boundary ограничена exact selected credential и поддержанными JSON decoded forms, не general DLP.

## Проверки и оставшаяся работа

Машиночитаемые результаты: [verification](T-050-durable-accounting-verification.json).

Frozen `bc405367ce770d0fd04ff7cff6ec488422595809`: unit 1669 passed / 18 skipped; integration 435 passed/4 skipped/1 failed (единственный `test_alembic_check_no_drift`: pre-release default `profile_code` в старой scratch БД); scenarios 43 passed/2 skipped; compliance 31 passed; frontend 354 passed; bot 43 passed. `make test` остановился на integration; оставшиеся targets выполнены отдельно на том же source. Это не полный green run.

В `6c8ae26` после обычного merge main 73425 исправлена идемпотентная нормализация default без потери истории, env provider tier перестал изображать configured app cap, восстановлена прежняя host/model классификация paid SDK candidate. Schema+ledger 52 passed (включая исходный Alembic check, повтор миграции и сохранение usage); targeted unit 110 passed. `make lint`: 362 frontend passed, Ruff 440 / mypy 285/backend и Ruff 12 / mypy 5/bot, OpenAPI 192/192; license gate 550+36; contracts 45 schemas/162 paths; production main+personal build прошёл. Полный unit 1669 passed / 18 skipped (49.91s). Final scoped coverage: 413 targeted tests passed (342.79s), 1100/1193 = 92.20% изменённых executable statements. Числа frozen source не приписываются новой версии.

Coverage на `6c8ae26` измерена относительно parent `3450afe`: stdlib tracing включает worker threads, отдельные worktree/БД. [Отчёт](T-050-durable-accounting-coverage.json) содержит file SHA и непокрытые строки, без runtime locals или credentials. Локальный второй полный 40-мин integration не запускался: финальный exact-head GitHub CI обязателен. Унаследованный root UI proof: 4 actual RU/EN×themes,101 table fingerprints stable,0 browser external/nonGET/errors, backend LLM/network Bomb markers absent; ссылки в T-050-quota-ui.md. Собственные regression tests используют только synthetic PostgreSQL/Fake HTTP; canonical venv/production/env values не изменялись.

T050 остаётся in_progress: отдельными пакетами ещё требуются queue 20s/per-profile limiter lock и main→fast→mock/fallback policy. Этот P2 закрывает durable accounting и прозрачность known/unknown, а не всю карточку. До merge обязательны точный final-head CI и human review API21/DDL16/внешнего API-budget policy по AGENTS §7. Техническое согласование реализации не заменяет пользовательский financial approval.


Композиция parentT121 b85d377:head34178fd, дерево идентично frozenab6a5eb. Parent теперь прямой предок, diff PR53файла. Проверка owners с явным --allow-cross прошла; L1/L2/L3/L4/L5 разрешены поручением пользователя, отдельный API21/DDL16/финансовый review ещё требуется. Runtime/coverage evidence не изменились.

## PR188 CI: source-qualified latency triage

Exact d99b856: shard3 содержит454 passed/1 skipped и единственный Trace fanout latency failure305.9>300ms. Парные неизменённые локальные тесты P2/parent прошли55.0/56.5ms; hot paths byte-identical, runtime fix не заявлен, порог не снижен. [Диагностика и source-qualified samples](T-050-ci-fanout-latency.md). После обычной композиции main/parent требуется новый exact-head CI. API21/DDL16/external-budget policy пользователь одобрил в родительском review PR188; эта диагностика не меняет согласованную политику.
