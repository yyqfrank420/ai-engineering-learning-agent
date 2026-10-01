# Zone edge routing verification

Verified locally on 2026-09-30 on `codex/zone-edge-routing`, based on main `a083406f6c8e8ea5812ac8c90d698f80751c72e9`.

## Reviewed change boundary

The learner navigation router and its D3 integration change connection geometry. `diagramConnections.ts` changes from blob `3df2c9bccc5625f9f4ac62f969fab4c1255d9d9f` to `3a8687a415dbb8f1e9818f59e76fff8fe7493c8d`. `D3Graph.tsx` changes from the actual base blob `5f9d6122f24486d92e5eef6410e942660b6d54ea` to `e67adb5e318da2847621d3c920a380d74c8d818a`. Focused tests change alongside these files.

Root and independent source review confirmed that D3 passes zone frames to the router only for learner navigation. The private renderer's frame calculation remains equivalent, and existing unzoned routes remain unchanged. No model, prompt, protocol, backend or persistence files change. The two exact presentation records in `ci/quality.json` identify only these reviewed transitions; AI scopes and policy rules are unchanged.

## Routing behavior

D3 computes the current zone frames once at the start of each render tick. Connection routing and drawn boundaries use those same frames, including before mouseup during component dragging and zone resizing.

Same-zone paths stay inside the shared frame's content area, clear its heading band and avoid component interiors. Cross-zone paths have contiguous source-zone access, an exterior corridor and contiguous target-zone access. They avoid unrelated zone interiors and prevent endpoint-zone reentry. Boundary contact is allowed. Duplicate ownership selects the first containing zone in the supplied ordering; repeated member IDs are deduplicated when computing frames.

Short endpoint corridors are tried before bounded grid search. Search tries the local endpoint window before the global coordinate grid. Each search is capped at 40,000 vertices and 160,000 expansions. Overlapping or obstructed manual layouts, or exhausted search bounds, can require the existing unzoned fallback. The relationship remains visible and is marked as blocked. Its tooltip and accessible description say: "This connection needs a clearer path. Move nearby zones or components apart to clear its route." A blocked fallback is not claimed to satisfy zone clearance.

## Checks completed

Focused checks passed 22 router tests, TypeScript checking and ESLint against the final source. D3 focused checks passed 109 tests during implementation; the final wording confirmation passed 53 interaction tests. The layout scope detector ran once and returned an empty violation list for both modified source owners.

The full canonical `./scripts/ci offline` run passed all 11 groups and 26 commands, exit 0, on 2026-09-30 from 13:43:44 to 13:48:03 UTC. Evidence is retained in parent workspace `work/zone-routing-verification/canonical-result.json` and `canonical.log`. The four runtime/test source hashes match before and after the run; the reviewed source did not change during verification.

Backend coverage checks passed 3,442 tests with 2 optional Postgres skips and 92% coverage. Frontend checks passed 589 tests across 43 files; coverage was 93.64% statements, 86.51% branches, 95.13% functions and 96.13% lines. Pipeline policy passed 388 tests with 5 optional skips. All applicable lint, security, dependency audits, production and container builds, Terraform, migration, ingestion and artifact checks passed. Dependency audits found zero vulnerabilities. The validated manifest SHA256 was `76581690057e0c7302ef1344d9a15018d77a023b34f7b4f42818e703f93ba313`.

Existing warnings and optional skips remain: Starlette/AnyIO and LangChain deprecations, Node localStorage experimental notices, two Bandit nosec notices, the optional Postgres and policy cases, and 10 ingestion skips. These are unchanged by the routing source changes; passing CI does not imply a warning-free run.

The reproducible benchmark in the parent workspace at `work/zone-routing/benchmark.json` uses Node v26.5.1 and TypeScript 5.9.3. Ten runs routing 59 connections across 60 jittered singleton zones had a 10.39 ms median and a 14.77 ms maximum, with no grid searches or blocked routes. The 60-card, six-zone case had a 1.64 ms median; a feasible multi-turn maze had a 0.84 ms median. An independent warm measurement reported 17.9 ms for the jittered case. The initial implementation took approximately 2,600 ms for that case. These synthetic timings describe local routing work and do not establish a frame-time guarantee for every layout.

## Current browser evidence

The final report at parent workspace `work/zone-routing-verification/report.json` was read after the final source review. It identifies a synthetic saved architecture, mocked HTTP and WebSocket transport, the actual current frontend and zero provider calls. Its before/after SHA256 values match the reviewed current source:

- `D3Graph.tsx`: `5c9d518a268b7fe8686fba0624beb67a44ee30b7d7275188d7045f68816d3f91`.
- `diagramConnections.ts`: `ecce10f7584da44a208c282423abf5a9d27d525b572e015f9510f37e8f895979`.
- Unchanged `graphLayout.ts`: `4f247310f593b02bb82580f8752c652c686bd1dd13544f18a70320a9a48ce28d`.

Desktop geometry checks covered six edges at initial render, component drag before mouseup, completed component drag, zone resize before mouseup, completed zone resize and final reload. Mobile checks covered all six edges at initial render and final reload. They confirmed same-zone containment where applicable, clear heading bands and component interiors, clear unrelated zones and contiguous endpoint-access intervals for cross-zone paths. Desktop recorded four layout saves and mobile one through mocked persistence. Both viewports recorded no browser/console errors, no external requests and no generation starts.

The earlier `geometry-report.json` records the preceding geometry-only run. The final `report.json` has capture authorization enabled and source hashes matching the exact reviewed blobs above. Captures and browser scripts remain outside the repository in the parent workspace. The parent viewed the valid desktop and mobile captures from the first capture round. A fresh default reviewer, using the supplied degraded finish role, returned `ship`: the captures and scoped routing promises matched, with no fixes required. The supplied degraded documenter check returned `No changes` and preserved the existing visual tokens. `DESIGN.md` was already absent; no design-drift repair was required. The existing card stripe is outside this routing change's scope.

## Limits

Browser evidence uses one synthetic saved graph and mocked persistence. It does not verify deployed persistence or a provider-generated diagram. Focused cases cover routing edge conditions, but arbitrary overlapping manual layouts may use the disclosed fallback. Grid limits bound search work, so fallback can occur when a larger search could find a route. No provider calls were made for this layout-only change.
