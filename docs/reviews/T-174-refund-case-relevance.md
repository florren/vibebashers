# T-174 follow-up — финансовое review связи возврата с текущим claim

Подготовлено для обязательного human review до merge. Ветка stacked поверх проверенного money-parser `0cbee24`; main/T-017 и replay cassettes не редактировались.

## Подтверждённый дефект

BRD FR1.4 требует найти событие, вызвавшее негатив; ТЗ21.4 п1 — отбор операции по продукту/сумме. Прежний check_rules рассматривал все recent operations клиента: чужая QR-комиссия создавала matched и меняла не только fast path, но classification/decide/act. Жалоба на открытие вклада могла завершиться возвратом комиссии по карте, закрытием fee_refund и выдачей подарка.

На собственной synthetic БД controlled negative test временно восстановил только прежний all-recent-ops selection (одноразовый plugin вне репозитория). Неизменённый deposit regression ожидаемо упал: AR completed, refund54.72, issued gift1000. Логи/evidence: `/tmp/refund-scope-beforefix.log`, `/tmp/refund-scope-beforefix-evidence.json`. При новом guard тот же scenario проходит без refund/issued gift/закрытия deposit claim.

## Конкретный scope diff

- Полный CRM context operations сохраняется. Failed-operation hints ограничиваются совместимыми product/operation_hint текущего обращения.
- Агент передаёт движку per-rule refund candidates; остальные action types продолжают читать весь прежний context. Unrelated refund rule получает not_matched, а не ложное matched с последующей попыткой заблокировать только fast path.
- Mapping/markers/intents/products/methods — валидируемые `case_scope` и `refund_case_context` в `data/rules.yaml`, не hardcoded PROC-коды в узле. Pydantic проверяет enum из contracts, лишние поля и regex; trace check_rules.input содержит fingerprint metadata и причины отбора. Общие financial лимиты/числа condition не изменены.
- Нужна явная тема денежного правила: QR-fee отдельно от unrecognised principal/fraud и от двойного списания. Refund_request сам по себе не разрешает возврат QR-комиссии. Product/method должны совпасть; сумма может обозначать payment ИЛИ fee. Unknown rule без metadata, отрицание, известные competing/fraud topics и несколько неразличимых кандидатов не дают financial matched; остаётся обычный граф.
- Metadata реализует ограниченный консервативный lexical scope, не универсальную NLP-классификацию. Положительные case по умолчанию — debit-card QR fee; неизвестные формулировки/новые финансовые rule codes требуют case_scope в данных и review. Изменение data metadata требует перезапуска процесса (как другие кэшируемые каталоги); fingerprint позволяет различать policy snapshots.

## Proactive и массовость

ТЗ21.4 п6 допускает отдельный scan/HITL cohort и проактивные сообщения; это не разрешает считать чужую жалобу решённой. `find_affected_clients` не ограничивается текущим claim. Отдельный explicit proactive fee case возвращает свою комиссию и не закрывает pending deposit incident того же клиента.

Дополнительная threshold regression выявила существующий mass-HITL bypass ordinary decide/act после отказа fast path: при50 pending сначала возвращалась своя fee, scan видел49 и терял массовый proposal. Enforcement существующей policy реализован отдельным commit: до refund сохраняется структурный snapshot pending_count/threshold/error_code/observed_sim. Ordinary decide запрашивает HITL; все пять effect-узлов требуют accept/modify для массового случая. Перед act/act_instant scan повторяется для обнаружения нового массового случая. Legacy checkpoint с mass reason без count завершается диагностируемым отказом. Threshold50 и права оператора не изменены. После approved собственного возврата snapshot50 сохраняет массовый proposal, хотя остаток уже49; bulk остаётся отдельной HITL-задачей, без автоматических выплат другим клиентам.

## Проверки перед полным набором

81 targeted unit, 15 graph/ledger/customer/scenario integration прошли. Проверены deposit, gratitude, noise, QR technical claim, unknown principal и typed fraud с реально присутствующей recent QR fee; no matched refund/no ledger refund/no issued gift. Positive decimal QR возвращает только выбранную операцию54.72, другая90 не возвращается. Ambiguous2 candidates не выбираются автоматически. Explicit proactive не меняет pending deposit; mass scan сохраняет других affected клиентов без автоматических возвратов им. Существующие customer_messages/scenario8 assertions не менялись.

