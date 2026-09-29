# Open node panes in normal view

Clicking a node now opens its detail pane immediately. Double-clicking keeps that
view and does not zoom or enter editing. Edit details and F2 explicitly enter the
existing form. Reselecting a node resets a pristine editor to normal details.
Unsaved drafts remain protected by the existing selection guard.

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

## Verification

Tested base: 99c2b6d2c7bbf418a12d146dac324ef33eb2c9d0. The exact runtime blobs are
recorded in ci/quality.json through the existing presentation review mechanism.

The full frontend suite passes 494 tests in 41 files with coverage. Lint,
TypeScript and the production build pass. Statement coverage is 93.36%, branch
coverage 85.44%, function coverage 95.34% and line coverage 95.77%. Tests cover
pointer activation, double-click suppression, retained F2 editing, DOM order during
click and drag, clean reselection after all editing entry points, and dirty drafts.
The CI policy suite passes 368 tests with five environment-dependent skips, and
the manifest validates. Independent source review found no actionable defects. The Impeccable detector
reported no findings for the changed runtime components before the final drag
handler correction, which changes no styles or rendered markup.

The parent exercised the current full App in the Codex browser with a local dev
account and isolated in-memory fixture transport at 127.0.0.1:5210. Desktop checks
confirmed first click, double-click, explicit Edit details, clean same-node
reselection, dirty-draft retention, Cancel, Save, and reopening the saved conversation
after page reload. A 390x844 viewport confirmed readable normal details, access to
Edit details in the scrollable pane, and return to normal details after Done.
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
