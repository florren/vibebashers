# ADR-0025: GigaChat package balance and application usage

Status: accepted by project owner,2026-11-04 (PR #218 DDL/policy/rollout approval).

## Context

GigaChat Authorization Key can obtain OAuth and `GET /balance`. Balance returns
remaining packages, not historic token consumption. Requiring Studio history to
connect an unused reserve credential prevents normal rotation without a browser.
TZ §5.2 requires per-key application counters from inference `usage`.

## Decision

Keep provider availability and application consumption separate. An explicit
`connect-gigachat --confirm` reads a valid API balance and creates one durable
application origin only for a credential with no application attempts, confirmed
token floor or legacy token hint. Pre-origin provider history remains unknown in
private audit. Subsequent usage is app-scoped; configured numerical caps remain.
Reconciled credentials keep their existing basis. An origin cannot be recreated
to reset allowance, even after a provider restart, bank restore or UTC rollover.

Origin-backed GigaChat structured and streaming calls validate the selected
model's package before durable admission. Unknown/zero balance fails closed;
the structured/stream key pool can rotate without spending inference allowance on the
rejected key. Every actual HTTP inference retains the existing durable attempt,
shared profile cap and usage validation. Within one pool call, an admitted request
is not replayed on another key; the existing outer model/provider fallback policy
remains unchanged and retains separate ledger attempts. Missing usage, cancellation or uncertain
delivery remains unknown in audit; it never creates a new origin.

### Availability correction,2026-11-08

Project owner explicitly requires live functionality to take precedence over
incomplete local accounting. For an existing GigaChat application origin, an
unknown attempt does not permanently disable the credential. Every new physical
inference must first receive a fresh positive `/balance` for its selected model;
an error, missing package or zero balance still refuses admission and permits
rotation before HTTP inference. Other providers and legacy credentials without
an origin retain their existing reconciliation requirement.

The old unknown attempt, confirmed token floor, origin and daily request counters
are preserved. Successful new responses add their validated usage, without
pretending the old gap is known. A local token cap stops at its confirmed floor;
it cannot guarantee an exact ceiling across unknown usage. The provider package
is the availability boundary in this case; `tokens_remaining` stays unknown.
Reviewed reconciliation is optional for repairing historical totals, not a
runtime dependency of an otherwise available GigaChat package.

Structured PERS calls wait for the process-wide slot before starting their
generation deadline. GigaChat normalization receives30s per configured model,
instead of splitting10s into4/3/3s; other context/provider deadlines are unchanged.
Queue wait and model retries can exceed the normal latency target. Calls remain
cancellable, and a queue cancellation has no physical inference reservation.

The demo operator holds the clock/control lock only while committing its HITL
decision. Graph continuation runs after releasing that lock, as in the public
HITL route. Waiting for the agent semaphore or GigaChat must not freeze ticks,
Pause or Stop. Existing decision/current-run checks and transaction are retained.

`usage_known` retains its documented app-scoped meaning. Sources
`gigachat_api_balance_app_origin` / `gigachat_api_balance_app_observed` identify
the accounting period; UI labels it. Initial zero means no application attempt
since connection, never zero historical provider consumption. Provider balances
are not added across models and do not replace a local token cap.

## Limitations and recovery

This is preflight, not a hard cap against simultaneous external consumers or
provider top-ups/expiry. Package403 (including pay-as-you-go) cannot establish
availability. Unknown model packages are refused; no guessing future model IDs.
OpenRouter policy is unchanged. Existing private ledger and origin audit must
be backed up together; restoring bank data cannot restore quota.

Forward migration0021 adds only a private operational audit table. Code rollback
preserves it and all counters. Stop writers and take a backup before any explicit
operational recovery; never drop the table to obtain a new allowance.

## Sources

- https://developers.sber.ru/docs/ru/gigachat/api/reference/rest/get-balance
- https://developers.sber.ru/docs/ru/gigachat/tariffs/individual-tariffs
- `docs/LLM-RECOVERY.md`, `docs/reviews/T-050-api-balance-app-accounting.md`
