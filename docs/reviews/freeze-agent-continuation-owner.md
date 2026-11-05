# Freeze: единственный владелец продолжения AgentRun

## Проверенные дефекты

Nightly browser suite прошёл 168/168, однако PostgreSQL сообщил
`agent_steps_run_id_seq_key` для `(run_id, seq)=(54,258)`; исходный фрагмент
сохранён рядом в `freeze-agent-continuation-owner-nightly.log`.
Детерминированная PG-регрессия воспроизвела ту же коллизию `(1,10)`:
followup восстановил seq и записал `outcome=NULL`, а параллельный recovery
успел восстановить тот же AgentRun и записать следующий шаг.

Отдельная регрессия штатного human accept показала вторую гонку: таймер
потреблял новый followup между commit узла act и первым followup_monitor.
В этот момент AR ещё awaiting_human, checkpoint для продолжения отсутствует,
поэтому таймер становился fired без обработки.

Crash между ранним commit followup-entry и новым LangGraph checkpoint также
оставлял outcome=NULL со старым terminal checkpoint. Требуется atomic entry.

## Конкретное изменение

`resume_after_followup` и `resume_after_human` используют существующий
session advisory lock `agent-resume:<id>`, общий с recovery/proactive.
Он сохраняется через checkpoint commits и освобождается в finally после
rollback, включая aborted SQL transaction и cancellation. Entry points принимают
выделенное соединение: runner открывает self._conn, API фиксирует decision
в собственной transaction до svc.resume. Human decision и 409 guards не
переносятся внутрь ownership transaction и не откатываются cleanup.

Timer выбирает только parked AR (`outcome=deferred` и сохранённый
followup_monitor). Он получает неблокирующее владение до изменения статуса
followup; busy остаётся scheduled. Повторная проверка scheduled/deferred
выполняется под ownership. Разные followups одного AR сериализуются,
разные AR сохраняют возможность параллельной обработки.

Для SLA сохранены прежние специальные пути: escalation_check потребляется без
продолжения; report_due допускает completed/deferred с существующим monitor.
Штатный notify_team сохраняет прежнюю дедупликацию team_notice.

После human decision AR получает outcome=NULL атомарно с новым accepted
checkpoint и audit шага, поэтому crash после durable entry доступен штатному
restart recovery без повторного принятия решения.

Claim и новое состояние AR фиксируются вместе с первым durable graph entry;
ранних commits между claim и checkpoint нет. Crash до entry откатывает claim,
после entry действует штатный durable recovery. Исключение до entry не
поглощает таймер. Шаги не перенумеровываются, UNIQUE constraint не ослаблен.

## Граница review

Изменение касается владения продолжением, в том числе human accept и
recovery потенциальных денежных эффектов; требуется human review по
AGENTS.md §5.1. Решения человека, суммы, лимиты, формулы, разрешения и
payload не меняются. API/DDL нет, история не переписывается.

Rollback — откат patch к прежним entrypoints; потерянные старые timer wakes
и уже созданные ошибочные проходы автоматически не исправляются.
Окно между сохранением human_decisions API и первым accepted graph entry
не получает автоматического startup reconciliation этим patch: старый
awaiting_human с уже сохранённым решением требует отдельного operator recovery. При
rollback остаётся исходная подтверждённая гонка; не следует одновременно
продолжать один AR разными worker paths.

## Проверки

Проверки выполняются на собственной PostgreSQL с native Mock graph;
primary, реальные LLM и Telegram не используются. Полный финальный gate
должен включать этот diff и пройти отдельно после review.

На итоговом source `graph.py` SHA-256
`f492345484e6044e7e087c1afeaf15d9fde2c52bc5d9b16a522582c87887ce86`:

- 54 unit/PG subsystem tests passed (219.12s): followup nodes, конкуренция
  recovery/followup в обоих порядках, duplicate timers, SQL error/cancellation
  unlock, SLA exceptions, существующие followups/LLM recovery/proactive/fault recovery.
- 8 независимых native PG HITL/crash tests passed (58.44s): global/run timers,
  cleanup, before-entry rollback, post-durable-entry recovery, в том числе
  настоящий AgentService._recover после human accept. Decision tuple,
  notifications/tasks/ledger hashes и число Mock LLM calls сохранены.
- 1 дополнительный PG busy-deferred-owner test passed: неблокирующий timer
  не потребляет scheduled до освобождения владельца, затем штатно срабатывает.
- Ruff check/format, targeted mypy graph.py, git diff --check passed.

Итого 63 адресные проверки; это не замена полного exact-head CI.
Один промежуточный SLA test ожидал новую notification, но source-аудит
подтвердил существующую дедупликацию; исправлено ожидание теста, production
notify_team не менялся. Один промежуточный reverse-recovery fixture ошибочно
ожидал выполнение старого terminal checkpoint; тест явно ограничен порядком
ownership, настоящее interrupted-node recovery проверено отдельно.
Прогоны без разрешённого socket-доступа с PG skipped в этот итог не включены.

Дополнительно измерено покрытие точного `graph.py` SHA `f4923454…`: 17 PG
проверок passed, 0 skipped/failed; 35/38 новых executable statement starts
(92,11%) относительно `89bc5bb`. Не покрыты missing-followup, stale claim
и missing-human-decision early returns. Это не branch/full-project coverage.
[Source-qualified JSON](freeze-agent-continuation-owner-coverage.json).
Пользователь согласовал совокупную HITL/recovery границу commit `ee8f087`
ответом «Подтверждаю после зелёного CI»; окончательный CI остаётся обязательным.
