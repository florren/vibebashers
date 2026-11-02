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

### Automatic wake и durable recheck

`AgentService` теперь coalesces `fault.started`/`op.failed`/`sla.tick` в один
Event; payload NOTIFY не задаёт clock/impact/client. Один отдельный daemon
использует тот же технический 2s cadence, что очереди replies/personal, и native
recheck после рестарта/потери NOTIFY. Producer transaction завершается до графа.
Новый anchor запускается обычным `submit`; deferred anchor — только через strict
same-AR/checkpoint continuation. Общие `_by_signal`/semaphore предотвращают
конкуренцию HTTP/LISTEN/continuation. Pending human не возобновляется этим путём.
Stop отменяет daemon до дочерних tasks, все lifecycle writer leases сохранены.

Actual PG regression: impact0 не финализируется; после actual op без NOTIFY
появляются 1 normal AR и 1 Sent; новая service instance находит позднего второго
получателя и даёт 2 Sent, один прежний AR с теми же tokens, один followup,
verified mass2. 1 passed/7.94s. Unit wake/coalescing/cancellation + старые
tracking/ingest/maintenance checks: 28 passed/2.30s; Ruff и mypy runner зелёные.
Первый non-escalated TestClient запуск остановлен из-за известного sandbox hang;
доказательством служит полный host повтор, не незавершённый запуск.

### Financial candidate: actual cohort вместо service/complaint rows

Сохранённый numeric regression подтвердил ошибку: один actual failed клиент,
`mass_impact=1`, но после первого customer metadata link stored
`incident_economics.affected_count` становился `2`: `signals_count` включал
служебный anchor. При исправлении before/after в обоих competing-fault cases:
`(mass, affected, potential_loss_rub, premium_addon_rub)` =
`(1, 1, 22.92, 0)` → `(1, 1, 22.92, 0)`. Старое значение potential loss отдельно
не снималось; старое `affected=2` подтверждено red regression, не расчётной оценкой.

`origin IS DISTINCT FROM 'proactive'` исключает service rows из customer count,
сохраняя legacy NULL. Для reserved native fault-monitor anchor требуется полный
canonical ingest payload/source/external-id/run/fault lineage. Shape лишь требует
проверку, authority не даёт. Cohort — DISTINCT actual failed clients собственного
run/fault/system/code/window, `started_sim <= own as_of`, с native fault.started.
Stored fault counters, будущие операции и число повторных customer signals не
подменяют cohort. Несовпадающий mass, отсутствующие/неконсистентные native facts,
provenance или own clock дают диагностируемую ошибку до financial writes.
Для исторического native run используется собственный `finished_sim`, для
текущего — persisted native clock; глобальные часы другого run не заимствуются.
Legacy/non-service fallback сохранён. Ставки, коэффициенты, retention, формула,
refund/HITL policy и платежи не меняются.

Это financial + HITL reviewer packet: metadata link до approval обновляет не
только relation/header, но и stored incident_economics через existing tool.
Pending human остаётся pending; act/refund/gift до approval не исполняются.
Откат без DDL — возврат source, но он возвращает известное ошибочное вычисление
service count; recovery при invalid native facts — восстановить/проверить native
scope и повторить штатный link/recompute, не подставлять ноль/старый payload.
User approval этого нового financial/HITL diff ещё не получено.

35 actual-PG regressions passed/218.73s: native future/counter ignore, восемь
negative facts с неизменным stored financial JSON после ошибки, повторный
customer/HITL, timing/recovery/runner, прежние finance/map/anonymous consumers.
Чистая формула/ingress/runner: 19 unit passed/1.08s; Ruff/mypy dCLTV зелёные.
Полный unit financial candidate: 1800 passed/18 skipped/54.16s. Full всей T039 и
exact-head CI ещё не выполнялись; actual120/90/30 остаётся следующим proof.

### Existing owner preflight и customer dashboard

Подтверждены две дополнительные regressions нового источника: current legacy
run без behavior marker принимал automatic anchor до graph.require_run;
service-only run показывал customer signals_total=1. Producer теперь вызывает
существующий require_run после run SHARE и до writes. Legacy/mismatched policy
error не меняет signals/ingest/events. Новая policy не вводится.

Dashboard использует отдельный customer_ws (`origin IS DISTINCT FROM proactive`)
для customer counts/response latency/first-response-by-segment. Raw AR/tokens/
agent latency и реальные incident/economics остаются полными. Общий where_s не
расширяется origin predicate, incident query не получает выдуманный i.origin.
Existing external channel=proactive с origin=api по-прежнему customer input.
Actual regression показывает0 customer signals при1 raw AR, неизменные tokens,
incident и stored economics; после обычного API input customer count1.

14 actual-PG regressions passed/95.74s, включая повторный native120/90/30;
полный unit1800 passed/18 skipped/52.25s, Ruff и mypy двух production modules
зелёные. Lazy dashboard economics refresh НЕ менялся: HTTP endpoint на этом
base по-прежнему использует прежний default refresh=True. Read-only proof относится
к явному dashboard(...refresh_economics=False); глобальный readonly HTTP claim
этим пакетом не делается. T241 view18 принадлежит другому owner и здесь не менялся.

