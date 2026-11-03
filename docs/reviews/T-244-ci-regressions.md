# T-244 / PR196: strict fixture и allocations большого отчёта

Runtime fix: `734c8a7c6ea39582ec5edac7e5c9bd00af11f784`. Контракт API1.5.26, деньги/HITL, scope policies и DDL не меняются. [Доказательства, samples и actual plans](T-244-ci-regression-proof.json). [PR196](https://github.com/florren/vibebashers/pull/196).

## Исторические failures

CI target `9e0f8c017c838da8267c6132eb242ce572f3b8e2`, checkout merge `34520ad` поверх ancestor base T242 `5b34a5f`:

- Job 125467437140: `test_demo_report_p95_includes_first_get` — p95=380.888ms при неизменённом300 мс threshold; 545 passed / 2 skip / 1 failed.
- Job 125468283953: report navigation test ожидал403, получил200;132 passed / 1 failed.

Исходные logs сохранены локально, SHA256 в proof; failures не объявлены «flake» и не удалены из истории.

## Strict visibility

Backend правильно использует default `cabinet.visibility=soft`: это presentation preset, не RBAC. Старый report test предполагал strict, но не задавал его. Actual production Mock/API red proof: явный soft fixture + snapshot старого 9e теста →Expected403/Received200 за 820 мс.

Исправление только в test fixture: получить actual catalog и effective visibility (учитывая dotted override), явно включить strict при необходимости, проверить direct backend403 с manager/bound-line headers, затем actual browser navigation403 и отсутствие report/PDF. Все browser report requests дополнительно проверяют реальные X-Cx-Role/X-Cx-Product-Line. Finally возвращает прежнюю effective visibility; setup/cleanup request-context PATCH отделён от browser read-only phase. Soft policy не превращается в strict по умолчанию. Cabinet.spec.ts не изменён.

## Причина локального performance failure и fix

Тот же collection 56 CI-shard0 modules, только selected report case, fresh demo5000 / 2813 signals:

- До fix diagnostic p95=320.064ms, median 146.685 мс. Request9=320.064ms содержит gen2 pause 172.582 мс; request23=321.456ms содержит 169.537 мс. Остаток без этих наблюдённых пауз 147.482 / 151.919 мс. Actual SQL plans 4.47–22.22 мс, JIT отсутствует; прежняя quadratic SQL проблема не вернулась.
- Это доказанный механизм локального воспроизведения. В исходном CI 380.888 мс callbacks не было: точная доля GC в CI не утверждается.
- Python-only immutable empties снизили gen0 cycles 495→384, но p95 ещё 307.254 мс: этот неуспешный промежуточный candidate также сохранён.
- Финальная 16-field projection использует NULLIF пустых flags/red_words до psycopg decode. Read-only rows переиспользуют immutable empty tuple вместо новых списков; наружу по-прежнему JSON[]. Убрано 8035 retained empty mutable arrays; GC-tracked row dicts 2813→713 на тех же 2813 строках. Никаких gc.disable/collect/freeze/threshold changes, SQL warmup/ANALYZE/retry или изменения 300 мс gate.
- После fix diagnostic p95=152.524ms, median 146.518 мс, gen0 cycles 495→194 / gen1 45→17 / gen2 0 в 30 запросах. Число запросов/окно/данные не уменьшены; первые GET включены.

Явная projection сохраняет все прежние 16 полей view, а не скрывает данные. Потребители helper — только cabinet API и report reader. Совместимость проверена реальным HTTP: JSON 1800375 bytes **побайтно идентичен**, SHA256 `2c838375d36636e516046ebeb3737585753b6b94b949f7a666ea058646d964fe`; все values семи XLSX sheets **exact-identical**, SHA256 `307f40e7c8ebd530501e0db0dc7c590e6fc3d8f998c9d22c5825ea24daec0fd7`. Денежная формула, exact-money strings, privacy masking и export limits не меняются.

## Проверки

- Без diagnostic hooks/coverage: **125 passed / 483 deselected за 259.68 с**, collection содержит все 56 CI-shard0 modules и affected modules. Выполнены прежние native p95 guards, cold-stats regression, JSON/XLSX agreement, scope/privacy/native SLA и audit migration checks; остальные 483 теста не объявляются выполненными.
- Последующий test-only assert явно проверяет публичные flags/red_words/incidents как JSON arrays. Вместе с helper coverage: **6 functional PG passed / 62 deselected**, 32/32 helper statements (100%). Timing tests не запускаются под tracer; штатные thresholds/CI assertions сохранены. Python coverage tracer warning отделён от native measurements.
- Production Playwright **5/5 за 7.2 с**, включая direct/UI403 и actual headers. Обе production builds прошли; frontend/src byte-identical 9e→734, UI-код не менялся.
- Full make lint: **421 frontend tests / 59 files**, Ruff 463 backend files, mypy 295 backend files, bot 11 format / 5 mypy, drift 193 methods, EXIT0.
- Contracts 45 schemas / 163 paths; gen_tasks два последовательных запуска unchanged; regenerated TS byte-identical. Diff check чистый.

Exact-head CI после push остаётся обязательным gate. Исторический полный прогон 3f42 не переносится на этот source. Rollback — отдельный app revert, новых DB migrations/writes или денежного rollback нет. Собственные preview/БД и Mock-only подготовка отделены от production; внешние LLM/email/Telegram не вызываются.
