# T-050: API balance / app-scoped reserve accounting

## Concrete review boundary

- DDL0021 adds `llm_runtime.gigachat_app_origins`, outside bank baseline.
- Explicit CLI `connect-gigachat --confirm` performs OAuth/balance only, no
  inference. It admits a previously unused reserve credential without Studio.
- Unknown provider history is saved as unknown. Confirmed application usage
  begins at connection; `tokens_used=0` means no app attempts in that period.
- Existing known counters, legacy token hints and any previous wire attempt
  prevent establishing a new origin. Idempotent reconnect cannot reset counters
  or clear unknown attempts. Key/profile request floors are preserved.
- Origin-backed GigaChat calls check the selected model package before admission;
  zero/absent/malformed/inaccessible package does not spend inference RPD.
- Session `usage` stays in the existing durable ledger. Streaming and structured
  paths share accounting. Unknown response usage still blocks further calls.
- Numerical limits, prices, bank money, formulas and HITL do not change. The
  new reserve cap is explicitly application-since-origin; old reconciled keys
  retain their original basis. This semantic distinction is the policy change.

No credentials, account exports or operational dumps are committed. The provider
source is authenticated API, not an open browser session. Existing broad user
authorization covers development, testing, PR and merge; AGENTS §5.1/§7 requires
final human review of this concrete DDL/budget basis before rollout.

## Validation

Targeted PG composition checks connect, shared profile counters, usage after
restart, streaming, unknown results, package refusal and native key rotation.
Unit checks validate package data and supported model mapping. Full PR CI and
bounded ordinary live inference on the exact reserve credential are final gates.
Local checks:2229unit/19skipped,193PG/provider composition,583frontend (Node22),
Ruff/strict mypy329,contracts48schemas/167paths,i18n2326,frontend lint/types/build.
New statement execution147/152=96.71%. Actual component fixture checked in
ru/en×light/dark; synthetic metadata only. Evidence stays private under
`.runtime/gigachat-app-{ru,en}-{light,dark}.png`, not production/live proof.
Completed commands and full CI results are recorded in the PR/task report.

## Rollout / rollback

1. Private backup of `llm_runtime`; apply forward0021 with no data rewrite.
2. Deploy matching code, explicitly connect reserve once, inspect source/status.
3. Run one bounded synthetic request pinned to reserve; verify known usage,
   durable attempt and shared counters. No fallback is accepted as success.
4. Test the ordinary consumer and retain private evidence, without publishing
   raw provider/accounting data. Run full exact-head CI before merge.

Rollback stops new callers and restores previous code, preserving0021 and all
operational counters. No automatic SQL downgrade or quota reset. If an inference
becomes unknown, capture state and reconcile; do not repeat connect to bypass it.
