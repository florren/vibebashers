# T041: time/run/RNG fence управления

Native два Simulator одного current run: actual.step3 → stale.load_state(T3) →
actual.step2(T5) → stale.control(start,counters) раньше создавал новый запуск сT3
и мог записатьfinished_sim=T3 старому run, фактически дошедшему доT5. Даже при
одинаковых часах stale RNG мог заменить уже зафиксированный draw. Это bounded
native-controller proof, не утверждение о воспроизведении single-instance HTTP reset.

Control preflight теперь проверяет native current pointer, sim_time и известный
rng_state. Проверка повторяется под существующим FOR UPDATE до start/create_run,
stop/pause, смены скорости и других control writes. Несовпадение → прежний typed
ValueError/HTTP409 до записи, без автоматического восстановления потерянной истории.
Fresh load штатно стартует на актуальномT5. Resume сохраняет существующий путь
загрузки native clock/RNG paused/interrupted; tick owner policy не меняется.
NULL legacy rng_state сохраняет прежнюю compatibility, это не новая реконструкция.

Три regression сначала RED21.67с: stale start с/без предварительного stop и same-time
RNG. После fix3passed20.79с, расширенные4passed26.00с включают также stale
stop/pause/set_speed/reset_day и interleave после unlocked preflight перед row lock.
Проверяются всеpublic table fingerprints, pointer/clock, run count/finished_sim,
последующий fresh start сstarted/finishedT5. Source change толькоengine.py,
без DDL/новых контрактов/формул/порогов/HITL/defaults. Ruff/format green.

Broader recovery/runtime/unit/lint/CI ещё требуются; четыре targeted результата
не объявляются полным suite. Producer API29 имеет отдельный defensive409 guard
на уже видимые временные противоречия; он не восстанавливает историю и не заменяет
эту writer fence (positive classification не всегда создаёт complaint receipt).

Rollback к старому controller снова разрешит stale overwrite: перед сменой версии
остановить собственные actors и загрузить свежий native state, не запускать два
контроллера. Не править clock/RNG/старые headers вручную. Production/настоящие
LLM/Telegram/email не использовались; tests только own cx_stale_control_revision.

## Независимое review: status и shutdown

После c92 peer review нашёл ещё два сохранённых пути. Actual status-only case
при одинаковыхclock/RNG: actual.stop → stale.pause раньше делал stopped→paused.
Unconditional shutdown.persist() мог откатить новые часы в обход control fence.
Третья regression показала, что прежний suppress(Exception) скрывал flush failure.
Тот source дал3RED/4deselected13.76с; исправленный набор7GREEN36.48с (6nativePG+1unit).

Check_state дополнительно читает native run.status после sim_state fence; обычные
control writers держат sim_state FOR UPDATE до смены статуса. Expected stale
выделен как StaleSimulatorError(ValueError), поэтому HTTP409 совместим. Shutdown
проходит такую же проверку под Python/DB locks: stale discard логируется как info,
TX rollback и close; неожиданный flush failure логируется и пробрасывается с close.
Постоянные данные не исправляются, новых leases/clock policies нет. Это защита
известных state/status/time/RNG противоречий в штатной архитектуре одного Simulator,
не новый distributed lease protocol. Resume по-прежнему загружает native state.

Более широкий source-c92 прогон до этого followup:56actualPG passed321.86с,
включая usage/recovery/process/SIGKILL/team journal. Результат source-qualified;
после status/shutdown нужен новый adjacent/unit/lint/CI, не перенос старого full green.
