# T-039 — временная причинность operation/fault

Focused prerequisite fix для T-039/T-161, **не завершение proactive subscriber**.
Раньше gen_operations выбирал первый active fault по system_path, хотя gen_faults
создаёт started_sim внутри того же batch. Поэтому операция могла получить
failed/error_code/fault_id раньше начала реального сбоя. Cache также не доказывал
region/run/актуальную границу resolved_sim.

Generator читает authoritative fault rows своего run один раз на batch. Causal
link допустим только при совпадении cache с настоящими system/error_code и
каталогом, наличии system в operation path, `started_sim <= operation.started_sim`,
`operation.started_sim < resolved_sim` при resolved, а также подходящей region.
Чужой/устаревший cache не создаёт failed link. Дополнительного per-operation SQL,
новых dependencies/DDL/политик денег нет.

Чтобы causal correction не сдвигала последующие RNG draws, прежний failure draw
потребляется независимо от eligibility. Для отвергнутой причины также потребляются
прежние complaint probability/delay draws, но pending complaint не создаётся.
Неуспешная causal попытка не превращается в фоновую QR-комиссию. После коррекции
этот клиент не считается реально затронутым до первого подтверждённого failed op.
Вероятность .6, существующие complaint параметры/тексты и порядок RNG draws не
менялись. World.pending остаётся прежней in-memory очередью; durable ownership
T-161 отдельно и пока не включено.

Actual PG regression (собственная cx_behavior_revision): **5 passed, 29.40 s**.
Проверены отрицательные before-fault, foreign run, region, resolved и stale code
cache; положительные after-fault связи. Полный Random snapshot (включая gauss
cache) и structural operation fields deep-equal control с тем же fault, начавшимся
до batch. Injected rollback после операций/events/ABS и повтор с тем же seed дают
одинаковые rows/timers/RNG; identity sequence ID не сравниваются, PostgreSQL
закономерно не откатывает sequence. Реальные до-fault pending не фабрикуются.

Финальный combined regression: **49 passed, 169.73 s** (5 causal PG tests,
11 simulation controls и соседние teams/operation-history unit cases).
Exact absolute-file changed-line trace относительно 83e0cf8: **31/31 = 100%**;
это line coverage, не branch metric. Результаты и source SHA:
[T-039 temporal proof](T-039-temporal-cause-proof.json).
Full make test/CI, proactive notifications/incident grouping, предотвращённые
жалобы и полная acceptance сценария 6 этим узким исправлением не доказаны.

Финальный `make lint` exit 0 после agent/T-039 source: frontend eslint/typecheck
и 225 vitest, Ruff 427 файлов, mypy 283 source files, OpenAPI drift192/192.
Полный backend make test здесь не выполнялся; integration/full CI остаётся
за итоговой actor/schema composition.