### Scripted atomic clock prerequisite

`prepared_step` использует тот же native `_step_chunk_locked`, что ordinary
Simulator.step; Python owner lock/clock/RNG validation и existing rollback
сохранены. Только validated persisted prepared source заменяет ambient
fault/operation/client_error/noise inputs; native pending timers, teams, SLA и
BehaviorOwner работают штатно. Старые free/live/scenario без journal unchanged.
Reader проверяет exact script hash, native operation/fault lineage и typed phase
refs. Нет произвольного clock target или автоматического исправления changed RNG.

Actual own-PG: 3 passed/30.01 s (120 native episodes, no early anchor, reload
idempotence, owner failure rollback clock/RNG/episodes, changed script rejection).
Fixture сохраняет initial RNG через Simulator.persist, как API start, не
ослабляет strict equality для пустого RNG. Adjacent existing Simulator и runner:
7 passed/32.65 s; failed service AR теперь остаётся diagnostic/manual даже после
restart/трёх polls, новый AR автоматически не создаётся. Ruff и mypy4 green.

Это prerequisite, не успешный production scenario6: API/YAML/phase coordinator,
scoped paused recovery и evaluator ещё не подключены. Modelled prevention B
остаётся отдельной owner implementation/review; текущий prevented=null честен.

### Scripted phase coordinator / API25 candidate (ещё без full/CI)

Production YAML теперь содержит `prepared_native`, operation template и timings
1/0.1/0.1 сим-минуты; параметры p/delay/care/severity, цены/HITL не меняются.
API проверяет native cohort/consents до нового run; start paused и atomic
Simulator prepare создают120 native rows, не inject3 и не fake customer.
AgentService использует тот же proactive daemon: короткая phase TX заканчивается
ДО Simulator lock/model, а каждый clock step использует прежний atomic kernel.
Source anchor создаётся только после первого native owner tick. Typed journal
проверяет hash, correlation/time/refs/native cause; phases не заменяют graph.
Доставка/30 inputs/care/economics подтверждаются native rows. Notified IDs не
обрезаются, unknown не ретраится. Native queue failed AR остаётся manual.

Public Resume/step/jump/reset для journal-owned scripted run теперь409;
Stop/new run доступны. Узкая paused recovery — только same native prepared
run/fault/journal signal, старый interrupted AR и strict durable checkpoint;
AR/thread/signal/run match и pending human проверяются до graph. Graph recovery
сам выбирает pinned profiles, phase/run/time locks отпускаются до модели.
Missing checkpoint и pending HD сохраняются для ручного разбора, без нового AR,
уведомлений/ledger или потери human choice. Ordinary paused/free/live unchanged.
**Эта новая control/recovery/HITL граница входит в final API25 human review,
прежние approvals её не покрывают.**

Source-qualified evidence: phase/prepare/recovery13PG passed127.94s; отдельные
новые evaluator/unknown-delivery/control/recovery6PG passed64.04s. Actual ASGI
API2PG passed16.45s: lite409 не меняет run count/time/RNG/owner, demo202 paused
native120 без signals/AR/ledger/client identity. Controlled phase proof использует
существующий synthetic5000-client metadata seed, не обещает lite120 cohort.
Никакие контакты/consents ради phase proof не редактируются.

Evaluator все обязательные checks требует True, незавершённость/unknown — False;
CLI ждёт bounded completed/failed journal в existing --wait. Map reuse вызывает
existing get_map_zones с explicit run_id локально, без HTTP: код producer и
resolve_run_id/_sim_now SELECT-only, без refresh_economics/write/LLM. Actual
positive evaluator/map + unchanged incident_economics JSON проверены в6PG.
Raw AR/tokens/Trace не фильтруются. Prevention пока null/not_modelled — отдельный
owner B helper/receipt dependency ещё не составлен; отменённый timer не Sent credit.

Откат operational: Stop/new run; уже созданные native факты/решения не удалять и
не переписывать. Старый strict event consumer не знает новую scenario family;
rollout согласуется вместе с API25/contracts. Новый nullable client_id описывает
NULL service anchor. Новых DDL, внешних вызовов, env/registry reads здесь нет.
Финальные whole lint/test/coverage/composition/CI/receipt B ещё обязательны;
T039 не объявлена done.

Последний early-customer regression:1PG passed13.84s — настоящий normalizer +
Mock graph создаёт canonical classification до следующего paused owner tick;
phase фиксирует early_complaint, не выпускает scripted30 и не продвигает часы.
Timeline/correlation native journal проверяются вместе с hash/refs.

Whole unit на host:1821 passed/19 skipped49.62s, Ruff/format488files green;
mypy301 green, contracts46schemas/162paths, own sync-contracts110models и TS
nullable client_id generated. Первый restricted sandbox unit завис на16 dots,
остановлен только свой session(exit130); host repeat прошёл без source/test
изменений для этого зависания. Это обход окружения, не runtime fix.
Coverage/full PG/scenarios/compliance/front/final composition ещё впереди.
