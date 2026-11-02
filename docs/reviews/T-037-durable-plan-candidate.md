# T-037: native план до первого действия — кандидат совместимости

## Воспроизведённая причина

На родителе `9bba1d9` настоящий tick сохранял global RNG и часы, но `_build_plan` до первого due действия сохранял решение только в RAM. Fresh Simulator восстанавливал часы/RNG, но `team_emulator.plans` был пуст: targeted regression завершился ровно missing-plan assertion (1 failed, 8.82 s). Это отдельный gap T037; прежний T161 bounded OS-proof его не покрывал.

## Конкретное изменение

Новый typed event `team.plan` фиксирует incident/team/version и полный план сразу после случайного выбора в **той же caller tick TX**, где сохраняется shared RNG. План — решение планировщика; это не фиктивный take/progress_report и не новый артефакт команды. Due times, random draws и вероятности не меняются. Native load не делает random draws. Initial plan и последующие реальные action snapshots сохраняют `paused_after_clarify`/`resumed`; snapshot записывается после фактического изменения этих флагов.

`team.runtime_started` отмечает enrollment версии 1. Новые runs получают его в `create_run` TX после behavior marker и до публикации нового current pointer. Legacy run может enroll только при отсутствии unresolved planless incidents и release с неизвестным планом/pending regression. Неизвестный старый pre-action план не выдаётся за новый и не reconstruct через новый draw. Существующий action-only legacy blob читается как сохранённый факт. Неполные lineage/version/aware dates, дубликаты и неверный marker дают actionable `TeamPlanError`, не автоматический repair/close.

Enrollment сериализуется частным transaction advisory key лишь при отсутствии marker. Builder одного incident также использует частный advisory key; incident row lock через LLM не добавляется. Конкурирующие Sim owners сохраняют существующие current/clock/RNG fences. Повторный builder читает committed native plan перед любым draw.

Изменены только additive event contracts/envelope и их штатно сгенерированные модели; DDL, API, profile snapshots и финансовые формулы не меняются. Общий WS router оставляет события в семействе `team`/топике `sim`; runner обрабатывает release по точному `team.release`, поэтому journal не объявляется выполненным действием. Старые action consumers сохраняют прежний формат, добавлены только state flags в открытом JSON payload.

## Обязательный human review

Root технически разрешил подготовить/проверить этот кандидат и enrollment marker. Это **не пользовательское одобрение** нового event-contract и отказа для legacy active runs. Final compatibility review по конкретному diff обязателен до merge/activation. Не выполнялись production restore, исправление старых данных или внешние вызовы.

## Проверки конкретного runtime source

- Исходные unit team и первая actual-PG recovery проверка: 9 passed, 12.10 s.
- Расширенный первый PG набор: 12 passed, 75.62 s; далее изменена только внутренняя serialization граница и добавлены проверки.
- Расширенный Sim/atomicity/SLA набор: 49 passed + 1 fixture F, 143.98 s. F был сравнением строк одного timestamp в `+03:00` (план) и `+00:00` (PostgreSQL); actual child уже проверял aware datetime equality. Exact plan/RNG/исходный clock равны.
- После исправления только timestamp assertion: actual OS SIGKILL/restart + autocommit refusal + неизвестный legacy release: 3 passed, 20.66 s. SIGKILL −9; полный план/RNG без нормализации, take выполнен в native due instant. Child environment — явный whitelist без provider credentials; нет LLM/HTTP.

Последующий exact runtime повтор исправил false autocommit refusal: действительный `INTRANS` внутри explicit `conn.transaction()` поддерживается; metadata readers используют `tuple_row` независимо от factory caller `dict_row`. Пять исходных lifecycle assertions не менялись.

- Final основной PG/OS/lifecycle/baseline restore/reset-day/teams набор: **43 passed, 223.01 s** (`/tmp/t037-final-coverage-targets2.log`).
- Stale builder без redraw и два повреждённых legacy snapshots: **3 passed, 21.94 s** (`/tmp/t037-supplemental-coverage.log`).
- Synthetic PG16 dump → отдельный disposable clone → native load/первое действие: **1 passed, 12.64 s** (`/tmp/t037-dump-clone-proof-final.log`). Первый вариант fixture после clone ошибочно оставлял обычные generator интенсивности, поэтому продолжение делало настоящие generator draws; reference и clone теперь явно имеют одинаковую controlled zero-generator workload. До продолжения native plan/RNG уже совпадали. Это не изменение producer RNG/clock.
- Final full unit: **1727 passed / 18 skipped, 54.02 s** (`/tmp/t037-final-full-unit.log`); все skips — существующие schemas без examples, новые две schemas имеют проверенные examples. Ранее первый ошибочный запуск без explicit scratch URLs остановлен, его результат не учитывается.
- Changed-executable **line** coverage: **131/131, 100%**, stdlib trace union двух успешных прогонов с проверкой одинаковых source SHA256. Это не branch coverage; [данные](T-037-durable-plan-coverage.json).
- Ruff/check+format: 455 файлов; mypy: 295 модулей; contracts: 47 схем / 162 OpenAPI paths; license gate: 550 distributions. Новых зависимостей нет.

Aggregate OS/clone evidence и точные source hashes: [proof](T-037-durable-plan-proof.json). Дополнительные scenarios/compliance запущены sequential; результат пока не заявлен. Full composition CI/human review остаются обязательными.

Clarify/resume восстанавливаются из actual clarify action и actual incident status/progress facts; позднее ручное возвращение `in_progress` не теряется до следующего due action и не тратит RNG. Неполный legacy blob даёт typed error, а не bool coercion/rebuild. Это не отменяет более строгий existing T161 admission для run без behavior marker.

Все данные synthetic, собственная `cx_team_plan_revision`; checkout T161 с полным regression на `9bba1d9` не изменяется. Результаты будущих этапов не приписываются этому checkpoint заранее.

## Restore, reset и rollback

Журнал лежит в обычном FK-owned `sim_events`, попадает в штатный bank dump/restore и lifecycle exports; private operational namespaces не затронуты. Новые runs после reset создаются существующей фабрикой. `reset_day` не меняет run и не должен пересоздавать план/marker или сдвигать due dates; проверяется существующим simulation suite. Отдельного production clone endpoint в текущем source нет; recovery fresh owner и dump/restore проверяются как различные границы, без заявления о несуществующем API.

Перед rollback штатно остановить actors/часы. Историю plan/marker/actions не удалять и не переписывать. Безопасный откат source допустим только для новых runs либо остановленных run без ещё не исполненных journal-only планов; старый код не читает `team.plan`, поэтому возобновление такого run старым кодом снова нарушит RNG continuity. Для затронутого run — сохранить остановленным до forward fix или явно создать новый run, сохранив историю. Не удалять marker как обход, не делать forced take, не подбирать новый plan/duration. DDL rollback не нужен.
