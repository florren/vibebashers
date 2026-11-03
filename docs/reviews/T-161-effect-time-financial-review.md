# T-161: post-LLM effect time — отдельный financial review

**Нужен review конкретного изменения timestamp semantics. Прежнее одобрение T165 и demo-policy не является одобрением этого пункта.** Пакет локальный, публикация/production операции не выполнялись.

## Доказанная причина

`ToolContext.sim_time` формировался до await LLM. Пока модель ждёт, SimClock может продвинуться; инструменты затем записывали старое время в `notifications.sent_sim` и другие effect fields. Actual PostgreSQL counterexample до исправления: контекст T0, штатные Sim steps до T3, `notify_client` сохранил T0. Лог `/tmp/t161-stale-effect-time-before.log` (1 ожидаемый regression failure, 7.32 s).

## Конкретное изменение

Production `load_deps` устанавливает `effect_time_fence`; общий `@tool` вызывает его непосредственно перед `SIDE_EFFECT_TOOLS`, после LLM. `BehaviorStore.current_effect_time` возвращает aware native persisted SimTime **только своего current run**, проверяя kind/status под `sim_runs FOR SHARE`. SimState lock в late graph callback не берётся; LLM не исполняется под этим fence. Требуется активная caller transaction (`TransactionStatus.INTRANS`): допускаются как неявная транзакция при `autocommit=False`, так и явный transaction block при `autocommit=True`. Helper не выполняет commit. Эта граница исправлена и проверена в `70e4b00`; standalone-вызов вне транзакции отклоняется.

Current active `free`/`scenario`/`live` получает собственное native время. Historical/inactive/baseline сохраняет bounded own-run context: foreign clock не заимствуется. Model eligibility по-прежнему только `free`/`scenario`; `include_live=True` в effect clock не включает hazard для live. Dry-run comparison не запускает effects/fence.

`behavior_agent_intents.observed_sim` и owner evidence получают native write/observation time. **Happened time клиента остаётся `signals.received_sim`**; поздняя классификация не переносит first complaint вперёд и не создаёт retrospective hazard draws.

## Потребители, влияющие на review

Общий effect context используется существующими write tools: notification sent time, incident/status/SLA-derived timestamps, task/follow-up scheduling, escalation/closure и Mock-АБС `refund_fee`/ledger `posted_sim`. Значения ставок/лимитов, формулы, consent/HITL, rule confirmation, operation/run attribution, суммы и idempotency не меняются. Однако сдвиг реального effect timestamp после долгого LLM — самостоятельная семантика, способная изменить временной срез отчёта, поэтому этот пункт явно вынесен на financial review.

Повтор idempotent refund/notification сохраняет исходную native запись и её happened time; повторный fence не переписывает ранее совершённый effect.

## Проверка

**39 actual PG tests passed, 211.37 s**, лог `/tmp/t161-native-effect-time-scopes.log`:

- Delayed controlled Mock fixture: complaint T0, notice T3, классификация/observation T5. T3/T5 получены из действующего segment deadline через обычные Sim steps; policy values не менялись. Synthetic negative response проверяет chronology, не accuracy модели. Native signal text и вход модели совпадают.
- First complaint остаётся T0; proactive/speed credit нулевой для действительно позднего notice; next hazard строго после recognition T5.
- Реальное `RULE-QR-FEE-001` подтверждение и refund tool: active current ledger timestamp равен своему native clock; historical ledger timestamp остаётся own T0 при более позднем foreign clock.
- Повтор refund возвращает тот же entry, не меняет `posted_sim`, не удваивает сумму; полный synthetic ledger invariant сохранён.
- Прежние owner, inactive/current switch, SHARE/account concurrency и rollback checks проходят.

Полный повтор на этом source: **1725 unit passed /18 skipped, 45.36 s; offline scenarios/replay 43 passed /2 skipped, 225.61 s**. Лог `/tmp/t161-effect-fence-unit-scenarios.log`; исходные cassette/response/hash assertions сохранены. Новый монолитный full regression после всех follow-up ещё не заявлен. Современные active-fault duration/correlation recovery — отдельный следующий packet, этим proof не покрыт.
