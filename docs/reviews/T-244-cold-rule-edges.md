# T-244: cold rule-version query performance

## Observed failure

Main CI41793839760, backend shard3 job126453171465: one failure,
`test_cold_report_preserves_links_without_repeated_scans`. Report p95=371.295ms
against unchanged300ms limit, min356.245ms, response1799610bytes. Other835tests
in that shard passed. The reported26.314ms SQL duration covered only the signal
list query; the test did not inspect the report rule-version query.

## Root cause and focused fix

Isolated PG16/demo5000, signals stats absent (autovacuum disabled only in the
existing scratch fixture): actual rule-version plan joined400incidents with
all2813signals in their run, producing1125200intermediate rows before checking
`incident_signals`. Full pytest collection reproduced that work amplification.
The facts query measured258.874ms in EXPLAIN; JSON serialization median10.4ms.
This is not resolved by retries, SQL warmup, ANALYZE, GC settings or a raised gate.

`selected_edges AS MATERIALIZED` retains the actual incident/signal/run triple
before the rules lookup. Rule-version input predicates remain equivalent:
selected incidents, same run, signal time window/product line, existing signal
view/proactive exclusion, and recorded evaluation run. No current rule version
is substituted for a stored version. Wire fields, money/exact strings, privacy,
scope, limits, DDL, LLM routing and financial formulas do not change.

## Regression and measurements

- New native work-bound regression is RED on the old source and GREEN on the
  candidate. It checks every EXPLAIN node's actual rows×loops, without prescribing
  a join type; no ANALYZE/statistics manipulation and all public fingerprints
  remain unchanged during GET.
- Existing30-sample cold HTTP test, first GET included, remains unchanged:
  candidate p95=117.612ms,1799610bytes. Facts EXPLAIN4.307ms; maximum node
  work2813 versus old1125200, work budget10000.
- Added actual saved-version901 / foreign-run902 projection regression for both
  current and all. Full native report/API/lifecycle/cold suite:72PGpassed/237.19s, including
  JSON/XLSX/exact-money/scope/privacy/read-only regressions.
- Unit report text/scope56passed; strict mypy329sourcefiles passed.

Diagnostics are separate from native timing checks. Full CI is required before
merge; the previous green PR218 CI does not invalidate the later main failure.
Private logs and detailed synthetic plans remain under `.runtime/` and CI
`test-results/cabinet-report-rules-cold.json`. No production data or credentials
are included in the diff.

## Rollback

Revert this app-only SQL optimization through a separate PR if necessary.
There are no migrations, configuration changes, writes or external calls.
