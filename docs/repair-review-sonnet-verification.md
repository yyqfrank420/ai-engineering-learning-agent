# Repair review and Sonnet 5.5 verification

## Changes and limits

A repair review now receives the prior validated rule evidence and the exact candidate changes. It still returns every current rule, and the server derives admission from that current response. History cannot bypass a blocker or malformed response. Snapshot state is copied and isolated by request and stage. Attempt limits are unchanged.

The shared reconciliation rule accepts an atomic durable commit of an effect and its same-operation deduplication record when same-key replay is safe. It still rejects race-prone check-before-write, separately committed markers and unsafe external effects. Optional implementation detail is advisory; a requested guarantee or declared unsafe behavior remains binding.

Explanations use `claude-sonnet-5-5` at low effort, with the supplied writing rules. Kimi K3 authors graph records and Sonnet 5 reviews them. The explanation schema, token limit and fallback remain unchanged.

## Fresh local requests

Frozen runtime: `a9b241c7784e66c56c060c9aaf78923ae348496f`. Run: `local-gate-consistency-05f08d9b-cab9-44c1-a81f-f93b5b78f290`. The isolated SQLite store began empty. The browser used production security headers and local development authentication. Source, corpus and browser build hashes are recorded in local `work/gate-consistency-local/`.

| Request | Nodes | Edges | Calls | Estimated cost | Explanation cost |
| --- | ---: | ---: | ---: | ---: | ---: |
| Research current practical trade-offs between agents and fixed workflows for production AI products. | 7 | 12 | 5 | $0.141329 | $0.027792 |
| Design a production model-serving stack with a monitoring component named Serving Monitor. | 8 | 19 | 5 | $0.157614 | $0.026238 |

Both component and connection reviews passed on attempt one. Both private captures passed for each request. All ten calls succeeded without retries or fallbacks. Each graph was newly generated in a separate thread; no prior answer or graph was reused. The second request's two Kimi calls each recorded 1,792 cached input tokens, which are provider prompt-prefix caching, not reused generated output. The research request recorded no cache tokens.

Reload and reopening preserved the exact decoded graph, contract, messages and telemetry. The provider ledger stayed at five calls after the first reopen and ten after the second. Total estimated cost was $0.298943, including $0.054030 for the two Sonnet 5.5 explanations. No standalone judge calls were made. The credentialed local backend was stopped after verification.

These fresh runs did not exercise a repair. Deterministic tests cover prior-review validation, stage isolation, changed records, malformed current responses and current blockers overriding historical satisfaction. Model adherence during a real repair remains subject to protected evaluation.

## Display defect found during review

The serving-stack answer contained three duplicated book citations shaped as `([Chapter 10, p.473](Chapter 10, p.473))`. CommonMark treats the destination with spaces as literal text. The stored source identity was valid, but its display was wrong. This was observed in the browser and persisted message. A deterministic Markdown display correction reduces identical canonical book pseudo-links to their label in assistant prose. User text, code, escaped examples and real links retain their original rendering. Stored content and source validation are unchanged. Focused frontend tests verify this presentation behavior without fresh model calls.

## Offline checks

The integrated runtime passed 3,087 backend tests with two skips and 92% coverage, 470 frontend tests, and 366 release-policy tests with five skips. TypeScript, lint, build, Bandit and dependency audits passed. Existing library deprecations, the Node localStorage experimental warning and two redundant Bandit suppression warnings remain in the recorded logs.

The first canonical run exposed two stale rubric-text assertions and an unregistered test file. The assertions now cover the atomic boundary and unsafe external effects, and the new rubric test belongs to the agent CI group. Repeated canonical checks passed. Commit `c35136e` changes only those tests, the manifest and architecture documentation relative to the frozen runtime.

This record establishes local generation and persistence on two requests. It does not establish universal success or a production rollout.
