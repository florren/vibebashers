# T-161 — actual0017 dependency checkpoint

Base ab00cf9 включает закреплённые cc3e229 (actual0016, без quota hooks),
17104d9 actual0015 follow-up и main e572939. Actual0017 forward-only имеет
parent0016 и переносит проверенный owner proposal в canonical schema/migration.
Public behavior runs/evidence/runtime/causes/work/receipts/tick receipts/agent
intents/pending signals принадлежат run через FK CASCADE; private llm_runtime и
channel_runtime не меняются. World pending snapshot сохраняется как timer source,
не как care или gold. Marker не разрешает угадывать legacy неизвестные timers.

Own scratch cx_behavior_revision реально прошла 0014→0015→0016→0017. Два повторных
применения SQL сохраняют число client_states; actual head0017, public behavior
таблиц 9. make sync-contracts выполнен только в своей worktree, ORM110 classes;
Alembic check не обнаружил drift (известный warning циклических FK остаётся).
Runtime wiring/activation/full-suite ещё не завершены. Этот checkpoint нужен
зависимым карточкам для честной цепочки схем, а не как merge-ready T161.

Откат кода не удаляет таблицы/историю: downgrade намеренно forward-only. Перед
активацией legacy непустой run без marker отклоняется до эффектов, нужен новый
run. Actual runtime tests, archive/baseline/crash/retry proof и финальный human
DB/contract review впереди; новые значения policy не добавлены, enabled=false.
