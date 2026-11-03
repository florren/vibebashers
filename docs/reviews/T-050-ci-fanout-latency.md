# P2 PR188: диагностика Trace latency без изменения runtime

На head `d99b8569426a400bb013839ac9c8d645a3c2550e` [backend shard3](https://github.com/florren/vibebashers/actions/runs/41452304960/job/125300930611) завершился с454 passed/1 skipped/1 failed. Единственный failure — `test_trace_fanout.py::test_large_fan_page_latency_and_bounded_response`: p95=305.900601ms при неизменном пороге300ms. Assertions HTTP200, total10001,50items/50edges, response<100KB и peak<8MiB прошли. Это не подтверждение полного green CI и не accounting/ledger traceback.

## Проверенное сравнение

Созданы отдельные checkout/venv/синтетические scratch БД для exact P2 `d99b856` и parent `b85d377`. Неизменённый тест с10 запросами прошёл на обоих: P2 p95=55.02ms (21.09s весь тест), parent56.52ms (21.06s). В обоих сохранены все исходные assertions; реальные LLM/Telegram/email не вызываются. Trace API/store/fanout, main, maintenance, backend uv.lock и CI на сравниваемых head byte-identical.

Отдельный диагностический probe, не подмена acceptance run, измерил stages: page fetch≈40ms, count≈2.5ms, projection<1.2ms, connect≈4–5ms на обеих версиях. Manual actual read-only `EXPLAIN ANALYZE BUFFERS` текущего page SELECT:0.253ms,10shared hits/0reads, без JIT. Проверенный SQL candidate с bounded-page materialization вернул те же51 строки, но0.287ms и не показал преимущества; он НЕ внедрён. Эти локальные измерения не воспроизводят условия CI runner и не доказывают причину305.9ms.

Полные samples, source SHA, stage medians и plan summary: [JSON](T-050-ci-fanout-latency.json). Runtime, схема, лимиты, cache semantics и assertions не менялись. Нельзя называть регрессию исправленной или объявлять failure случайным без дополнительных данных. Следующий обязательный шаг — обычная композиция main/parent и exact-head полный CI с тем же300ms; при повторе этого failure — дальнейшее stage/runner расследование.
