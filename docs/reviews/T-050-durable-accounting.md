# T-050: durable accounting, подготовка P2

## Проверенный foundation checkpoint

Основа private ledger добавлена отдельно от подключения провайдеров. На этом checkpoint production HTTP admission не переключён: `accounting.service()` ещё не вызывается провайдерами. Карточка T-050 остаётся `in_progress`; API1.5.21, operator CLI, wire hooks, публичные остатки и финальные full/coverage/CI ещё впереди. Нельзя считать этот checkpoint исполнением всей карточки или окончательным финансовым approval.

Источник — миграция0016 `contracts/db/migrations/0016_llm_accounting.sql`; mirror/schema/models генерируются штатно. Namespace `llm_runtime` исключён из банковского pg_dump и не имеет FK к восстанавливаемым public configuration/AgentRun. Данные inference attempts, неизвестный расход и reconciliation переживают банковский restore. Downgrade forward-only: operational counters не удаляются автоматически. Отмена не возвращает reservation. Сбой между commit reservation и отправкой HTTP консервативно считается возможной попыткой; exactly-once для DB+HTTP не заявлен.

Physical credential определяется private keyed verifier; credential bytes/промпты/ответы в ledger не записываются. Смена APP_SECRET приводит к безопасному отказу до reviewed identity migration. Canonical aliases одинакового physical key с одинаковыми действующими лимитами делят один ledger. Конфликтующие active limit configurations блокируют admission: min/max policy не вводится. Выбранная explicit binding повторно проверяется до admission; fallback к env не добавлен.

`llm_profiles.quota_uid` — private UUID конфигурации, включённый в opaque config fingerprint. Он сохраняется при rename/правке лимита и банковском restore той же конфигурации. Новый профиль, даже с повторно использованным числовым ID, получает новую unknown quota identity. UUID отсутствует в public profile API, settings JSON export и AR/SimRun role snapshots. Private банковский dump содержит этот configuration UUID для корректного restore; operational namespace в dump отсутствует. Public config ID разрешается во внутренний quota scope под configuration lock.

Краткая транзакция после ordered configuration/profile/credential locks читает реальное `clock_timestamp()` в UTC, проверяет allowance и атомарно резервирует key/profile daily attempt. Session lease сериализует неопределённость расхода одного physical key между процессами; сетевой вызов не держит SQL transaction. Повтор UUID reservation не разрешает повтор HTTP. OAuth/GET модели/баланс пока не подключены и не выдаются за inference RPD.

Missing usage не является0. Validated cumulative observations прибавляют delta один раз; известный floor сохраняется при stream failure/повторе observations. Незавершённая reservation требует истечения deadline и отдельного acknowledge в reconciliation. Операционное начало не создаёт known0: budgeted unknown calls fail-closed. Legacy `tokens_used` сохраняется как `legacy_tokens_hint`, а не подтверждённый wire floor: старый health path мог присвоить ему размер limit. Reconciliation требует явного `acknowledge_unknown_origin`, source=`operator_declared_app_usage`, timestamp текущих UTC суток, UUID и не уменьшает подтверждённый app-observed floor. Audit сохраняет прежние source/known/hint и явное подтверждение оператора. Автоматический новый бюджет «с момента cutover» не вводится.

## Проверки foundation

-15 synthetic PostgreSQL integration tests:15 passed/20.63s; `/tmp/t050-accounting-foundation-pg-final.log`.
-61 targeted profile/security/role/baseline unit tests:61 passed/5.74s; `/tmp/t050-accounting-profile-unit.log`. Первый sandbox TestClient run завис и был адресно остановлен; результат относится к полному повтору с рабочим TestClient.
-Ruff format/check и strict mypy для accounting/base/run_profiles прошли.
-`make sync-contracts` с собственной scratch generation DB:99 SQLAlchemy models, API19 без feature API changes.

Проверены actual pg_dump/restore (quota остаётся потраченной, quota_uid сохраняется), ID reuse/rename/current limit, config fingerprint без counters, API/export/AR negative projections, parallel connections с cap2, одинаковые/конфликтующие aliases, UTC date после реального lock waiter, idempotency, unknown usage, orphan deadline, provenance и late cumulative observations. Все credentials synthetic, сервисы внешних LLM/Telegram/email не вызывались. Собственная БД `cx_quota_ledger_revision`, собственные venv/worktree; production и canonical venv не изменялись.

Обязательное review готового API21/DDL16/policy diff по AGENTS §7 остаётся за техлидом/пользователем до merge. Эти технические согласования не заменяют финансовый approval. Последующие composition/main changes требуют source-qualified проверки.
