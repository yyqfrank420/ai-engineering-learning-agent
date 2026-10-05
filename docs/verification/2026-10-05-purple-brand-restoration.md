# Purple brand restoration verification

Base: `de8438ff0c608e08cd946367d39d5ba67fa42d5c`.

Restore the purple-blue gradients, ambient backdrop and translucent surfaces from
`271436e`. Preserve the newer components, Phosphor icons, spacing, typography and
keyboard affordances. Restore the original decorative generation SVG from
`e07070f^` inside the existing empty canvas branch.

The SVG appears only when `graphData` is absent and `isBuilding` is true. A real
preview replaces it. It is hidden from assistive technology and does not become
candidate or persisted graph data. Generation state, request callbacks, transport,
backend and agent code are unchanged. Private rendering retains body typography
and its separate mounting boundary outside the visible workspace.

## Offline checks

- Affected frontend component tests: 115 passed in 8 files, including idle, pending
  and graph-present loading states.
- Frontend ESLint, TypeScript and production build passed.
- Exact presentation audit tests: 42 passed.
- Full diff and whitespace checks passed.
- Design detector findings are intentional: the user requested the original gradient
  wordmarks; body Inter metrics remain fixed for private diagram evaluation.

## Local browser verification

Verification uses `dev@local`, SQLite development storage, Vite on port 5191 and a
local fixture server on port 8191. Model credentials are disabled. The pending
flow uses a deterministic scratch transport and a captured saved graph fixture.
No fresh generation evidence is required for this presentation-only change.

At 1440x900 and 390x844, inspected sign-in, empty conversation, pending mock
visual, captured preview replacement, saved diagram and component inspector.
The pending visual disappears when a real graph preview arrives. Stop remains
available. No phone overflow; composer text remains 16px. Screenshots and fixture
provenance are in the task outputs `purple-restore-verification.json` and
`purple-restore-*.png`.

Initial scratch-server setup missed newer FastAPI lazy route wrappers and failed
provider-client initialization with empty credentials before any provider call.
The corrected server intercepts every WebSocket at its ASGI boundary. A direct
loopback handshake proved that only deterministic fixture events are emitted.
The browser then exercised the corrected fixture. Provider calls: zero.
