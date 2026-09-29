# Open node panes in normal view with compact connections

Clicking a node now opens its detail pane immediately. Double-clicking keeps that
view and does not zoom or enter editing. A muted Edit button sits beside Close.
Edit and F2 explicitly enter the existing form. Reselecting a node resets a
pristine editor to normal details.
Unsaved drafts remain protected by the existing selection guard. The Edit button
retains its accessible name, focus restoration and permission checks; it appears
only in the normal view and has no accent fill or border.

Node dragging now raises the SVG node after movement starts. Raising it on
mousedown reparented the element before click dispatch, which swallowed the first
click in the local WebKit browser. The parent reproduced that failure and confirmed
that the first click works after this change.

The inspector reset key also restarts its ResizeObserver subscription. Existing
save, cancel, validation, graph persistence and generation protocols are unchanged.
Selection invokes the existing callback immediately instead of after 350 ms.
Private graph capture disables pointer interaction, so these handlers do not alter
capture geometry or model evaluation. No migration or backend deployment is needed.
Reverting the frontend patch restores the prior interaction.

## Compact connections

The normal pane groups incident edges by component pair using the existing
`diagramConnections` presentation helper. Each collapsed row names the peer with
To, From, or To and from. Self-loops say Within this component. Expanding the native
HTML disclosure reveals every directed label, technology and asynchronous marker.
The five-exchange fixture now starts with three compact rows. The repeated action
hint is removed. Connection editing still uses the original graph edge indexes.

The added nodes prop supplies peer display names only, with IDs as the fallback
for missing peers. No graph records are removed or rewritten. Disclosure keys keep
same-node enrichment open and reset when the selected node changes. Native
keyboard behavior, focus outlines, wrapping labels and touch target sizing remain
available. These changes do not alter requests, graph geometry or capture output.

## Verification

Tested base: 99c2b6d2c7bbf418a12d146dac324ef33eb2c9d0. The exact runtime blobs are
recorded in ci/quality.json through the existing presentation review mechanism.

The full frontend suite passes 496 tests in 41 files with coverage. Lint,
TypeScript and the production build pass. Statement coverage is 93.37%, branch
coverage 85.50%, function coverage 95.36% and line coverage 95.78%. Tests cover
pointer activation, double-click suppression, retained F2 editing, DOM order during
click and drag, clean reselection after all editing entry points, and dirty drafts.
Connection checks cover hidden metadata, both directions, parallel exchanges,
self-loops, missing peer names, enrichment and selection changes.
The CI policy suite passes 368 tests with five environment-dependent skips, and
the manifest validates. Independent source review found no actionable defects.
The Impeccable detector reported no findings for the updated pane component,
styles and GraphCanvas integration.

The parent exercised the current full App in the Codex browser with a local dev
account and isolated in-memory fixture transport at 127.0.0.1:5210. Desktop checks
confirmed first click, double-click, explicit Edit details, clean same-node
reselection, dirty-draft retention, Cancel, Save, and reopening the saved conversation
after page reload. A 390x844 viewport confirmed readable normal details, access to
Edit details in the scrollable pane, and return to normal details after Done.
The compact Connections list was checked on desktop and at 390x844: rows start
collapsed, name their direction, and reveal both exchanges when opened. Enter
and Space toggle the focused disclosure. Long labels wrap inside the scrollable
pane. The muted header Edit control was checked on desktop and at 390x844; it
opens the form, focuses Name, and receives focus again after Done. The preview
was left at its normal desktop size with connections collapsed.
No paid model calls were made. The fixture reports provider_calls=0 and does not
import application backend/provider clients or connect to production storage.

The fixture backend was restarted while adding content-save support. Old browser
thread IDs then produced three layout-save errors; a new fixture conversation
completed save and reload successfully. These fixture lifecycle errors are separate
from the pane change. Local evidence and fixture scripts remain in work/pane-view-check
in the task workspace.

## Existing dependency issue

The required npm audit reports one existing moderate advisory in the jsdom development dependency undici
7.28.0-7.29.0 (GHSA-3wwx-pv8p-q78v). This patch leaves package.json and package-lock.json
unchanged. The Node test runner also emits its existing experimental localStorage
warning. Neither issue is introduced by this change.
