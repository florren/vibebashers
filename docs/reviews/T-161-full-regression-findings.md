# T-161: полный integration и два конкретных follow-up

На frozen `9bba1d9` выполнен весь `backend/tests/integration` с explicit own synthetic `cx_behavior_revision`, Mock/offline, PostgreSQL16: **469 passed / 2 failed / 4 skipped, 2752.16 s**. Лог `/tmp/t161-native-fault-final-integration.log` сохранён; source во время прогона не менялся. Это не successful full regression.

## Подтверждённые причины

1. Actual `TwinService.react` работает внутри `conn.transaction()` на соединении `autocommit=True`. Проверка `current_effect_time` ошибочно отвергала такой connection flag, хотя фактический status был `INTRANS`. Guard теперь принимает существующую explicit transaction; вне transaction autocommit по-прежнему отвергается **до SQL/эффектов**. SHARE/current/kind/status/native-clock границы не меняются; commit в helper не добавляется. Добавлен actual PG positive/negative regression с `dict_row` и неизменными clock/RNG/current pointer.
2. `test_information_request_gets_team_result_only_in_explicit_demo` создавал новый run напрямую test helper **после** загрузки `app.sim`, обходя production `sim.control`. Намеренный stale guard верно отказывал старому reader. Fixture теперь явно вызывает `sim.load_state()` после этого test-only внешнего create; обычный info_request по-прежнему не создаёт incident, explicit demo обязан получить closed incident и resolved notification. Assertions, production guards и current pointer writer не ослаблены. Production `run_scenario` использует `sim.control`, не этот обход.

Оба исходных failures + новый transaction regression: **3 passed, 19.05 s** (`/tmp/t161-full-findings-focused.log`). Все affected effect-time/Twin/repeat/inactive/demo-live модули: **24 passed, 142.56 s** (`/tmp/t161-full-findings-affected.log`). Повтор всего 45-минутного integration не объявляется выполненным; exact final composition CI остаётся обязательной.

Отдельный T037 candidate `56e62b9`/docs `558227d` из другого checkout имеет собственные scoped PG/OS/clone/coverage и sequential scenarios/compliance proofs. Эти результаты не приписываются этому T161 runtime head. Новые event/legacy recovery и reset_day/financial timestamp границы по-прежнему требуют уже описанного concrete final human review. Утверждённые demo-policy/variant A повторно не согласуются и не менялись.


## Frozen runtime70e4b00: актуальные дополнительные доказательства

- Full unit: **1725 passed /18 skipped,96.45s** (`/tmp/t161-runtime-final-coverage-tests.log`, первая завершённая pytest session).
- Fresh single pytest invocation: пять pure behavior unit modules + все семь behavior integration modules: **167 passed,357.70s** (`/tmp/t161-runtime-package-coverage-tests.log`).
- Весь новый `app/sim/behavior` package: **1657/1772 executable lines,93.51%**; по модулям90.12–100%. Это line coverage, не branch coverage; source SHA256 и missing lines сохранены в [coverage JSON](T-161-runtime-package-coverage.json). Процент раннего proposal checkpoint не использован.
- Обновлённый bounded OS SIGKILL/restart aggregate: [proof](T-161-runtime-process-final-proof.json). Исходные raw wall-clock hashes сохраняются; разрешённая нормализация ровно declared `review.posted.posted_at` проверяет равенство native timestamp и wall bounds.

Первая версия coverage harness ошибочно вызвала `pytest.main` дважды в одном процессе. После успешного unit cached structlog PrintLogger ссылался на закрытый global capture stream первой session;13PG failures были `ValueError: I/O operation on closed file` в logging Simulator.load_state. Эту прерванную PG попытку и её trace в финальное покрытие **не включали**. Fresh one-invocation прогон выше прошёл; source не менялся.

**Known whole-World gap до отдельного T037:** этот T161 proof не сохраняет RAM-план TeamEmulator до первого due team_action; из-за этого нельзя заявлять универсальную restart-equivalence World/global RNG на T161 в одиночку. T037 source56e62b9/docs558227d реализован отдельным child candidate с native plan/RNG commit boundary и собственными OS/clone/coverage proofs. Корректная публикация — отдельные stacked PR T161→T037 и итоговая проверка композиции; atomic exception не вводился.

Конкретные event/legacy fail-closed, reset_day и financial-time изменения всё ещё требуют final human review. Исходные policy values и variant A уже одобрены; permission на внешние LLM/TG или рабочую БД не получалось и не использовалось.


## Проверенный direct parent P2

Обычный merge P2 `25852b83807f84ec9a9897f806cc7b38ff004c9c` в T161 дал runtime head `cd102579cd2e32221bf1902124458ec1b0550ce1`. Конфликт был только в schema tail: сохранён нормализующий P2 DROP DEFAULT **перед** полным actual0017. Обе schema mirrors совпадают. Source ветки P2 не менялся.

Все **11 behavior source blobs** побайтно совпадают с coverage70e; [parent proof](T-161-parent-composition-proof.json). Штатный `make sync-contracts` создал110ORMклассов и актуальные API types без tracked diff. На этом head: **T23546 passed/10.10s**, актуальные effect-time/Twin/owner/inactive/fault/causality/atomicity guards **55 passed/314.39s**. `make lint` зелёный, включая **366 frontend tests/47files**, backend472Ruff/297mypy, tgbot12Ruff/5mypy, drift192/192. Один унаследованный ESLint warning в DemoMenu,0errors. Contracts45schemas/162paths; licenses550+36.

Полный45-минутный integration на этом head не повторялся; прежний469/2F/4skip не переписан в green. Main364c4fd намеренно не включён по согласованной последовательности stack. T161 публикуется отдельно от T037; final exact CI и concrete human compatibility/financial-time review обязательны. Следующий receipts B packet0019/API27 зависит от0018 и не входит в эти PR.
