# Mobile and tablet layout review

## Goal and review scope

Make the AI Engineering Learning Agent usable on mobile and tablets, review the existing layout with Impeccable, research current guidance, implement the accepted plan, and prepare a pull request. Preserve the existing dark visual style, D3 diagrams, graph generation, streaming, thread persistence, and graph editing behavior.

Review of baseline commit `99c2b6d` found these problems at 390px: history opened by default at 300px wide, the stacked diagram occupied 60% of the workspace, small controls were difficult to tap, and glossary content and thread deletion controls overflowed. The browser baseline confirmed that the open history covered most of the phone workspace.

## Impeccable audit assessment

Implementation integrity passes for the reviewed workspace: the same chat, D3
canvas, editing components, and callbacks serve every layout. Responsive variants
change available space and access to controls. The detector findings and retained
incumbent styling are recorded below.

Scores describe the reviewed surfaces and evidence, not a WCAG certification.

| Dimension | Baseline | Final | Evidence and remaining scope |
| --- | --- | --- | --- |
| Accessibility | 2/4 | 3/4 | Named inputs, composition-safe Enter, native modal focus and tab keyboard tests; screen reader device checks remain |
| Performance | 3/4 | 3/4 | Existing lazy chunks retained; bounded observers clean up; no performance benchmark claim |
| Responsive design | 1/4 | 3/4 | Seven viewport/orientation checks, touch controls and local overflow; device keyboard behavior remains unverified |
| Theming | 2/4 | 2/4 | Existing tokens mixed with inline colors; visual identity preserved |
| Implementation integrity | 2/4 | 3/4 | Component CSS replaces conflicting global overrides; retained typography and quote styling are deliberate |
| Total | 10/20 | 14/20 | Good within the reviewed scope |

Eight findings were prioritized: two P1 and six P2. No P0 was found.

| Priority | Location | Impact | Resolution |
| --- | --- | --- | --- |
| P1 | `App.tsx`, `ThreadSidebar.tsx` | The 300px open drawer covers most of a 390px first view, with no modal focus model | Closed by default on compact screens; native modal with close, Escape and backdrop dismissal |
| P1 | `SplitPane.tsx` | The 60% stacked diagram leaves too little room to read and compose | Full-height Chat/Diagram views below 960px pane width; state preserved |
| P2 | `ThreadSidebar.tsx`, `GlossaryDrawer.tsx` | Offscreen delete confirmation and fixed glossary widths lose controls | Inline confirmation; canvas-bounded glossary and scrollable entries |
| P2 | `TitleBar.tsx`, `SequenceBar.tsx`, `ChatInput.tsx` | Small targets and hover-only actions impede touch use | Common controls measure at least 44px under coarse input; visible history actions |
| P2 | `App.tsx`, `ChatInput.tsx` | Fixed viewport sizing and small fields risk an obscured composer and focus zoom | VisualViewport fallback and 16px touch fields; device testing remains |
| P2 | `ContextBar.tsx`, `MessageList.tsx` | Long labels and math can extend past their pane | Wrapping labels and local rich-content overflow |
| P2 | `ChatInput.tsx` | Enter while composing non-Latin text can send an unfinished draft | Ignore composing Enter; regression verifies normal submission afterward |
| P2 | `D3Graph.tsx` | Reordering a node on mouse-down suppresses its first native click | Raise the node only after nonzero pointer movement; preserve click and edit behavior |

The recurring issue was desktop-sized chrome consuming narrow workspace space.
The existing D3 resize handling, measured inspector camera exclusion, private
evaluator, per-thread drafts, and local table/code scrollers were retained.
Impeccable adapt supplied the implementation strategy; the bounded visual review
covered the integrated result without changing the product's visual direction.

## Research and accepted architecture

