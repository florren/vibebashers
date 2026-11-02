# T-161 — durable owner: локальный review checkpoint

Значения и семантика demo-policy одобрены пользователем 02.11.2026; этот
checkpoint реализует их durable границу, но **не включает actor**. YAML сохраняет
`enabled=false`. Новых dependencies, runtime DDL, API и Alembic-файла 0017 нет.
`T-161-storage-proposal.sql` применяется только integration fixture в отдельной
scratch DB `cx_behavior_revision`; исходные/production базы не используются.

## Реализованная граница

`BehaviorStore` сохраняет evidence реальных failed operations, отправленных
notifications, client_reactions, SLA events и resolved incidents. Идентификаторы,
run/client и timestamps читаются из собственных исходных строк. Fault adapter
принимает полный набор **известных failed operations**, а не sample50 и не
предполагаемых владельцев продукта. SQL проверяет system/code/time/region связи.
Queued/failed/suppressed/unknown не означают отправку и не дают care/gift credit.

`BehaviorOwner.advance` работает только внутри переданной transaction, блокирует
`sim_state`, загружает сохранённый SimRng и атомарно записывает state/care,
receipts, таймеры, signals/events и следующий RNG snapshot. Модуль не открывает
соединение и не выполняет commit. Receipt предшествует случайному выбору.
Операции одного fault для одного клиента образуют одну initial complaint/patience
попытку; cause memberships сохраняются отдельно. Новая причина в незавершённом
эпизоде добавляется без повторного initial draw. Logical hazard ticks строго
следуют 15-минутной UTC epoch сетке, в том числе до 1970 года.

Complaint/repeat создают настоящий сигнал только через normalizer и существующий
TextGen с тем же SimRng. Gold/classification не подставляются. Patience хранит
eligibility для T-164, а не команду закрытия счёта. Resolution требует реальных
связанных incidents/faults для всех причин; care определяет retained/satisfied.
`client_states.hazard` хранит raw score в допустимом диапазоне без умножения на
100 и без незаявленного clamp. Некорректный probability domain отклоняется до
эффектов. Components, sticky SLA/tone и policy/params snapshots восстанавливаются
из БД; policy checksum проверяется.

TwinService получил **не подключённый** callback: реакция и evidence записываются
в одной transaction. При callback satisfaction остаётся наблюдением и не
переписывает care. Legacy путь сохранён до атомарного actor wiring; main callback
не передаёт. Положительный actual TwinService test проверяет это поведение.

Потеря is_current вследствие второго writer вызывает явный reconciliation error,
а не скрытое восстановление владения. CHURNED не получает новый эпизод/initial RNG;
переход нового эпизода сохраняет фактическое предыдущее состояние в событии.

## Проверки checkpoint

- 99 pure + 13 actual PG tests: **112 passed, 71.01 s**, offline/mock only.
- Реальное новое соединение продолжает persisted complaint timer; два concurrent
  соединения потребляют logical tick один раз и сохраняют тот же RNG.
- Injected transition failure откатывает state/receipts/RNG; повтор успешно
  применяет исходный факт. Полный fault cohort 62 operations/61 clients не обрезан.
- Отрицательные system/code/time/region causal boundaries отклоняются до evidence
  и RNG. Legacy duplicate currents не удаляются; потеря владения даёт отказ.
- Actual TwinService satisfaction .990 не меняет component-derived care, повтор
  реакции не вызывает второй model call. Provider локальный FakeTwin/MockProvider.
- Resolved episode с/без SLA breach выбирает satisfied/retained, отменяет durable
  work и не пишет churn_events/ledger. Gift evidence требует done+issued+matching
  sent offer; open/mismatched/personal_call fixtures credit не создают, исходные
  tasks неизменны, issuer/ledger не вызываются.
- Exact absolute-file stdlib trace: **1062/1169 = 90.85%** executable behavior
  module lines; каждый из семи модулей >=86%. Это line coverage, не branch metric.
  Raw lines, исходные SHA и границы: [proof JSON](T-161-durable-owner-proof.json).
- Дополнительно policy sensitivity/TextGen/baseline/maintenance/legacy Twin routing:
  **39 passed, 23.80 s**, на том же source.
- `make lint` exit 0: frontend eslint/typecheck и **225 vitest**, Ruff 426 файлов,
  mypy 283 source files, OpenAPI drift 192/192 без пропусков/лишних paths.
  Contracts gate: 45 schemas/162 paths; license gate: 550 distributions; diff
  whitespace check green. Full make test/CI для этого scoped checkpoint не
  выполнялись. Готовые frontend node_modules использованы через собственный
  symlink после совпадения SHA package-lock; установки/изменений dependencies нет.

