# T-235: проверка записанных search/trace

CLI считал HTTP 501 успешной приёмкой. Кроме того, actual AS trace падал с
UndefinedColumn: `compliance_alerts` не содержит `run_id`. CLI теперь возвращает
ошибку для невыполненного сценария, scope алерта берётся через audio session.
API и DDL не меняются.

Checker выполняет 26 search и 17 trace GET, проверяет DTO по contracts, конкретные
kind/ref, скрытие tracking token и отсутствие raw contacts в title/snippet.
Discovery SQL работает в read-only транзакции; отсутствие любого префикса или
формата даёт явный FAIL. Остальные сценарии сохраняют прежний путь исполнения.

20 адресных unit/actual PG тестов прошли за 11.93s. Проверены CLI dispatch,
43 GET, отсутствие LLM, запрет INSERT в Trace и изоляция алертов по запускам.
Полный make test и CI ещё не заявляются.

Это промежуточная реализация T-235. Приёмка rich traces, веера, pending,
производительности, Playwright/export, ru/en × themes и DEMO-SCRIPT остаётся
незакрытой. На неполной БД checker завершится FAIL, не создавая недостающих данных.

Источник `c4d53ab`: новые исполняемые строки 97/100 (97.00%);
сам checker — 88/90 (97.8%). Показатели и hashes файлов сохранены в
`T-235-checkpoint-coverage.json`. Соседние search/trace regressions: 118 passed
за 1.55s. Первый sandbox запуск завис на TestClient и был остановлен;
успешный повтор выполнен без ограничивающего TestClient sandbox.

Следующий checkpoint добавляет два причинных следа с непустыми before/after,
pending для незавершённого инцидента и веер ≥120 сигналов. Fixture создаёт
120 повторов через normalizer; проверены 47 GET и прежние запреты записи/LLM.
24 адресных unit/actual PG теста прошли за 8.77s. Raw contact в отображаемом
тексте Trace также даёт FAIL. Coverage artifact выше относится к c4d53ab;
покрытие расширенного checkpoint будет пересчитано отдельно.

Добавлены меню сценария 13 и локальное скачивание загруженного Trace в JSON/Markdown.
JSON сохраняет scope и DTO; Markdown — ДО/ОБЪЕКТ/ПОСЛЕ, итог, pending и сводки
связей. Тексты экранируются от Markdown images и HTML. Backend теперь возвращает
422 до SQL для некорректных внутренних числовых refs и UUID не той семьи.
Проверено 46 unit/PG тестами за 7.79s, 329 frontend за 10.14s, frontend lint/typecheck
и обеими production builds. Browser proof, coverage после расширения, demo5000
performance и полный backend suite остаются следующими проверками.

Actual production UI proof на ae7141d: 10 вариантов legacy/v2 × ru/en × light/dark
и два mobile 320px. Проверены меню → поиск → before/center/after, реальные скачивания
JSON/Markdown, отсутствие horizontal overflow. Все 85 table fingerprints совпали;
0 browser external/nonGET/page errors/failed responses. SQL read-only включён;
структурированный LLM bomb и backend network guard не сработали. Это synthetic
fixture, не live bank. Screenshots/proof: docs/screenshots/T-235/. Owned preview
остановлен. Первый harness не дождался mount Trace перед hotkey; после явного
ожидания заголовка все 10 исходных assertions прошли. Никаких route mocks нет.

Постоянный CI regression `frontend/e2e/trace-journey.spec.ts` дополнен фактическими
JSON/Markdown downloads: 4 ru/en × themes cases passed за 7.2s на static production
frontend с явно mocked API. Он дополняет, не заменяет actual API/PG proof выше.
Проверен запуск новых unit tests из backend без PYTHONPATH: pytest явно включает
backend и repo scripts в import path. Команды и путь manifest исправлены в
источнике генератора карточек (`gen_tasks_v15.py`), а не только в сгенерированном
Markdown.

Штатный `make lint` после согласования imports с backend cwd завершился успешно:
329 frontend, Ruff/formatter 377 файлов, mypy 258 source files. Первое выполнение
выявило только порядок imports четырёх новых tests; он исправлен без изменения
assertions. Следующий gate — последовательный `make test` на отдельной БД.


## Финальная локальная проверка d1a4197

Последовательный `make test`: 1410 unit / 18 skip, 284 integration / 2 skip,
43 scenarios / 2 skip, 31 compliance; всего 1768 backend passed / 22 skip,
329 frontend passed. `make lint` зелёный: frontend lint/types/tests,
Ruff/formatter 377 файлов, mypy 258, drift 192/192. Runtime после этого source
не менялся. CI и merge остаются отдельными gate.

Финальное покрытие: 46 targeted unit/actual PG tests за 12.92s,
146/152 новых исполняемых строк (96.05%), hashes и строки в
`T-235-final-coverage.json`. Первый coverage-прогон остановился на setup:
системный pg_dump18 несовместим с PG16. Повтор с локальным PG16 client прошёл;
тесты/assertions не менялись.

Actual localhost HTTP benchmark на отдельном PostgreSQL16.15: demo5000,
600000 операций, PostgreSQL ограничен 4 CPU / 2GiB, API/client закреплены
на тех же четырёх CPU. 47 запросов проверены до замера, затем по25 повторов:
1175 timed GET, всего1222. Все47 p95 меньше300ms; худший132.993ms.
84 streaming table fingerprints совпали до/после; structured LLM и external
network guards не сработали. Seed включая dump занял22.509s. Детали по каждому
запросу: `T-235-demo5000-performance.json`. Это последовательный actor-free
замер после validation warmup, не доказательство задержек под активным Sim.
Временные API/PG остановлены; рабочая БД не использовалась.

Actual browser proof остаётся source-qualified ae7141d (10 вариантов), CI
Playwright — четыре mocked API cases; различие описано выше. Replay-корпус
с законченными native agent traces и нагрузка активного Sim остаются зависимыми
приёмочными условиями; карточка не закрывается фиктивно.
