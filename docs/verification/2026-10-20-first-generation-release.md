# First-generation release verification

## Scope

PR 84 refreshed against main cde8b6095369f0f8ac1731fbf77e6e1ffe7bfa75. The previous branch head was f23f3d2b6e87a1804cc58d3ea14e8d0fdcc93bc7. Runtime source was frozen before the final local data-query request and backend coverage run. Final commit identity and protected evaluation results are recorded by PR checks.

AI, ML and data requests default to diagrams, with an explicit text-only opt-out. Unhinted applied requests start at prototype maturity; explicit production requirements retain production treatment. Existing graph edits retain their maturity. Review budgets and validation gates remain unchanged.

The latest three public work updates remain visible while a request runs. Actual nonempty provider activity refreshes the active operation at most once every five seconds. The client receives fixed operation names and elapsed time. Provider reasoning and content are never forwarded through activity events. Full history remains expandable; completed activity starts collapsed.

Sources are collapsed and inline citations open the matching source. Single-version controls and the supporting description row are absent. Existing heading wrapping, header padding and sidebar resizing are preserved. Component previews use role labels rather than pending-contract text.

## Concurrency

Real Postgres tests reproduced a lock cycle between the profile owner lock and a message insert's foreign-key check. Three owner mutex reads now use FOR NO KEY UPDATE. This still serializes retention and permits foreign-key KEY SHARE reads. Thread locks and graph compare-and-set checks remain in place. There is no schema migration.

Five new real-Postgres cases cover stale graph revisions, duplicate completion, message adjacency, the deterministic deadlock interleaving and retention versus stream registration. The old lock mode fails the deadlock regression. Test URLs require loopback hosts and reject query strings and fragments. CI starts an isolated Postgres container for affected storage groups and cleans it up afterward.

## Offline evidence

- Final backend coverage: 5,074 passed, zero skipped, 92% coverage, with real Postgres enabled. Existing dependency deprecation warnings remain.
- Frontend canonical suite after integrating main: 719 tests in 46 files passed; coverage, lint, types, production build and dependency audit passed with zero audit findings.
- After the live-trace changes: 33 indicator tests and 93 stream-hook tests passed, along with scoped lint, types and the final production build.
- CI policy checks: 504 passed with five local capability skips; manifest validation and shell syntax checks passed. Actionlint and shellcheck were unavailable locally.
- Independent integration review found no blockers in progress privacy, cancellation, ordering, disclosure behavior, maturity selection or Postgres locking.

Full backend coverage was justified by shared stream, activity, storage and CI changes. Passing focused checks were reused where their inputs remained unchanged.

## Fresh local generation

Development authentication and local SQLite storage were used. Providers were real, with existing model settings, review budgets and call limits. No production database was accessed. Provider credentials were held in subprocess memory.

| Request | First component render | Connection phase | Total | Result |
| --- | --- | --- | --- | --- |
| How do I build a Snowflake Cortex agent? | 46.5s | 91.7s | 132.4s | 14 components, 39 connections; saved answer and graph |
| Build a data querying AI agent. | 24.4s | 59.1s | 116.3s | 10 components, 20 connections; saved answer and graph |

The data-query run used the final runtime source and completed one bounded connection revision. Nine provider operations completed with no errors, fallbacks or queue wait. Two messages persisted and active stream records cleared. Browser inspection confirmed the final diagram, answer, collapsed sources and completed activity. During generation, recent work stayed visible while the full log was collapsed, including observed drafting and review updates. Browser errors were empty. Snowflake history reopening restored the saved diagram and answer.

These are individual observations, not latency guarantees. A baseline automatic production-maturity Snowflake run was stopped after 473.8 seconds while still reviewing. It is not counted as a successful generation.

Local evidence is retained in ignored work/pr logs and JSON summaries. Protected exact-tree CI and fresh live evaluation remain required before merge. Earlier PR checks do not approve this refreshed source tree. Deployment and production verification are recorded by the release workflows and PR.

## Rollback

Revert application commits and redeploy the previously approved artifacts. No data migration or irreversible storage change is part of this release. Preserve compare-and-set and message-ordering guarantees when reverting related runtime code.
