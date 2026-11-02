# T-161: активация проверяемого candidate

В собственной ветке `enabled` переключён в `true`, `runtime_loader` указывает на реализованный `app.sim.behavior.runtime.configured_policy`. Это не публикация и не изменение production: окончательная готовность зависит от full regression, coverage, CI и review конкретного diff. Особая семантическая граница `reset_day` описана в [admission checkpoint](T-161-admission-reset-day-checkpoint.md).

Машинный deep diff подтвердил: в policy изменены только `enabled` и `runtime_loader`; все утверждённые числа, источники, predicates, scope и approval metadata неизменны. В пересчитанном sensitivity JSON изменены только `enabled` и hash файла, все расчёты и catalog hashes побитово эквивалентны прежним значениям. Offline sensitivity generator допускает включённый утверждённый пакет, но не включённый draft; это не доказательство runtime результативности.

На composed базе main `db1f73c`, P1 `2b11bc5`, focused T121 lease `7132aad` проверены **39 tests, 72.23 s**: policy/codec, owner admission/timers/reset_day и lease-before-FK-metadata. Лог `/tmp/t161-active-admission-composed.log`. Следующий P1 checkpoint `10a2dd5` и main `0e64802` ещё не входят в это утверждение.