## SQL proposal и совместимость

Proposal добавляет public behavior_evidence/runtime/causes/work/receipts/
tick_receipts с run ownership FK CASCADE и уникальными dedup ключами. Публичная
schema выбрана для существующего archive/baseline FK discovery. В component JSON
проверяются версия, shape, числовые диапазоны и sticky flags. Уникальный current
state ограничен `(run_id,client_id)`, а не глобальным client_id. При legacy
дубликатах proposal явно отказывает и сохраняет исходные строки; требуется
операторское согласование, автоматического удаления/догадки нет.

Это **не актуальная миграция**: зарезервированная 0017 может появиться только после
настоящих 0015 T-121 и 0016 P2. Полная схема/дамп/archive/cross-process proof на этой
цепочке ещё не выполнены. Текущий scratch base заканчивается на 0014.

## Что обязательно согласовать и завершить до активации

- Единственный writer должен включить agent `set_client_state`: сейчас legacy
  tool очищает is_current без run scope и напрямую пишет состояния. Предложен
  evidence sink на том же graph transaction с настоящей provenance; source этого
  producer пока не менялся, интерфейс ожидает отдельного root review.
- Tick adapter должен сохранить текущий shared RNG перед advance, принять
  возвращённый snapshot и commit вместе с остальными tick эффектами. При rollback
  восстанавливаются и DB, и память World/RNG. Новая P1 engine уже содержит нужную
  memory rollback границу; её требуется ordinary-merge и проверить композицию.
- `World.gen_operations` пока выбирает fault без проверки started_sim операции.
  Admission честно отказывает некорректной причинности. Исправление генератора —
  конкретный отдельный T-039 boundary, а не ослабление SQL guard.
- Approved policy не определяет отображение hazard в legacy `clients.churn_risk`
  (0..100). Поле не меняется; hazard*100 не предполагается. Требуется явное
  решение с учётом agent/dashboard/economics потребителей, а не скрытая формула.
- Legacy World.pending не стал durable. Нужны actual actor/timer integration,
  OS-process crash/restart equivalence, pause/step semantics, run isolation,
  baseline/archive и полный regression на окончательной цепочке схем.
- Actual parent notification.status=unknown из T-121 ещё не в этой schema;
  typed care уже поддерживает unknown с нулевым credit, DB composition впереди.

Карточка остаётся `in_progress`; этот checkpoint не доказывает завершение T-161.

## Follow-up: agent state writer и read scope

По отдельному root signoff реализован opt-in `ToolContext.state_evidence_sink`,
который передаётся через `graph.load_deps` и использует то же graph connection/TX.
Он пишет проверяемый intent с реальным AR→signal/run/client/incident provenance;
не меняет state немедленно. Action trace содержит `status=pending`, requested_state
и actual state; pending не публикует ложный clients.state NOTIFY. Исключение
вызывающей transaction откатывает одновременно intent/evidence; повтор dedup-safe.

Legacy UPDATE теперь ограничен `(ctx.run_id,client_id)`; baseline и чужие free/
scenario/live состояния не очищаются. Profile читает только baseline+ctx, сначала
ctx, затем baseline. Более новый foreign state больше не подменяет контекст.

Owner не считает requested satisfied/retained/churned фактом resolution/closure.
Churn-intent допускается только при persisted signal flag и actual cause relation;
repeat принадлежит actual signal/Twin evidence. Новый review-only intent table
входит в SQL proposal, но actual schema/0017 по-прежнему не менялись. Callback
не включён main/AgentService, enabled=false; полная activation/OS-restart proof
этим follow-up не заявляется. Legacy churn_risk projection не менялась.

193 regression tests passed (82.68 s): прежние 99 pure, owner+новые PG scope/sink,
router/refund tests. После дополнительных incident-provenance/pending-reasoning
правок affected 81 passed, 13 deselected (12.47 s), затем полный 193 pass выше.
Старый coverage JSON привязан к be69825 исходникам; новые changed-line результаты
публикуются отдельно, а не подменяют предыдущий checkpoint.

Actual graph.load_deps дополнительный PG test passed (8.04 s), подтверждает тот
же connection и opt-in sink в deps.ctx. Объединение exact-file trace на одном
runtime source: **105/111 = 94.59%** новых executable lines относительно be69825,
все затронутые файлы >=90%. [Agent proof JSON](T-161-agent-state-proof.json).
