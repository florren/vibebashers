# T-161: фактический kind и исключение live

В frozen candidate `df01ed6` полный набор фаз дал:

- contracts: 45 схем / 162 OpenAPI paths;
- unit: 1715 passed / 18 skipped;
- integration: 423 passed / 18 failed / 4 skipped, 2589.93 s;
- scenarios: 43 passed / 2 skipped, 223.65 s;
- compliance: 31 passed, 106.88 s;
- frontend: 346 passed;
- fake tgbot: 33 passed, 5.28 s.

Это не успешный full regression. Логи `/tmp/t161-full-active-final.log`, `/tmp/t161-full-active-rest.log`. Artifact bounded SIGKILL proof и source hashes сохранены в `/tmp/t161-full-process-evidence`; он не доказывает восстановление произвольных активных World faults.

После завершения всех фаз обычными merge включены T240 `e8987a3` и main `73425c9`. Пять старых integration fixtures (два CSI FK, три счётчика 800 вместо фактических 1162) исправлены producer T240 без ослабления исходных проверок.

## Исправленная runtime граница

`Simulator` продолжает загружать configured policy по умолчанию. Новый `effective_policy` определяет применимость по **фактическому kind** строки run: только `free`/`scenario`. `live` и baseline не получают behavior owner. World creation, rollback, resume и reset_day используют ту же границу. Это исправляет нарушение уже утверждённого scope, а не отключает runtime или business rules/HITL живых входов.

Targeted повтор: 44 passed и два новых live-кейса первоначально упали на слишком широком ожидании неизменного RNG: штатный `TeamEmulator.tick` строит планы собственными draw (прежняя attribution к load была неточной). После явного разделения стадий оба новых кейса прошли: **2 passed, 15.28 s**. Graph identified/anonymous не меняет RNG; load сам не расходует RNG; в реальном simulation execution admission/clock не добавляет behavior draws; foreign owned state/hazard, legacy churn_risk, persisted RNG и отсутствие live behavior rows проверены точно. Семь исходных live-control regressions проходят, без изменения их assertions. Wall loop в новом fixture выключен через тестовый `_start_loop`, время двигается явным API вызовом.

Оставшиеся known failures: parallel20 closed-run sink (отдельная согласованная suppressed граница), новый client.* event family в тесте schema map, durable pending/owner RNG после успешного retry. Полный финальный regression и coverage после всех follow-up ещё впереди.