Breakpoints should follow content fit. A tablet width alone does not prove that two side panes and a conversation fit. [web.dev responsive design](https://web.dev/articles/responsive-web-design-basics) recommends starting with narrow content and adding breakpoints when the content needs them. All functionality must remain reachable after reflow.

The accepted layout uses Chat and Diagram tabs when the actual workspace pane is narrower than 960 CSS px. Measuring the pane accounts for history occupying part of a wider window. At larger pane widths, retain the resizable diagram and conversation arrangement. When no diagram exists, show the conversation without an empty diagram tab. Keep both pane components mounted with their existing props and callbacks. An inactive pane remains measured for D3 readiness and is hidden and inert for interaction. Tab changes must preserve drafts, diagram state, and generation/render acknowledgement behavior.

History becomes a modal drawer below 1280px and starts closed. Wider windows retain inline history. The drawer needs a visible close control, focus placement inside, Escape dismissal, contained keyboard focus, an inert background, and focus restoration to its trigger. Resize transitions must close or convert the drawer without leaving focus trapped or background content inert. These requirements follow the [WAI modal dialog pattern](https://www.w3.org/WAI/ARIA/apg/patterns/dialog-modal/). Tabs need keyboard selection and associated tab panels; collapsed sections need a button and an expanded state.

The shell uses dynamic viewport height and safe-area spacing. Virtual keyboard behavior requires separate handling: [web.dev viewport units](https://web.dev/blog/viewport-units) states that viewport units do not automatically account for the on-screen keyboard. `interactive-widget=resizes-content` is an enhancement described by [Chrome viewport guidance](https://developer.chrome.com/blog/viewport-resize-behavior), not a cross-browser guarantee. The accepted VisualViewport adjustment uses visible height and top offset at scale 1 and removes those adjustments during pinch zoom. Do not disable zoom or restrict user scaling. [MDN VisualViewport](https://developer.mozilla.org/en-US/docs/Web/API/VisualViewport) explains that keyboards and pinch zoom can both change the visual viewport. Apply [safe-area environment variables](https://developer.mozilla.org/en-US/docs/Web/CSS/Reference/Values/env) to composer and panel edges without treating them as a universal keyboard-height measurement.

Use a 44px design target for frequently used controls, including send, history, close, thread actions, tabs, and glossary controls. [WCAG 2.2 target size minimum](https://www.w3.org/WAI/WCAG22/Understanding/target-size-minimum.html) requires 24 by 24 CSS px at AA with defined exceptions, including spacing. The chosen 44px size is a usability goal associated with the [enhanced target criterion](https://www.w3.org/WAI/WCAG22/Understanding/target-size-enhanced.html), not the AA minimum. Preserve focus indicators and expose controls without relying on hover.

Conversation prose, composer, header controls, dialogs, and surrounding captions must fit at 320 CSS px. Wrap long URLs, filenames, and labels. Keep wide tables, code, and mathematical content in local scroll regions so they do not widen the page. Scale diagrams and media to their container. [WCAG reflow](https://www.w3.org/WAI/WCAG21/Understanding/reflow) allows two-dimensional content such as data tables to retain local scrolling; prose and individual table cells still need reflow unless their meaning requires two dimensions. Code is not automatically exempt. Sticky UI must leave focused controls visible; reserve layout space or use scroll padding as described by [WCAG focus not obscured](https://www.w3.org/WAI/WCAG22/Understanding/focus-not-obscured-minimum.html).

## Implementation plan

1. Replace the narrow stacked layout with pane-width-driven Chat and Diagram tabs. Preserve component identity and existing graph/render callbacks. Keep desktop resizing bounded so the conversation remains usable.
2. Convert history into an accessible modal drawer below 1280px. Keep history selection, deletion confirmation, and long thread titles within the drawer.
3. Add viewport and safe-area handling to the application shell. Keep the composer reachable and allow pinch zoom. Retain normal browser behavior where viewport APIs are absent.
4. Adjust composer, context controls, diagram sequence controls, node details, and glossary spacing and wrapping. Increase common hit areas and contain rich-content overflow locally.
5. Test state retention, tab and drawer keyboard interaction, viewport changes, no-diagram behavior, and existing generation invariants. Run repository checks and browser verification before PR review.

## Verification checklist

Browser checks used the current source, Chrome 154.0.8037.58, and the local `dev@local` account at `http://127.0.0.1:5211`. A FastAPI fixture on port 8026 supplied in-memory threads and a saved seven-node graph. No provider clients were loaded and no production writes were made. These checks exercise real frontend components with an offline transport. No physical-device keyboard testing or fresh generation is claimed.

| Check | Expected result | Status |
| --- | --- | --- |
| 320px width | Full chat functionality, fitting composer and header, no horizontal page scroll | Pass: browser matrix |
| 390px width | History starts closed; Chat and Diagram tabs use the available height | Pass: browser matrix |
| 768px width | Compact pane layout; modal history fits and dismisses | Pass: browser matrix |
| 820px width | Composer, glossary, node details, and rich content fit | Pass: browser matrix |
| 1024px width | Closed history permits side-by-side panes when measured width is at least 960px; open drawer does not shrink the workspace | Pass: browser matrix |
| 1440px width | Inline history and bounded resizable panes remain usable | Pass: browser matrix |
| 844 by 390 landscape | Composer and panel controls remain reachable in short height | Pass: browser matrix |
| 200% text resize | Text and controls reflow without loss of functionality | Pass: 32px root font at 768px; no page overflow |
| 1280px at 400% zoom | Content reflows at the equivalent 320 CSS px width | Equivalent 320px geometry passes; browser desktop zoom not separately exercised |
| Pinch zoom / viewport scale | VisualViewport overrides are removed when scale differs from 1; user zoom remains allowed | Pass: emulated scale 2 removes workspace height override |
| Keyboard open and close | Visible viewport adjustment keeps composer reachable | Unit-tested height/offset updates; reduced 390x400 viewport keeps send bottom at 388px; real keyboard unverified |
| Tab switching with draft and diagram | Draft, D3 state, and generation/render callbacks survive pane changes | Pass: browser matrix |
| History keyboard interaction | Focus enters drawer, remains inside, Escape closes, focus returns to trigger | Pass: browser matrix |
| Resize with history or diagram open | No stale modal state, lost focus, or inaccessible inactive pane | Pass: 390 to 1440 to 390 clears modal state; focused-pane regressions pass |
| Long URL, code, table, and math | Prose wraps; rich-content overflow stays local | Pass: 320px and 768px; code, table and math scroll locally |
| Glossary and deletion confirmation | Content and action buttons fit at narrow widths | Pass: browser matrix |
| Touch and keyboard controls | Common controls meet the 44px design target and display visible focus | Pass: browser matrix and 390px emulated touch node tap |
| Save and reopen edited graph | Node edit survives save, reload and history reopen | Pass: 390px touch and 1024px native mouse flows with offline persistence |
| Desktop mouse node activation | Single mouse click opens node inspector | Pass: first click and zero-displacement mouse move; drag, double-click and keyboard behavior retained |
| Empty, streaming, error, and completed states | Existing status and graph behavior remain intact | Existing unit regressions pass; completed state browser-checked with offline graph |
| Frontend tests, types, lint, build, and relevant repository checks | Required checks pass | 508 tests, lint, type/build and audit pass; 368 CI policy tests pass, 5 expected skips |
| Impeccable review and diff review | Remaining layout issues are resolved or documented before PR | Completed; retained incumbent styling noted below |

## Evidence and review

The browser matrix measured the visible composer inside every viewport, zero page
horizontal overflow, positive dimensions for the inactive diagram, and 44px touch
controls. It exercised history focus entry, twelve Tab presses inside the native
modal, deletion Cancel/Escape, drawer Escape, and return to the history trigger.
Node editing and chat drafts survived tab changes. Node fields and Save/Cancel
remain scrollable in short landscape layouts.

Additional fixture checks covered a twelve-step walkthrough at 320px and 768px.
Its progress row scrolls locally and the last step remains reachable. At 390px,
a native emulated touch tap opened a node, editing and saving succeeded, and the
edited value survived reload followed by reopening its saved thread.

A 1024px native mouse test initially emitted pointer down/up without a click
event. The same test against isolated baseline commit `99c2b6d` reproduced the
failure. The debugging pass found that raising the node on mouse-down reparents
its SVG group before the browser dispatches a click. The first click failed;
the second succeeded because the node was already last in drawing order. A fresh
page with only the reparent operation suppressed restored the first click while
D3's other event handling remained active. The node kept its identity throughout,
which ruled out renderer replacement as the cause.

Moving the raise operation into the drag handler alone was insufficient. D3 can
emit a drag event for a mouse move with unchanged coordinates. Native Chrome and
a three-node regression both reproduced the lost click in that case. The fix
raises the node only when `event.dx` or `event.dy` is nonzero. Click timing,
double-click editing, F2, keyboard selection, snapping and persistence callbacks
remain unchanged. PR #62 contains the related drag-only change; this branch also
covers the zero-displacement case.

After the fix, six native Chrome journeys passed without page or console errors:
1024px first click, double-click editing, drag followed by click, Enter/F2,
edit/save/reload with history reopening, and 390px touch activation. Separate
stationary-pointer checks passed with and without a zero-displacement mousemove.
The source tests ran on `fdc162c` plus this commit's two-file pointer patch.
All 508 frontend tests, lint, TypeScript and the production build passed;
independent review found no further issue in the patch.

The live-evaluation investigation found no failed test in run `36565582959`.
Its evaluation job was queued behind PR #62 in `staging-live-eval-global`, with
no pending environment approval. The obsolete run was cancelled before updating
the fix. The live browser suite uses a 1440 by 960 viewport and Enter-based node
selection, so mobile tab transitions and native pointer activation require the
separate local checks. Forty existing frontend readiness/layout tests and four
backend selector/follow-up tests passed during this investigation.

Independent source review caught one breakpoint transition defect: a retained
Diagram tab could hide a focused chat input when returning to compact layout.
The resize measurement now chooses the focused pane. Regressions cover chat focus,
node editor focus, graph removal, and interrupted resize cleanup.

Commands run from `frontend/`:

```sh
npm ci --ignore-scripts
npm run lint
npm run test:coverage
npm run build
npm audit --audit-level=low
```

Coverage: 93.86% statements, 85.88% branches, 96.05% functions, 96.43% lines.
Repository command: `./scripts/ci offline --group pipeline-policy`.
The policy suite passed 368 tests with 5 expected skips; the manifest validates.
`git diff --check` passes.

The Impeccable detector reported the incumbent Inter fallback, the Markdown
blockquote border, and progress-dot width/height animation. The dot animation now
changes background only. The existing system-font stack and semantic quote border
remain because this task preserves the product's visual identity. They do not
change responsive behavior. No typography redesign was requested.

The required dependency audit initially found moderate advisory
[GHSA-3wwx-pv8p-q78v](https://github.com/advisories/GHSA-3wwx-pv8p-q78v) in development
only `undici`, pulled through jsdom. The lockfile updates that transitive dependency
from 7.29.0 to 7.30.0; the package manifest is unchanged. Reinstall and the full
frontend checks pass, and npm audit reports zero vulnerabilities.

The local Node 26.5.1 runtime prints an experimental localStorage warning before the
Vitest setup installs in-memory storage. Test storage remains isolated and all
checks pass. CI uses Node 20.

## Limits and rollback

Real iOS Safari, iPadOS Safari, Android Chrome keyboards, VoiceOver, and TalkBack
were not available. Browser emulation and synthetic viewport tests do not replace
those device checks. No live model evaluation was invoked locally: prompts,
provider settings, graph data, renderer algorithms, and transport are unchanged.
The pointer fix changes when an existing node is raised in SVG drawing order.
CI retains its existing conservative path classification and required gates.

No database migration or backend change is involved. Revert the PR to restore the
previous layout and lockfile. The change does not rewrite saved threads, graph
content, or stored camera positions.
