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

## Native routing / T161 ownership checkpoint

Обычным merge включён committed T16189f61b5. Producer и короткая effects transaction используют его active_run SHARE/current gate; lock через LLM не удерживается. Native system/error routing имеет приоритет над product_line модели только для подтверждённого service signal, customer routing сохраняется. Дополнительная CX команда из ТЗ6.9 хранится в fault_monitor config.co_team_codes; отсутствие/невалидный source, неизвестная команда или отсутствующий native routing rule завершаются диагностикой, без подстановки команды.

9 actual PG passed (49.42s): в том числе schema-valid Fake model с неверным product_line, фактический team_notifications+team_cx и unchanged DCLTV affected_count=3; четыре негативных конфигурации не создают signal. Новые immediate Sent outcomes явно отражаются как emulated, queued не выдаётся за доставку. Критерии всей карточки по-прежнему не закрыты. Отдельный regression выявил отсутствующий metadata link identified customer до реального HITL; его исправление будет отдельным focused commit с неизменными human/act guards.

## Common effect-time composition

Ordinary merge T1615d7c427 добавляет общий per-tool native effect-time callback. T039 делегирует ему время, добавляя только service-specific fault-window/current-run check перед каждым side effect; отдельного глобального time setter нет. На композиции12 actual PG passed (65.18s), включая original T161 delayed-notice/refund financial timestamp cases. Deterministic resolution между двумя отправками:1 passed (7.26s); весь act rollback, нет native notifications/incident от откатившейся попытки. Новый guard не разрешает отправку после закрытия fault и не выдаёт queued за доставку.

## Поздние адресаты и strict checkpoint

Один native signal/AR сохраняется, когда impact увеличивается после первого прохода. Private resume-only entry допускается только для того же deferred AR, durable followup checkpoint и verified fault/run; ingestion payload не задаёт этот контекст. Исполняется существующий act с ограниченным набором инструментов link/mass/economics/notifications, без повторного routing, смены incident status, модели, gift или выплат. Decision/human state и token totals сохраняются.

4 actual PG passed (24.75s): поздний новый адресат на новом соединении, persisted unknown не переотправляется, caller cancellation после durable entry с последующим recovery того же thread и два конкурирующих wakeup. В каждом случае один AR/incident/scheduled followup и один initial normalize/classify/decide; native mass/economics увеличиваются до2 без изменения формулы. Это не утверждение OS SIGKILL proof: cancellation проверена event barrier на настоящих PostgreSQL checkpoints и другом соединении.

### Причинная metadata-связь до обязательного HITL

Два actual-PG counterexample воспроизведены без изменения policy: identified
`ultra_vip` обращение ожидает HITL и не получает `incident_signals`; при двух
same-code faults более свежая операция B подменяет явный source A. Исправление
отдаёт приоритет citation только после same-run/client/time/system/cause
validation и native `fault.started` provenance. Конфликтующая/будущая/чужая
citation не заменяется другой операцией; без citation несколько валидных fault
candidates дают `None`, а не выбор самого свежего. Причинный as-of — native
`signals.received_sim`, не более позднее effect time.

Для verified `link_existing` перед HITL выполняется только существующий
логируемый `link_signal_to_incident`: native link, AR incident header и штатное
обновление mass/economics. Новых маршрутов, возвратов, подарков, принятия решения
человека или запуска `act` этот шаг не выполняет. Уже ожидающий human incident
принимает следующую metadata-связь; прежние pending decisions не заменяются.
Это новая metadata/HITL boundary для отдельного финального human review, не
покрытая прежними approval финансовых PR. Формулы, лимиты и права не менялись.

Проверки: две исходные regressions — 2 passed/14.78s; расширенная композиция
HITL + fault/timing + late/recovery — 17 passed/108.10s до последнего сужения
native-event/catalog validation. Окончательный targeted результат фиксируется
следующим checkpoint; full всей T039 ещё не заявлен.

Окончательный causal/HITL checkpoint: 3 actual-PG regressions passed/20.56s
(включая повторный pending HITL и negative native provenance); полный unit
1797 passed/18 skipped/57.73s; Ruff выбранных файлов и mypy трёх изменённых
production modules зелёные. Весь T039 `make test` ещё не выполнялся на этом head.
