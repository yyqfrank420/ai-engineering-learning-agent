# Startup time copy verification

Verified 2026-09-30 on `codex/startup-time-copy`, based on `a083406f6c8e8ea5812ac8c90d698f80751c72e9`.

The initial message changes to "Starting the service… usually takes 30-60 seconds". The hook changes only this literal. Polling, lifecycle, retry and generation behavior are unchanged.

The existing exact presentation record identifies before blob `a47bc08f43ba5dcd84b310e5066ce5a2b10de30d` and after blob `a2e5551ae749d2037bcd9694379074eb8c060d75`. No other policy records changed.

Canonical local checks passed:

- Frontend: lint, 571 tests across 43 files, coverage thresholds, TypeScript/production build, and audit with zero vulnerabilities.
- Pipeline policy: 388 passed, five local Bash-version skips, manifest validation passed.

A scratch Chromium harness imported the current hook and ChatInput directly, with a fake local session and intercepted readiness responses. Desktop 1440x900 and mobile 390x844 verified the exact pending copy, disabled Send, replacement by the server milestone, and ready completion with the draft preserved and Send enabled. Both screenshots were inspected; neither width overflowed. Each journey made two readiness requests, with no browser errors or external requests. No permanent fixture or mirror test was added.

Evidence remains in the parent workspace at `work/startup-copy-verification`. These controlled UI checks do not measure production cold starts or guarantee a startup duration. No paid generation calls were needed.
