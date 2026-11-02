# T-037: финальная граница event/journal review

T161 сохранял clock/RNG tick, но случайный TeamEmulator plan до первого due action оставался в RAM. T037 сохраняет это решение в той же существующей tick TX, где фиксируется shared RNG. После restart выполняется прежний план с прежними due times. Фиктивные take/report не создаются; вероятности, SLA, p/delay/care, денежные формулы и HITL не меняются.

## Контракты и совместимость

- Новый additive typed `team.plan` event: версия1, incident/team и полный initial plan (steps, times, flags, regression decision). Привязка native run/incident/version проверяется; private transaction advisory key сериализует builders, повтор читает committed plan до любого draw. Дубликат/некорректные факты дают typed error, не выбор случайного snapshot.
- Новый typed `team.runtime_started` версии1 отмечает enrollment. Для нового run он создаётся в create_run TX после behavior marker, до смены current pointer. Изменены envelope и две новые payload schemas/Pydantic-модели; существующий team_action payload/enum не переименован. DDL и API paths не добавляются.
- Новые подтипы валидируются отдельно от обычных `team.*` actions. WS сохраняет семейство team/topic sim; существующий runner реагирует по точному team.release. Reader, который считает каждый team.* выполненным действием, должен различать новые journal events; они не имеют action_id и не добавляют строки team_actions. Общий счётчик настоящих sim_events закономерно включает журнал.
- Последующие реальные action snapshots сохраняют execution flags; clarify/resume до следующего action восстанавливаются по actual clarify/status/progress facts без RNG draw. Action-only legacy blobs читаются как факты после проверки структуры/aware times.

## Явный legacy fail-closed

Без marker нельзя отличить новый incident от потерянного старого RAM-плана. Legacy enrollment допускается атомарно только при отсутствии unresolved planless incidents и release с неизвестным plan/pending regression. Неизвестный активный pre-action план, некорректный snapshot или неясный legacy release дают actionable TeamPlanError с run/incident IDs до clock/RNG/generator effects. Данные сохраняются; автоматического закрытия, реконструкции, forced take или исправления рабочей БД нет. Даже закрытый legacy release без плана не считается доказательством отсутствия pending regression.

Это новая compatibility граница, требующая **отдельного human event/journal approval**. Подтверждение пользователем T161/PR193 (при green CI и parent188) не заменяет этот review. Семантика receipts B уже разрешена для отдельной реализации; DDL0019/API27 не входят в T037.

## Проверенные источники

- На composition98af3b66 (P2→T161→T037): **67 passed,364.32s** — INTRANS/current effect, owner, inactive/two-owner, plan/OS/clone, fault recovery и reset_day. Лог `/tmp/t037-current-p2-parent-targets.log`.
- После root docs/source-acceptance-only d0867fc merge: head a3fb6164. Все **14 journal/schema/test SHA** и **11 behavior SHA** побайтно прежние; runtime не менялся. Финальный source proof: [JSON](T-037-current-parent-proof.json).
- Actual SIGKILL до первого take: восстановленные plan/RNG/исходный clock равны; настоящий take выполнен ровно в native due instant. PG16 dump/restore в отдельный disposable synthetic clone также сохранил plan/RNG; исходная scratch БД не продвигалась. В clone и reference задана одинаковая controlled zero-generator workload.
- Journal changed-executable line coverage **131/131**, hash-checked union двух успешных прогонов; это не branch coverage. Ранние source56e62b9 unit1727/18skip, scenarios43/2skip и compliance31pass остаются историческими source-qualified результатами, не полным suite нового head.
- На финальной композиции make lint green: backend475Ruff/300mypy; bot12Ruff/5mypy; frontend366tests/47files, typecheck/lint; drift192/192. Один inherited DemoMenu ESLint warning,0errors. Contracts47schemas/162paths, licenses550+36. Backend generation110ORM и frontend types без tracked diff; первая FE generation требовала отсутствовавший node_modules link, после подключения существующего frozen окружения повтор прошёл, пакеты не устанавливались.

Production, реальные LLM и Telegram не использовались. Перед merge нужен **green CI exact final head**; scoped tests не объявляются полным backend integration. T161 отдельно сохраняет известную whole-World plan/RNG границу до T037; универсальная equivalence произвольных конфигураций не заявляется.

## Rollback

Штатно остановить actors/часы и сохранить journal/actions/history. Старый код не читает journal-only plan: возобновление такого run старым кодом снова нарушит RNG continuity. Для него — держать остановленным до forward fix либо явно создать новый run с сохранением истории. Marker/events не удалять как обход; due times и выборы не подбирать. DDL downgrade не нужен.
