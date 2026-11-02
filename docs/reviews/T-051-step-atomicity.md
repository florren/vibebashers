# T-031/P1: атомарность failed simulation step

## Подтверждённая проблема

UI воспроизвёл409 после fault creation, затем retry падал на operations_fault_fk; restart очищал симптом. Обычный Exception откатывал SQL, но оставлял сдвинутые clock/RNG/stats и World с незафиксированным fault ID. CancelledError восстанавливал только часть кэшей. Причина первоначального409 (prefix6 против ANTIFRAUD) исправляется отдельно approved T-014; она не отменяет самостоятельный rollback defect.

## Inventory и восстановление

- World clients/by_product/error_codes/scale — DB-derived; intensities сохраняют текущую настройку.
- active_faults — DB membership/system/error/start плюс volatile expected_end/impact/clients/corr. Reload берёт только committed active IDs, volatile attrs сохраняет лишь для совпавших старых ID.
- pending — существующая volatile очередь. Снимок ДО tick сохраняется; новые элементы failed tick удаляются. Нового queue/store нет, durable timers не заявляются (известный T-161 gap).
- textgen использует тот же SimRng после T-173. Constructor/load не потребляют его случайные числа.
- TeamEmulator plans/done/pending_regressions/regressed IDs и caches восстанавливаются из committed team_actions/faults/refs; plans содержатся в payload.plan. Нефиксированные кэши не reuse.
- SlaEngine cursor восстанавливается из committed sla.tick; segments — из справочника.

Один BaseException path восстанавливает clock/day/RNG/stats, выполняет SQL rollback и создаёт свежий World с прежними pending/fault snapshots. loaded flag запрещает reuse частично загруженного кэша. Если reload временно падает, старая pending остаётся в том же World.pending, следующий step повторяет load. Connection change также требует нового кэша с сохранённой pending. Reload failure диагностируется отдельно, исходная step ошибка/отмена не скрывается. Для обычной ошибки сохраняется sim_step_failed; cancellation не превращается в success.

## Проверки

4 PostgreSQL cases прошли17.40s: ordinary RuntimeError/CancelledError × успешный/однократно failed reload. После записи fault и operation ошибка возникает уже после сдвига clock; проверяются точный clock/day/RNG/stats rollback, неизменные DB rows, сохранение старой pending и удаление новой failed pending. Retry без restart успешно пишет operation с committed fault FK; подтверждаются старый fault deadline/impact/correlation, отсутствие uncommitted team cache, прежний SLA cursor и ровно один RNG draw успешной попытки. Исходные assertions не ослаблены, таймеры/rates/банковские правила не менялись.
