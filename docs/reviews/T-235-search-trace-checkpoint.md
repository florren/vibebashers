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
