# T-161: полный integration и два конкретных follow-up

На frozen `9bba1d9` выполнен весь `backend/tests/integration` с explicit own synthetic `cx_behavior_revision`, Mock/offline, PostgreSQL16: **469 passed / 2 failed / 4 skipped, 2752.16 s**. Лог `/tmp/t161-native-fault-final-integration.log` сохранён; source во время прогона не менялся. Это не successful full regression.

## Подтверждённые причины

1. Actual `TwinService.react` работает внутри `conn.transaction()` на соединении `autocommit=True`. Проверка `current_effect_time` ошибочно отвергала такой connection flag, хотя фактический status был `INTRANS`. Guard теперь принимает существующую explicit transaction; вне transaction autocommit по-прежнему отвергается **до SQL/эффектов**. SHARE/current/kind/status/native-clock границы не меняются; commit в helper не добавляется. Добавлен actual PG positive/negative regression с `dict_row` и неизменными clock/RNG/current pointer.
2. `test_information_request_gets_team_result_only_in_explicit_demo` создавал новый run напрямую test helper **после** загрузки `app.sim`, обходя production `sim.control`. Намеренный stale guard верно отказывал старому reader. Fixture теперь явно вызывает `sim.load_state()` после этого test-only внешнего create; обычный info_request по-прежнему не создаёт incident, explicit demo обязан получить closed incident и resolved notification. Assertions, production guards и current pointer writer не ослаблены. Production `run_scenario` использует `sim.control`, не этот обход.

Оба исходных failures + новый transaction regression: **3 passed, 19.05 s** (`/tmp/t161-full-findings-focused.log`). Все affected effect-time/Twin/repeat/inactive/demo-live модули: **24 passed, 142.56 s** (`/tmp/t161-full-findings-affected.log`). Повтор всего 45-минутного integration не объявляется выполненным; exact final composition CI остаётся обязательной.

Отдельный T037 candidate `56e62b9`/docs `558227d` из другого checkout имеет собственные scoped PG/OS/clone/coverage и sequential scenarios/compliance proofs. Эти результаты не приписываются этому T161 runtime head. Новые event/legacy recovery и reset_day/financial timestamp границы по-прежнему требуют уже описанного concrete final human review. Утверждённые demo-policy/variant A повторно не согласуются и не менялись.
