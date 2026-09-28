# Startup status without a percentage

Startup previously displayed the fraction of three completed server milestones as a
percentage. Their durations differ, and polling can observe only the initial and final
states. A bar that jumps from 0% to 100% gives an unreliable impression of remaining work.

The composer now shows the current startup message with a small indeterminate indicator.
It has no percentage, track, simulated progress, or minimum display delay. Reduced motion
keeps the indicator static. Startup errors retain an alert and the existing Retry action.
The status disappears as soon as readiness succeeds.

Only frontend presentation and unused percentage state change. The server response contract,
automatic readiness checks, polling schedule, cancellation, account isolation, telemetry,
draft handling and generation requests retain their existing behavior. No backend release,
database migration or paid generation evaluation is required. Reverting the frontend change
restores the previous display.

## Verification

Frontend lint, the full 490-test suite with coverage, TypeScript/build and dependency audit
passed. The audit found zero vulnerabilities. The existing Node test-runner warning about
experimental localStorage remains unrelated to this change. The release-policy suite
passed 368 tests with five environment-dependent skips. Manifest validation and diff checks
passed. Impeccable detection reported no findings for the changed composer source and CSS.
Independent source review confirmed that startup lifecycle and generation behavior are unchanged.
The exact runtime file revisions are recorded in ci/quality.json.

The production build, with auth/readiness bypasses disabled, ran against isolated startup
and history fixtures at localhost:5202. At 1440x960 and 390x844, pending startup showed
compact status text and a spinner without a percentage, progressbar or horizontal overflow.
Reduced motion computed animation: none. Failure showed an alert and Retry without a
spinner. Recovery preserved the draft and loaded history; reload performed fresh readiness
checks. The parent inspected the desktop, mobile and error screenshots. No source corrections
were needed after this inspection.

There were zero generation calls, unexpected network requests or JavaScript page errors.
These fixtures establish presentation and recovery behavior, not real backend cold-start
speed. Evidence is retained locally in work/startup-status-verification, including scripts,
result.json, bundle hashes and screenshots. The tested base is
0e3ab01a899f2d7bb0b50ced3baff27189cf1efe with the runtime blobs recorded in the manifest.
