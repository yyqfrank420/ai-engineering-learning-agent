# Zone heading overflow verification

Baseline: origin/main, `44d722df7029e1edcbaf1995db70aa7f6e72ea87`.
The exact reviewed source blob pairs are recorded in `ci/quality.json`.

## Scope

Interactive zone frames were sized around their nodes while headings rendered on
one unbounded line. Headings now reuse the existing two-line label wrapper with
attached SVG font measurements and 18px horizontal insets. Font completion and
zone resizing remeasure the heading. Full names remain in accessible zone labels.

The interactive header reserves 60px above its nodes. Two-line baselines sit at
27px and 43px; a single-line baseline sits at 32px. Resize minimums, centering and
node alignment targets use the same frame insets. Node positions and saved padding
retain their existing meanings. Restored frames gain 18px of header space.

No backend, prompts, graph records, generation policy or private layout rules change.

## Private renderer isolation

HiddenGraphEvaluator disables navigation. Its group-frame calculation is separate
from interactive zoneFrame, and the changed wrapping and font-ready render branches
are guarded by navigation. A temporary Vitest harness imported separate baseline
copies of both changed modules and compared complete private SVG strings against
the current source. Both comparisons passed at 1440x960 with geometry readiness,
fixed text metrics and 700ms transition waits:

| Fixture | Nodes/edges | UTF-8 bytes | Identical SHA256 |
| --- | --- | ---: | --- |
| modelServingPaidCandidate | 10/15 | 36662 | d40809e49ea80cc9f9aa393b1eac198dca89d6de971d5637ecd66572fb4564a3 |
| documentProcessingPaidCandidate | 30/95 | 175043 | c4c1fd678e4d0cc1ce504c9c30e69d75f74b5682413dda6174815c7db3630b4d |

Temporary baseline and proof files were removed. No provider calls were made.
Paid generation checks are unnecessary for this interactive presentation change.

## Verification

Focused regressions cover spaced and unbroken long headings on first draw,
font completion, resize reflow, stale font callbacks after unmount, frame resizing,
restored padding and routing around the larger zone frame. The scoped layout
detector found no issues.

Rollback uses the normal frontend source/deployment rollback. No migration or
backend release is required.

Canonical frontend checks passed ESLint, 172 related tests across eight files,
TypeScript and the production build. CI policy checks passed 504 tests with five
existing local capability skips. Manifest validation passed.

The isolated local preview used the current D3Graph and application CSS without
backend calls or restored layout. Desktop (1440x900) two-line headings had 13px
above and below the text. Mobile (390x844) measured 13.036 and 12.811 SVG units
at 0.716 canvas scale. Single-line headings also stayed inside their zones.
All four scenarios passed containment and 12-unit clearance checks with no
console or page errors. Mobile retains the existing pannable canvas behavior.
