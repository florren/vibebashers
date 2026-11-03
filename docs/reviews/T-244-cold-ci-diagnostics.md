# T244: диагностика cold cabinet report после CI202

## Установленные факты

CI202 на source `05ee8c0b967ad776cebde7dfebb385cafe9495ba` завершился
678 passed / 20 skipped / 1 failed. Единственное падение в job
[`125649407511`](https://github.com/florren/vibebashers/actions/runs/41554335068/job/125649407511)
— `test_cold_report_preserves_links_without_repeated_scans`:
`411.76389999998264 < 300` неверно. До проверки p95 уже прошли проверки native
incident links/deadline, неизменности fingerprint, NULL `last_analyze` /
`last_autoanalyze` и budget ActualRows × ActualLoops. Старый квадратичный SQL plan
этим падением не подтверждён. Причину нельзя объявить исправленной или назвать
flake без дополнительных данных.

[CI204](https://github.com/florren/vibebashers/actions/runs/41555015079) на source
`d3cf4eb7945aa57ac199ed07594d9b824055ee3a` прошёл; все backend shards успешны.
Production modules отчёта, cold test, DB contracts, uv.lock и workflow для отчёта
byte-identical между `05ee8c`, `d3cf4eb` и `3e9e592`. Новый cached loader runtime
OpenAPI version не меняет hot path отчёта. Green CI204 не доказывает performance
fix. Численные samples и план старый CI не сохранял в загружаемый artifact:
файл оставался в pytest tmp_path, а upload берёт `test-results/`.

## Собственное воспроизведение

Отдельная ветка `codex/fix-cabinet-cold-regression` создана от exact
`3e9e592c76fab404ab02cbd727daa07a0b7f00db`; native T020 сюда не переносился.
Использованы собственная scratch DB `cx_cabinet_cold_revision_20261103`,
PostgreSQL16 / port55439 и отдельное offline frozen uv environment.
Реальных LLM / Telegram / email / production вызовов нет.

До изменения теста в согласованном quiet окне исходный cold test прошёл:
1 passed / 39.68s. Для 30 HTTP samples: p95 = 155.802709ms,
min = 145.028686ms, max = 307.992613ms; 2813 signals.
SQL Execution Time captured signal query = 19.607ms. Сохранены NULL stats и
fingerprint. Лимит 300ms, 30 samples, fixture 5000 clients и assertions исходные.
Proof: `/tmp/cabinet-cold-current-proof/test_cold_report_preserves_lin0/cold-report-proof.json`.
Это не объяснение CI411 и не обещание результатов другого runner.

После измерения без tracer отдельно снят instrumented stage/cProfile;
эти значения не считаются latency acceptance. Response — 1799610 bytes;
overview ~22.48ms, signals ~66.17ms (fetch_all ~21.87ms,
process CPU ~55.16ms), bounded_json ~12.8ms. Вложенные времена нельзя суммировать
как независимые. Python mask/regex и JSON заметны, но конкретный CI bottleneck не
доказан. Продуктовая оптимизация по этой гипотезе не выполнялась.

## Минимальный patch

Меняется только integration test. После исходного measurement window формируется
прежний safe proof с samples / EXPLAIN / stats / fingerprint / count плюс
sample_count, min, p50, p95, max и response_bytes. Тот же JSON остаётся в tmp_path
и копируется в ignored `test-results/cabinet-signals-cold.json`, который existing
upload artifact уже берёт. Assert message содержит квантили / bytes /
SQL execution и путь artifact.

Новых HTTP / SQL / ANALYZE / warmup или таймеров внутри measurement window нет.
Left-hand p95 expression, строгий лимит 300ms, 30 requests, SQL work budget,
links / deadlines, fingerprint и NULL stats checks сохранены. Response body,
контакты и ключи не пишутся; план получен только из fresh synthetic fixture.
CI aggregator читает только `manifest-*.json`, поэтому дополнительный proof не
подменяет collection или evidence.

Root read-only review — без замечаний; Ruff / format теста GREEN. Quiet повтор
после patch и source-qualified proof будут добавлены ниже. Production runtime,
API / DDL, функциональные acceptance и статусы T244 / T020 не меняются.
Это diagnostics, а не product performance fix.

## Проверки после patch

В отдельном согласованном quiet окне исходный тест после diagnostics patch прошёл
1 passed / 36.47s. Для тех же 30 samples: min = 136.945654ms,
p50 = 139.425938ms, p95 = 144.533006ms, max = 146.471366ms.
Response — 1799610 bytes; 2813 signals; SQL Execution Time = 18.252ms.
Нативные связи, deadlines, неизменность fingerprint, NULL stats и work budget
прошли. Это ещё одно локальное наблюдение; оно не объясняет CI411 и не считается
ускорением продукта этим patch: runtime не менялся.

Проверено побайтовое равенство tmp proof и CI artifact, точный набор безопасных
ключей, 30 samples и исходная p95 formula. JSON содержит метрики и план, без
response body. Файл игнорируется Git. Source hash и безопасные результаты:
[T-244-cold-ci-diagnostics-proof.json](T-244-cold-ci-diagnostics-proof.json).
Ruff / format прошли; contracts_check: 48 schemas / 167 OpenAPI paths.
Полный backend / frontend suite не повторялся: production code не менялся.
