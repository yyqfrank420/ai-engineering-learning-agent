# Diagram reliability verification, 2026-09-28

## Tested source and environment

The fresh local application check used base
`fc17e61ae4f50c5eb0537300cc08e5ba5b5fc5ae` with frozen binary diff SHA256
`014a5e06ed32e2fb3f6f01660338bae12dc58eebc3979d90002390df2cf2b59a`.
The account was `dev@local`, with a new isolated SQLite database and existing
source artifacts. Production storage, authentication and external analytics were
disabled. Provider calls used the normal application models and deadlines under
one shared nine-attempt limit.

## Fresh generation and persistence

The exact prompt was `tell me about ai engineering in education`. The actual
request used automatic depth, diagrams enabled and research enabled. A new thread
and new request identities linked the stored turn, provider telemetry and
accepted graph. The run produced a substantive answer and a complete diagram
with 10 nodes, 22 directed connections and three steps. Both staged reviews
approved all four rules on their first attempts. The graph and its accepted
contract carried the same version.

Five actual provider calls completed: Kimi components, Sonnet component review,
Kimi connections, Sonnet connection review and Opus synthesis. Five independent
attempt reservations matched them. There were no retries or fallbacks. Recorded
usage was complete: 32,473 input tokens and 6,649 output tokens, with zero cached
input tokens. The new database contained two messages and no replay event.
Reloading and reopening the thread preserved identical messages, graph,
contract, telemetry and provider reservations.

## Failure evidence and policy correction

An earlier fresh run failed after two component candidates and two reviews.
One review rejected `learning_or_release=false` because a component owned offline
fine-tuning. The next rejected `true` because that same work was offline and
human controlled. No complete graph was generated. The component records were
unchanged; the flag and standard/overview detail setting differed.

The shared capability criterion now counts owned training, updates and releases,
including offline work and human approval. Passive curation alone does not
establish that capability. Generator version `staged_components_v29` and review
version `staged_component_gate_v18` identify the clarified policy. Models,
review requirements and retry policy were retained.

Two separate calls reviewed the actual saved candidates under the new policy.
The original false flag was rejected solely for capability classification; the
repaired true flag passed all rules. These are fresh reviews of saved inputs,
not fresh diagram generation. Their detail settings also differ, so they do not
isolate flag causality. The subsequent fresh generation above supplies the
application evidence.

A production request logged a browser-render timeout at 10:46:37 UTC. This proves
that the server did not receive an accepted evaluation before its deadline.
The actual browser trigger remains unknown. Navigation, deferred painting and
capture waits were investigated as possible causes. Local verification exercised
private rendering while the dashboard was open.

A separate real local WebSocket check pointed the provider adapter at a closed
loopback port with a fake key. The UI displayed a service-unavailable notice,
preserved the failure through history reopening and stopped waiting. No external
provider was contacted. This verifies failure handling, not generation success.

## Checks and limits

The full backend suite passed 2,837 tests with two skips and 92% coverage. The
frontend suite passed 456 tests across 41 files with 93.17% statement coverage.
Lint, build, Ruff and security checks passed; npm audit found zero vulnerabilities.
Bandit reported two existing unused B603 suppressions in the CI runner.

After the frozen application run, a harness-only change normalized an omitted
optional `diagram_requested` field to false when checking submitted requests.
Its tests and 137 focused corpus checks passed. Application runtime source did
not change after the fresh run.

These checks establish the recorded journeys and bounded visible failures.
They do not establish a 100% generation success rate, vendor billing accuracy
or every possible browser suspension scenario. Failure notices and preserved
graphs are not counted as new generation. No migrations are included. Rollback
uses the normal deployment rollback to the previous application revision.
