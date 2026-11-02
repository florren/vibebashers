# T-039: native fault → служебный сигнал → обычный граф

## Промежуточный checkpoint

База: P2 `ab6a5eb` + ordinary merge T161 `871b44a`, затем focused native-origin guard `48c4e5e`. Собственные worktree/venv/БД `cx_proactive_revision`; никаких реальных LLM, Telegram или email.

Один служебный signal через normalizer (`origin/channel=proactive`, subtype `system_logs`, client_id=NULL), без вымышленной личности или клиентской жалобы. Trusted scope требует native fault.started, canonical producer source/external_id, same-run failed operations с совпадением fault/system/code/region/time и started_sim≤native clock. impact0 ждёт операции; будущие и чужие факты не используются. Service graph сохраняет обычные normalize/classify/decide/tool calls и policy/HITL checks, не предлагает деньги/подарок неидентифицированному клиенту.

Перед act/HITL после model await заново проверяются current run, fault window и native clock. Native notifications идут через notify_client по существующим proactive consent и contacts.preferred. Дедупликация различает client_id (включая NULL); существующий unknown не становится повторной отправкой. mass_impact не уменьшается числом последующих customer complaints.

## Contract-change / совместимость

API1.5.25: внешний origin=proactive и новый reserved source fault_monitor отклоняются до prepare/SQL. Прямые REST/poll/file/transcript вызовы normalizer также default-deny; только private Python keyword от native producer разрешает origin. Существующий native compliance producer явно отмечен и сохранён. Внешние интеграции должны использовать origin=api; channel=proactive с origin=api допустим. Enum внутреннего UnifiedMessage не сужается, прежние строки не переписываются. Нужен обязательный human contract review AGENTS §7 до merge.

## Проверки checkpoint

- Dependency-only composition: schema/Alembic9 passed, unit116 passed; Ruff/mypy green.
- Owner guard на этой базе:2 actual PG passed; service input не считается complaint/first_complaint/RNG draw.
- Ingress/default-deny boundary:13 unit passed, включая HTTP доDB/prepare и direct adapter calls.
- Producer + обычный Mock graph:5 actual PG passed (28.02s): три impacted clients, два consented Sent/emulated notices, один incident, без gift/ledger; delayed model отправляет в actual T5, resolved-during-model даёт failed без effects.
- Полный unit на этом checkpoint:1787 passed/18 skipped (50.49s); contracts45 schemas/162 paths.

Это НЕ завершение карточки: фоновые wakeup/recovery/late recipients, actual120/90/30 и care proof ещё в работе. Общий effect-time/active-run fence ждёт отдельного committed T161 checkpoint; WIP другого автора не копируется. T241 customer-view filter принадлежит agent3. Счётчик prevented complaints пока null/not_modelled: Sent не доказывает профилактический эффект, native cancellation не содержит достаточной attribution. После proof будет отдельный provenance proposal с T161 owner; новые policy числа/коэффициенты не вводятся. Full lint/test/coverage/final CI и human review готовой композиции остаются обязательными.
