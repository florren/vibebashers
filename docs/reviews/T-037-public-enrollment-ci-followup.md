# T037: исправление public enrollment после CI PR195

На parent2921e851 CI показал девять failures personal_execution и один failure fixture behavior rollback/retry. Локально до исправления воспроизведены две первичные причины: public_context создавал отдельный live run без team.runtime_started, а fixture «пустого legacy run» удалял behavior marker, оставляя team journal event.

## Узкая коррекция

Новый public run получает штатный ensure_runtime в прежней creation TX, до сохранения конфигурации/первых входов. Public run остаётся отдельным live run; current bank pointer, bank clock, private queue и настройки behavior не меняются. Повтор public_context использует существующий run и не создаёт marker задним числом. Планless legacy public history по-прежнему даёт TeamPlanError без RNG/state/action effects.

Fixture теперь сначала строго подтверждает единственный ожидаемый team.runtime_started, затем удаляет только его вместе с behavior marker для моделирования действительно пустого legacy run. Исходные clock/RNG/stats/rollback/retry assertions сохранены; production legacy guard не изменён.

## Проверки

- До исправления: 2 failed,12.38s — новые public creation marker assertions и прежний behavior rollback/retry точно воспроизводят причины CI.
- После исправления: **12 passed,89.88s** — все девять исходных personal_execution cases, новая atomic public creation/rollback/idempotency/new-connection проверка, новый legacy public refusal и прежний behavior marker rollback/retry. Лог `/tmp/t037-public-enrollment-after.log`.
- Существующие enrollment/legacy/autocommit/concurrency guards: **5 passed,29.71s** (`/tmp/t037-public-enrollment-guards.log`); транзакционный отказ и конкурентная идемпотентность сохранены.
- Ruff/format трёх затронутых Python файлов и mypy public producer — green; diff whitespace check — green.

Данные только собственной scratch PG16 cx_team_plan_revision; реальные LLM/Telegram/production не использовались. Исторические full/coverage результаты T037 остаются привязаны к прежним sources; новый producer path ими не покрывается. Пользователь уже подтвердил неизменённую event/journal границу PR195 при green CI и parent193. Exact final CI остаётся обязательным перед merge; receipt0019/runtime не входят в это исправление.
