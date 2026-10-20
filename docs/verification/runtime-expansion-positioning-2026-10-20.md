# Runtime expansion positioning verification

Verified source revision: `6f123d44acbafae492e657bb1064c02c0cc703d9`.
Baseline: `github/main`, `e5d0e55c5896c1cef499f29fe24f088a8713ceec`.
The exact source blobs are recorded in `ci/quality.json`.

## Scope and private renderer isolation

`D3Graph.tsx` replaces the added-node collision loop only inside
`navigation && restoreViewState`. The new pure `placeAddedNodes` function in
`graphLayout.ts` retains saved anchors and places added internal components beside
their owning service. Existing layout functions are unchanged.

`HiddenGraphEvaluator.tsx` mounts `D3Graph` with `layoutReadiness="geometry"`
and supplies neither navigation nor saved view state. `D3Graph` defaults navigation
to false. The private candidate path cannot execute the changed placement branch.
Backend source, prompts, transport, candidate publication and schemas are unchanged.

A temporary untracked Vitest harness imported the baseline D3Graph and graphLayout
blobs alongside the current renderer. Both rendered the same private-mode props
at 1440x960 with fixed jsdom SVG text measurements. The harness waited 700ms for
D3 transitions and compared complete SVG strings. Both comparisons passed:

| Fixture | Nodes | Edges | Identical SVG bytes | SHA256 |
| --- | ---: | ---: | ---: | --- |
| modelServingPaidCandidate | 10 | 15 | 36644 | d40809e49ea80cc9f9aa393b1eac198dca89d6de971d5637ecd66572fb4564a3 |
| documentProcessingPaidCandidate | 30 | 95 | 174925 | c4c1fd678e4d0cc1ce504c9c30e69d75f74b5682413dda6174815c7db3630b4d |

The harness and baseline source copies were removed after the comparison. This
checks renderer geometry with deterministic text metrics, not browser font layout
or immediate screenshot timing. No provider or backend calls were made.

## Interactive flow

The release owner verified a local browser fixture reconstructed from the supplied
Cortex diagram and its visible saved coordinates. Of 15 nodes, all 12 saved nodes
retained their positions and three added components stayed near Cortex Agent runtime.
Reloading the emitted layout retained all 15 positions. The browser reported no
console errors. This is a local fixture check; it does not claim a production
persistence request succeeded. The screenshot's save error remains a separate issue.

The release owner also ran 114 affected tests across four files, plus type and lint
checks. The canonical offline command is recorded below after completion. Its scope
includes transitive frontend consumers and CI policy because this release changes
the exact-content audit ledger. No runtime, test, model or deployment behavior was
changed while preparing this evidence.

## Canonical release checks

`./scripts/ci offline --base github/main` selected `frontend` and
`pipeline-policy`. Frontend ESLint passed, all 185 related tests across eight files
passed, and TypeScript plus the Vite production build passed. Node emitted its
existing experimental localStorage warning; `vitest.setup.ts` provides the test
storage implementation.

The initial default scan included unrelated untracked `work/` preview files and
`.vite/` caches. Local `.git/info/exclude` now excludes those scratch directories;
no tracked selection policy changed. System Python 3.14 lacked pytest, so the
remaining policy gate used an isolated Python 3.12 environment under
`work/release-venv`. Its minimal installed imports were pytest, pytest-asyncio,
PyYAML, pydantic-settings, Playwright, websockets and Pillow.

`CI_PYTHON="$PWD/work/release-venv/bin/python" ./scripts/ci offline --group pipeline-policy`
passed 504 tests with five existing local Bash capability skips. Manifest validation
passed with fingerprint
`aa1827e639cead048c75c98519a5a94ef65c90ec7c820a1d469950ab5e13a11a`.
Passing frontend checks were reused when resuming the policy gate.

`./scripts/ci impact --base github/main --head HEAD` matched both reviewed source
transitions and reported `ai_impact: false`, with no AI-impacting paths.
`git diff --check` passed. No paid generation evaluation was required because the
changed placement path is interactive presentation only and the private candidate
renderer remains unchanged.

Rollback uses the normal frontend source/deployment rollback. No database migration
or backend deployment is needed. Existing saved misplaced nodes retain their saved
coordinates; the fix applies to newly added nodes without saved positions.
