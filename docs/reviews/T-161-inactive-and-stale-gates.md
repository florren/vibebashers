# T-161: historical business completion и единственный current owner

## Граница

Утверждённый scope модели не запрещает завершать bounded business graph/HITL/follow-up исторического run. Такой graph сохраняет собственный run, AR/checkpoint, frozen role configuration и прежние финансовые проверки. Но он не может менять behavior state/hazard или добавлять owner evidence для stopped/noncurrent run.

`StateEvidenceResult` явно различает принятый запрос и `accepted=false, evidence_id=null, reason=inactive_run`. Для inactive owned `free`/`scenario` используется именно suppressed sink — **не** `None`, которое разрешило бы legacy UPDATE. Это относится и к legacy inactive run без marker: marker не создаётся, история не реконструируется. Actual state возвращается отдельно от requested state; trace содержит `suppressed`/`inactive_run`, а не утверждение применения. Current active legacy run без marker по-прежнему требует нового run.

Проверка повторяется внутри write TX. `sim_runs FOR SHARE` удерживает kind/status до commit; current читается только для этого run. Штатный `create_run` сначала блокирует SimState, останавливает предыдущий открытый run и лишь затем меняет pointer в одной TX. Поэтому допустимый запрос линеаризуется до stop, либо после перехода становится suppressed. Restore/reload защищены maintenance lease/drain. Произвольный административный SQL в эту cooperating boundary не входит.

`prepare_run` использует совместимый `FOR SHARE`: одновременно с graph refund→enqueue Sim tick может удерживать SimState→run→account. Late graph callback **не** берёт SimState lock после money locks. Native Twin callback также подавляет inactive behavior effects без запуска legacy care writer.

## Защита Simulator

`persist` больше не назначает current pointer: это делают factory/restore. UPDATE условен по `current_run_id IS NOT DISTINCT FROM self.run_id`, stale caller получает явный ValueError→HTTP409 и rollback. Control проверяет current до эффектов; блокировки остаются в порядке Python lock→SimState→run. Start factory, reset RNG, persist и commit объединены; loop запускается после commit. Ошибка до commit возвращает прежний RNG object/World и не оставляет новый run. Model tick сохраняет прежний rollback time/RNG/stats/World. Штатные bootstrap/load/resume/reload продолжают получать pointer из БД.

## Проверено на собственной PostgreSQL16 scratch базе

- **52 passed, 55.10 s**: typed-result/trace tests, inactive closed/noncurrent/markerless cases, actual two-connection accepted-before-stop/current-switch barriers, stale two-Simulator overwrite counterexample, atomic start rollback/retry и неизменный parallel20 business/isolation test.
- Расширенный control/durable retry набор: **52 passed**, единственный новый refund proof первоначально падал в итоговом full-bank invariant из-за отсутствия полного ledger backfill в fixture. Все refund/enqueue concurrency и rollback assertions до этой строки уже прошли. Добавлен штатный full backfill (как в исходном ABS proof), без удаления invariant.
- Повтор исправленного native `RULE-QR-FEE-001` refund proof: **1 passed, 7.22 s**. Настоящая rule evaluation, refund ledger/account effect, параллельный tick SHARE→account, enqueue без deadlock, общий TX rollback и invariant всего synthetic банка проверены.
- Старые test_sim contracts теперь проверяют также фактическую `client.*` family по существующей behavior/client_event schema. Step atomicity сохраняет все failure/cancel/phantom-ID assertions; успешный commit проверяет точный durable timer вместо RAM pending, один affect receipt и точный RNG: успешная operations draw + существующие complaint/patience draws.

Логи: `/tmp/t161-inactive-stale-gates.log`, `/tmp/t161-gates-money-controls.log`, `/tmp/t161-refund-share-native.log`. Это source-qualified targeted proof, не новый успешный монолитный full run. Полный unit повтор после этих изменений: **1725 passed /18 skipped, 45.13 s**, лог `/tmp/t161-gates-fullunit.log`. Окончательный composed full regression проверяется отдельно.

## Оставшиеся границы review

Нативные active-fault duration/correlation recovery и delayed-LLM pre-effect timestamps ещё отдельные follow-up. Последний затрагивает refund/ledger timestamps и требует отдельного пункта финального financial review: прежнее одобрение T165 его не покрывает. `reset_day` semantic change также отдельно указан в admission checkpoint. Числа demo-policy, формулы, лимиты и legacy churn_risk projection не изменены.
