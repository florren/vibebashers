# T-161 / T-040 — composite FK archive/delete follow-up

Actual0017 добавила настоящий composite FK `(run_id,client_id)` в behavior owner
closure. Старый lifecycle blanket guard отвергал любую ширину FK>1; исходные
10 lifecycle/checkpoint regressions T-241 не доходили до purge. Producer fix
сохраняет ordered column pairs из pg_constraint и соединяет **все** пары через
AND в owner resolution и cross-run checks. Корневой FK остаётся к sim_runs.id;
неизвестный некорректный shape явно отклоняется, guards не обходятся.

Дополнительные populated tests обнаружили вторую причину: root-only purge
полагался на runtime→causes CASCADE, но immediate NO ACTION causes→operations
мог провериться раньше transitive удаления. Теперь один SQL statement явно
удаляет всё FK-owned замыкание по вычисленному owner. Все CTE используют один
statement snapshot; FK/nullable constraints не ослаблены. Экспорт и прежние locks/
foreign ownership checks выполняются до purge. Private channel_runtime/llm_runtime
не входят в public/langgraph FK discovery и не затрагиваются.

Проверено на собственной actual0017 DB: **17 passed, 96.66 s** — весь
run_lifecycle module, обе исходные checkpoint ownership archive/delete проверки,
legacy duplicate-current fixture, четыре новых populated composite case
(2 clients, archive/delete, foreign composite reference с отказом и retry после
явного удаления только собственной synthetic ссылки). Сохранены исходные
atomic export rollback, current/baseline/active run guards, cross-run references,
header/summary/descendant isolation и data preservation assertions.

Legacy fixture уже исправлена в4c99681: test-only scratch TX моделирует pre0017
без нового index, исходные два legacy rows и aborted upgrade проверяются без
удаления истории; обычная actual0017 uniqueness не ослабляется.

При будущей композиции T-121 runlease guard должен оставаться перед metadata
inspection: этот focused fix его не удаляет/не переносит. Full T-161 runtime
repeat/process/activation ещё в работе; результат17PG не является fullsuite proof.
