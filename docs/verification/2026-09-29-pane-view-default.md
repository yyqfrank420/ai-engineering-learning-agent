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
capture geometry or model evaluation. Reverting the frontend patch restores the
prior interaction. The backend changes added below use a normal deployment rollback;
no database migration is included.

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
coverage 85.50%, function coverage 95.26% and line coverage 95.78%. Tests cover
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

## Dependency audit

The first PR run passed frontend tests and build, then failed the required audit
on an existing moderate advisory in jsdom's development dependency undici 7.29.0
(GHSA-3wwx-pv8p-q78v). The lockfile now pins its patch release 7.29.1, using the
registry's published tarball URL and integrity hash. No direct or production
dependency changes. An isolated npm ci install, audit, all 496 frontend tests with
coverage, lint and build pass; npm audit reports zero vulnerabilities. The shared
dependency directory used by other worktrees was left unchanged.

The lockfile change requires the existing protected staging evaluation before
merge. The presentation review records do not exempt dependencies. The Node test
runner still emits its existing experimental localStorage warning.

## Backend review and recovery

Review response schemas constrain record indexes to an enum of current candidate
positions. This bound survives the provider schema sanitizer. The parser retains
type, range and 32-citation limits, including the requirement that empty candidates
have no cited indexes. Empty-array cardinality remains a runtime check because the
provider removes maxItems. A fixed schema template keeps the review policy identity
stable when a correction changes the number of records. Component and connection
review prompt versions are v23 and v28.

Recovery prompts preserve cited witness records when additions can resolve a
finding. Connection corrections must preserve root-to-primary directed paths when
removing or retargeting records. Component corrections receive only instructions
within their stage's authority. Generation prompt versions are v33 and v28.
The final reachability validator, correction permissions, attempt limits and
provider budgets remain unchanged.

Focused verification passes 310 gate, policy and review-regression tests and
192 generation tests. Cases cover zero/one/38-record schemas, invalid indexes,
correction identity stability, retained witness connections, and rejection of
a repair that removes both entry paths to a primary tool. Ruff and whitespace
checks pass.

Runtime revision b6911940c78519c43e28ac2ae3c079f032b7799b passed fresh local
browser verification on 2026-09-29. The dev account used isolated SQLite storage,
local retrieval artifacts and real providers at 127.0.0.1:5212. Both the education
and research requests produced a rendered diagram and completed answer. A bounded
component correction completed successfully. The parent inspected the outputs,
opened normal node details, expanded a connection group, edited and saved a name,
then reloaded and reopened both conversations. The diagram, saved edit and answers
persisted. Browser error and warning logs were empty. The local run retained a
24-provider-attempt cap.

The full backend suite passed 3,106 tests with two environment-dependent skips and
91.85% statement coverage. Ruff, Bandit, and backend/evaluation/ingestion dependency
audits passed. CI policy passed 368 tests with five environment-dependent skips;
the manifest validates. Independent review found no outstanding defects. Existing
Starlette BlockingPortal and LangChain import deprecations remain; neither
dependency nor import was changed. Bandit also reports two existing redundant
suppressions in the CI runner, with no security findings.

## Production component ownership

Production component generation and review now require executable ownership of
applicable release controls before component responsibilities freeze. Evidence
curation, offline evaluation and controlled release operations can share compatible
owners. An explicitly declared upstream dependency may own curation or evaluation.
Frozen inference without an owned update or release remains exempt. Connection
review still owns contract and transition proof. The existing brief_coverage rule
carries this requirement; no rules, model calls, attempt limits or budgets were
added. Component generation v33 and component gate v23 identify this policy.
A normal code deployment rollback restores the prior policy.

Runtime revision a69cc062920359935c121b8fab2097ce63e303d7 passed fresh local
browser verification on 2026-09-29 using the same isolated dev account, SQLite
storage, retrieval artifacts and real providers at 127.0.0.1:5212. A serving request
produced a five-component diagram and completed answer. Expanding its monitor added
exactly one connected responsibility and retained the original components. The
parent opened normal details, expanded a named connection, edited and saved the
monitor's name, then reloaded and reopened the conversation. The six-component
diagram, saved edit and both answers persisted.

A separate request explicitly included an owned model release pipeline. Its
accepted design included evidence curation and offline evaluation owners, a release
controller, canary control, and recorded promotion and rollback outcomes. The
parent inspected the complete rendered diagram and answer, then reloaded and
reopened the saved conversation. Browser error and warning logs were empty.
All three turns completed without an LLM provider failure or correction. The local
iteration used 16 of its 24 permitted provider attempts. Web search reported a
provider failure and an empty fallback; generation completed with available
retrieval evidence. This does not establish general web-search reliability.

Focused policy, generation, gate and regression checks passed 507 tests. The full
backend suite passed 3,111 tests with two environment-dependent skips and 91.85%
statement coverage. Ruff, Bandit and all three dependency audits passed. CI policy
passed 368 tests with five skips, and the manifest validated. Independent source
review found no actionable defects. Existing dependency deprecations and redundant
Bandit suppressions are unchanged. Protected staging evaluation remains required
before merge.