Контракты/DSL не менялись: существующий runtime all/eq и public condition-schema scope/when имеют legacy расхождение, новая metadata находится вне condition и не выдумывает расширение DSL. Реальных LLM/Telegram/email вызовов нет; все DB тесты — `cx_refund_relevance_revision` на scratch PostgreSQL16.

## Resumed checkpoint: pre-effect validation

`act`, `act_instant`, `verify`, `gift`, `close` повторно проверяют финансовый scope до business effects. Legacy matched rule с несвязанным text/product/operation IDs не может воспользоваться старым checkpoint: возвращается диагностируемый `stale_refund_scope`/failed. Это выбранный безопасный исход вместо silent ordinary reprocess: нельзя переинтерпретировать ранее принятое человеком решение как approval другой проблемы. Human decision остаётся сохранённым; нужна новая актуальная обработка/согласование. Уже совершённые старым кодом проводки/подарки не откатываются автоматически.

Retry возобновления выбирает полный wait_human checkpoint, привязанный к конкретному human_decision_id; компактный post-resume ack больше не принимается за state и не выбирается чужой следующий HITL checkpoint. Проверены legacy/unrelated accepted checkpoint (no refund/incident/gift, approval сохранён) и нормальный approved refund6000 с повторным resume (одна refund-проводка). Pure tests подтверждают отказ до вызова DB effect для всех пяти узлов.

## Проверки массового enforcement

Границы49/50/51 проверены на graph/ledger:49 — прежний автономный путь;50/51 — wait_human без refund до approval. После accept выполняется ровно один собственный refund54.72 и одна mass_refund manual_review; повторный resume не дублирует проводку, баланс или задачу. Pure tests проверяют отсутствие DB effects для всех пяти узлов при пропущенном approval, late scan на пороге50 и безопасный отказ legacy snapshot без count. Targeted unit129 passed; полный набор фиксируется ниже после завершения.

## Совместимость, риск и rollback

Публичные API/DB contracts и миграции не менялись. Финансовые лимиты, threshold50 и права accept/modify/reject/delegate сохранены. Меняется автономное поведение: неоднозначный/несвязанный fee claim не получает financial matched; checkpoint с устаревшим scope или неизвестным legacy mass count безопасно отказывает вместо продолжения денежных эффектов. Это может потребовать новой обработки и повторного human review для старых paused run.

Snapshot mass count сохраняет основание уже принятого решения; он не является разрешением массово заплатить всем участникам cohort. После accept/modify выполняется собственный подтверждённый refund, остальные остаются manual_review/HITL. Новые формулировки и новые денежные rule codes требуют review metadata, иначе автономный refund не выбирается.

Rollback — обычный revert commits финансового пакета и deployment предыдущей версии приложения, без изменения схемы и без автоматического удаления ledger/tasks/HD. Ранее созданные денежные проводки не отменяются этим diff; их финансовая коррекция требует отдельного решения и штатной процедуры. Откат возвращает прежнюю ошибочную границу claim/mass, поэтому безопаснее временно остановить обработку затронутых cases до исправления, чем переигрывать их автономно. Перед merge обязателен human financial review всего конкретного diff.


## Routing context отдельно от финансового права

Полный прогон выявил собственную регрессию selectors: `transfer` ошибочно сравнивался с `method=transfer`, исключая валидный `op_type=transfer,method=online`. Данные исправлены на отбор по op_type; исходные assertions сценариев02/06 сохранены. Диагностика использует отдельный `routing_operations` и data-driven overrides notification/login по system_path; значения проверяются существующим generated System enum. Финансовый `case_operations` по-прежнему запрещает notification/login и не получает право refund от диагностических фактов.

MockProvider в фактическом normalization output опускает необязательный operation_hint (unknown), а не генерирует произвольный enum. Это закреплено unit test; ненужного изменения Mock/runtime API нет. Добавлены pure tests transfer/online и transfer/transfer, notification/login diagnostic context без financial authority, invalid system; negative graph case notification с реально присутствующей QR fee не должен создавать refund/issued gift. Targeted pure suite:135 passed.

Адресная DB-проверка после исправления routing selector:53 passed (весь `test_scenarios.py`, финансовые regressions/customer/scenario8); дополнительно2 passed для явных contract-valid notification/login hints с QR fee. Исходные assertions сценариев02/06 не менялись. `make lint` прошёл: Ruff, format329, mypy244, frontend144, OpenAPI191/191.
