# Route connections around unrelated zones

Cross-component lines could cross an unrelated zone's background and heading because
the interactive router only considered component cards. The router now considers
the complete rendered bounds of unrelated zones. A connection may enter the zones
that contain either endpoint. Zone bounds are calculated before routing and use the
same `zoneFrame` geometry as the visible frame, including saved padding. Node moves,
zone moves and zone resizing recalculate both visible paths and their hit targets.

The change is limited to interactive navigation rendering. `HiddenGraphEvaluator`
does not enable navigation, so its routing and capture geometry are unchanged.
Connection projection, graph persistence, prompts, model calls and publication
protocols are unchanged. The exact runtime blob transitions are recorded in
`ci/quality.json` using the existing reviewed presentation mechanism. No workflow
or classification rule is relaxed. The user requested a frontend-only PR and merge
without paid model evaluations.

## Local verification

Base revision: `bf763e3` on 2026-10-04. Runtime file hashes are recorded in the
presentation review entries. The worktree used its locked frontend dependencies
installed with `npm ci --offline --ignore-scripts --no-audit --no-fund`.

- `npm exec vitest -- related src/components/GraphCanvas/D3Graph.tsx src/components/GraphCanvas/diagramConnections.ts --run`: 177 tests passed in 10 files.
- `npm run lint`: passed.
- `npm run build`: TypeScript and production build passed.
- `git diff --check`: passed.
- Impeccable's detector reported no findings for the changed runtime files.

New regressions cover wide zone headers, saved padding, horizontal and vertical
routes in both directions, direct routes through zone space, empty groups,
intra-group links, visible/hit path agreement, and recalculation after moving or
resizing a zone. Existing self-loop and overlapping-obstacle behavior remains
covered. Node emitted its existing experimental localStorage warning during
Vitest; jsdom tests completed successfully.

The current source ran through the existing local `visual/graph.html` harness at
`127.0.0.1:5214`. This harness renders the real GraphCanvas with no auth session or
active thread, so it does not save data or call model providers. Browser checks
covered the growth marketing fixture at 1440x900 and the support fixture at
390x844. DOM geometry checks found no connector segments intersecting unrelated
zone interiors across 17 paths/5 zones and 18 paths/4 zones respectively. The
growth diagram also retained clear routes after keyboard zone movement and border
resizing. Browser warning/error logs were empty and no Vite overlay appeared.
An independent source review found no correctness blocker.

## Limits and rollback

The existing router chooses among a bounded set of orthogonal candidates. Overlapping
manually placed cards or zones, or layouts requiring more turns than those candidates
provide, can still force intersections. This change does not add a general maze
router or claim that every possible manual arrangement has a clear route.

No migration is needed. Reverting the frontend change restores previous routing.
