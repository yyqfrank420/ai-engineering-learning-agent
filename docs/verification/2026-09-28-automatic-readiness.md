# Automatic startup readiness

Refreshing the deployed site previously reset browser readiness to unknown and required
another Prepare click before chat history could load. The authenticated workspace now
starts the existing readiness check automatically. Server milestones remain visible;
a failed check stops polling and offers Retry. The composer preserves a draft through
startup and retry.

The readiness hook cancels its timer and request on teardown, user change, or explicit
cache clearing. Attempt identity rejects late responses even if cancellation is ignored.
Polling stays sequential. A refreshed token for the same user does not restart work.
StrictMode effect replay and A -> B -> A account transitions have regression coverage.
Automatic checks record success or failure; only a user retry records prepare_clicked.

## Scope and release checks

This change affects authenticated startup and its controls. The only API-client change
forwards an AbortSignal to GET /api/prepare. Generation payloads, intent classification,
model settings, provider calls, graph validation and private rendering are unchanged.
An independent review confirmed this scope. The exact before/after frontend Git blobs
are recorded in ci/quality.json; later edits to these modules remain protected by the
normal classifier. Paid generation tests do not exercise the changed behavior.

Frontend lint, 490 tests with coverage, TypeScript and dependency audit passed. The audit
reported zero vulnerabilities. A scoped effect-lint exception documents the synchronous
startup state reset required when a new account starts network preparation. Deriving
that state from an older result would expose stale readiness during A -> B -> A changes.
Impeccable's detector reported the existing milestone progress width transition; this
change retains the server-reported progress bar and introduces no new animation.

No database migration or backend release is required. Reverting this frontend deployment
restores the previous startup behavior.

## Browser verification

The current production build ran at localhost:5202 at 1440x960 with both development
auth and evaluation bootstrap disabled. An isolated fake persisted session and stubbed
readiness, analytics, and thread endpoints exercised the real App. Initial startup and
reload each performed a fresh three-poll readiness sequence, loaded history, and allowed
a saved lesson to open without Prepare. A failed startup showed Retry, made no automatic
retry, and recovered with the draft intact through first-thread initialization. There
were zero generation requests, unexpected external requests, or JavaScript page errors.
This verifies startup behavior; it does not measure a real backend cold start.

The release-policy suite passed 366 tests with five environment-dependent skips, and
manifest validation passed. The tested source starts from main 29847b3f300f81cddedd2a987bc418edbd7a7cf5;
the exact changed runtime blobs are recorded in the manifest.
