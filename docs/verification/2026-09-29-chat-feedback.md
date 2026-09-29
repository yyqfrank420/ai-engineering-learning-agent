# Live chat feedback and preview acceptance

Stop during a rendered component or connection review accepts that preview for the current
request. Component acceptance preserves its components, finishes connections, and then writes
the answer. Remaining semantic reviews are skipped; deterministic integrity, edit authority,
private rendering and durable persistence still apply. Acceptance provenance is stored in the
graph contract. Navigation and disconnect retain cancellation behavior.

The chat shows concurrent operation status, an initially expanded provider thinking feed and progressive
validated answer sections after the matching graph has painted. Provider thinking is bounded
plain text, lives only in the active frontend turn, and adds no model calls. It is unverified
provider output and may quote request context. It is never used as the answer or persisted in
chat history or analytics.

## Design evidence

Impeccable's Operate and Clarify guidance calls for familiar controls, restrained styling,
short labels, progressive disclosure and truthful operation feedback. The existing house style
is retained. Assistant sections use prose instead of individual cards; the user bubble remains.

NN/G's [April 2026 chatbot study](https://www.nngroup.com/articles/ai-chatbots-design-guidelines/)
identifies forced autoscroll as a reading problem and recommends progressive disclosure.
The chat stops following new content when the reader scrolls away, with an explicit route back
to the newest content.

Anthropic documents [streamed thinking summaries](https://platform.claude.com/docs/en/build-with-claude/thinking).
Kimi documents a [separate reasoning stream](https://platform.kimi.com/blog/posts/kimi-thinking).
The existing adapter already yields this data. Forwarding it does not change provider parameters,
prompts, or generation call counts. Structured graph JSON and signatures stay out of the feed.

## Transport decision

Chat retains its bidirectional WebSocket. Steering, preview acceptance and browser-render
evaluation uploads must reach the active task and its process-local controllers. SSE with POST
commands would need cross-instance command routing and the same render callback. The existing
SSE endpoint provides neither. Vercel serves the frontend; chat connects directly to Cloud Run.

Provider thinking chunks are forwarded immediately over the current socket. User collapse
persists as text arrives. No timer simulates typing, and no extra model call creates feedback.

An interrupted connection still cancels an unfinished turn. Durable runs with sequenced event
replay are separate future work; changing transport alone does not provide resumability.

## Verification status

Full offline checks passed 3,199 backend tests (92% coverage), 543 frontend tests and 368 CI
policy tests. Subsequent targeted runs passed 108 provider/adapter tests, 90 thinking/hook tests
and 198 staged workflow tests. Lint, TypeScript and production build passed. CI then exposed a timing-sensitive App test:
the mock allowed sending while history was loading. A deferred-history regression reproduced
it, the mock now honors the disabled control, and the final full frontend suite passed 544 tests.

Fresh local run `local-stop-accept-d07f91f2-02ab-43a6-99c8-dfe701016e2c` used an empty SQLite
store and one new tutoring prompt. Real provider thinking appeared in the browser. Stop during
component review accepted eight components; the run completed 13 edges and one answer section.
The final nodes preserved every component field except the deterministic replacement of the
preview's pending type label. Reload and reopen preserved the exact graph, contract, messages
and revision. Provider telemetry and its four attempt-ledger entries were unchanged.

There were four provider attempts: Kimi components, canceled Sonnet review, Kimi connections
and Sonnet 5.5 explanation. The known cost subtotal is $0.078350 using repository prices.
The canceled review has incomplete usage, so the total cost is unknown. No additional model
calls generated feedback. Browser console checks found no warnings or errors.

After that run, operation feedback was corrected to mark component/connection generation
complete before rendering and review. The focused ordering regression passed without another
paid run. The live run validates the preceding frozen source plus the same generation behavior.

At that point, the prior PR61 staging research connection-wire failure remained open.
The Stop test did not establish ordinary semantic approval or production readiness.

## PR review corrections

GPT-6 Sol at extra-high effort reviewed the full PR and found three defects:

- A typed Extend request at graph capacity could fall through to a rebuild when the request
  contained rebuild wording, including "do not rebuild". Scope failures now preserve the saved
  graph and contract before interpreting that text or calling a generator.
- Stop could accept a component preview hidden behind the saved connected graph. Acceptance
  now requires the exact preview to be displayed, painted and matched to the review version.
  Missing, hidden and unpainted previews retain cancellation behavior.
- Both continuity clarification guards sent `response_delta.delta`, while the frontend reads
  `response_delta.content`. Both writers and their regression tests now use the protocol field.

The final frontend suite passed 550 tests across 43 files. Focused backend suites passed 202
staged workflow tests and 121 agent workflow tests. Scoped lint, TypeScript and diff checks
passed. The reviewer independently ran 16 backend regression scenarios and confirmed all
three findings were resolved without a new regression.

A provider-free browser fixture verified Stop on a painted component preview sends
`accept_preview`, then receives connections and an answer. With an existing connected graph
visible and a hidden component preview, Stop sends `stop` and preserves the saved diagram.
The fixture deliberately reused a version identifier to check payload identity as well as
version matching. Browser console checks found no warnings or errors. No paid model calls
were used for these deterministic scope, protocol and interaction corrections.

## Connection failure diagnostics

The earlier staging failure retained only `connection_wire_invalid` and a fingerprint of
the preceding candidate. Connection validation now records a constant reason, an indexed
field path and the canonical fingerprint of the rejected wire. Raw model output and labels
stay out of the diagnostic. Error codes, exception messages, repair findings, validation
decisions and retry limits are unchanged. Generation and workflow suites passed 409 tests;
scoped Ruff and diff checks passed before the authorized fresh release evaluation.
An independent old/new parser comparison matched accepted payloads, rejection codes and
repair findings across 33,024 cases, including malformed inputs, duplicate edges and root
reachability checks. All 13 diagnostic reasons were exercised.

## Preserve exchanges during semantic repair

Protected run `36564110437` passed seven browser journeys and failed research. Both research
connection candidates validated and rendered, but the repair changed a planner-to-executor
request into a second executor-to-planner reply. Its paired reply remained unchanged. The
semantic gate correctly rejected the missing tool invocation. This run did not reproduce the
earlier malformed-wire failure.

Initial generation authors request/reply exchanges. New-graph semantic recovery now retains
that representation when exact exchange provenance and cited edge findings are available.
Findings map to whole exchange slots. Updates preserve endpoints and existing replies;
rewiring requires an explicit cited removal plus a complete replacement. Uncited exchanges
and accepted components remain intact. Expanded edge limits still apply. Global or mixed
global findings, missing provenance, and explicit user edits retain their existing canonical
edge behavior. Review rules and attempt limits are unchanged.

The two affected suites passed 422 tests. Broader checks passed 2,431 agent/RAG/LLM tests,
411 evaluation-quality tests and 260 API integration tests, plus repository Ruff and Bandit.
GPT-6 Sol at extra-high effort independently verified 1,548 mapping/removal cases, 496 fallback
parity cases, 5,160 endpoint/reply guard cases, 620 malformed provenance cases, expanded edge
capacity and 15 changed or explicit-edit regressions. It found no actionable defects.

Local verification used HEAD `2f296503271e04530a75b3254497a48d4654147e` plus source diff SHA256
`d51ebfd33b566c7de6ef55a6e1131446a2cae061c40f6b88c1d40347ad0652bd`. Separate empty SQLite
stores and unique run IDs prevented generation reuse. Both tests used the current frontend,
normal deterministic/render checks and current model settings. Neither used Stop acceptance.

- `local-connection-fixture-5e81a963-a44b-4df5-87c3-90c6df7b0543` replayed the historical
  components and first rejected connections. One live repair and one live review produced an
  approved 11-node, 36-edge graph. The lost invocation and its reply remained byte-for-byte
  intact. This establishes repair behavior, not fresh generation. Two provider attempts,
  estimated cost $0.102104 with complete usage.
- `local-connection-fresh-f07ef8dc-ef76-4747-bb23-d17208705a1d` submitted the research request
  in a new empty chat. Its 9-node, 18-edge graph passed both semantic gates on the first
  attempt, followed by the Sonnet 5.5 answer. Five provider attempts, no repairs or fallbacks,
  estimated cost $0.132967 with complete usage.

Both diagrams were inspected in the browser, saved as one revision, and reopened after
reload. Nodes, edges, contracts, messages and provider-attempt counts remained unchanged.
The fresh graph retained the Fit camera adjustment made during inspection; the fixture
graph was byte-identical. Private render reports recorded no overlap or clipping. Prices
use the repository's `2026-09-28` price release. These local checks precede the new protected
release evaluation.

Local test lesson: parallel shards in one checkout can share `data/sessions.db`. Their
autouse rate-limit cleanup caused two false OTP failures. The API shard passed all 260 tests
alone with the same order and source. Run local shards sequentially or use distinct
`DATA_DIR` values; CI jobs already use separate checkouts.


## Component ownership, diagnostics, and additive zones

Protected run `36564110437` on `2f29650` passed seven browser journeys and failed research after a repair removed a tool invocation. The paired-exchange repair in `2c4a9da` preserves request/reply units and passed separate captured-repair and fresh-generation checks. Protected run `36569546773` on `2c4a9da` then failed education, the initial serving graph, and a critical grounding judgment. Neither protected failure is recorded as a release pass.

Education's second component output failed deterministic parsing before rendering. The malformed output was not retained, and its old diagnostic hash referred to the first candidate. Its exact invalid field remains unknown. Component diagnostics now retain safe reason codes, indexed paths, and the rejected-wire fingerprint while preserving acceptance, public errors, and model repair findings. A single fresh captured-context correction parsed ten components for $0.033784; it did not reproduce or identify the original malformed field.

The serving failure assigned release-review operations to a passive telemetry store after component responsibilities froze. Production component review v22 now receives the shared conditional downstream controls and checks executable ownership before freezing those responsibilities. Compatible controls may share an owner. Prototype criteria and connection-stage requirements remain unchanged. A separate one-call owner-review fixture caught the missing approval owner for $0.055558.

External judge v18 keeps corpus anchors and critical flags unchanged. It evaluates correctness separately from grounding and follows declared intermediary routes before reporting contradictions. The exact-artifact judge attempt failed with APIConnectionError at 60 seconds; no judgment or complete usage was available. Its charge is unknown. The remaining authorized attempt rejected a critical grounding negative control for $0.077026. Two attempts, no retries. That control does not establish a judgment on the exact artifact.

Fresh v33 application runs used HEAD `2c4a9da3c8cd6e97cdd9ae4ad855323e12482776` plus diff SHA256 `157404346bcde35fe3e300b525d2bc50b851eaab01156756ac28c2c5540091df`, recorded in the separate education and serving manifests. Education produced 10 nodes/24 edges and serving produced 7 nodes/11 edges, each with first-pass reviews, five calls, and successful reload checks. Education cost $0.138312. Serving's later extension failed admission after four calls because a new component joined an existing zone; raw evidence and an offline reproduction identified immutable group membership as the cause. The baseline remained 7 nodes/11 edges/one revision. Serving's combined journey cost was $0.228326.

The new v34 extension contract permits new node IDs appended to compatible existing zones or placed in new zones. Old members retain their order and all saved metadata. Existing nodes cannot move groups. Invalid membership is preserved through presentation handling so admission can reject it. The frontend also retains a resized generic region's identity when an earlier group gains the same role; saved zone padding continues to apply.

Validation includes 1056 integrated stage/graph-patch tests and 552 frontend tests; these counts overlap earlier runs. Broader backend checks passed 2462 agent tests and 414 evaluation tests before the zone changes. Ruff and Bandit passed. Independent Sol review reported 58,641 parser parity cases, unchanged connection criteria/review identity for 16 capability/depth combinations, six ownership/scope scenarios, 57 targeted regressions, and unchanged anchors/critical flags across all 20 judge cases. These checks do not establish model adherence.

## Fresh v34 extension and layout/history verification, 2026-09-29

The newer source passed one fresh extension against the saved approved serving baseline. Exact HEAD `2c4a9da3c8cd6e97cdd9ae4ad855323e12482776`, frozen diff SHA256 `1854cbcc73f7d5a8875dc10cea1beb105358633063317786c1022d2928dd5655`; full identity and evidence: `work/component-repair-verification/extension-after-fix/RESULTS.md`. This is fresh extension evidence, not fresh baseline creation. Component prompt v34 permits append-only group membership. Integrated validation passed 1,056 backend and 552 frontend tests; independent final review reported no blocking findings.

The parent moved Serving Monitor and resized its zone before submission. The fresh extension added Alert Triage Service and two connections, producing 8 nodes/13 edges/4 groups. Both reviews passed first attempt, both private renders passed, and all original seven node records, eleven edges, saved coordinates and zone padding stayed exact. Revision 1 retained the original manually edited layout. Actual UI Undo/Redo restored the respective graph and contract apart from deliberate new graph-version identities; reload preserved the Redo graph, answer, messages and revisions. Provider attempts remained five through history operations and reload. Complete estimated cost $0.168628, zero repairs/fallback/cache tokens.

A scratch guard initially rejected two normal analytics_capture ledger rows before generation. Zero provider calls or persisted messages resulted. The corrected guard checks only llm_provider_attempt; original failure evidence is retained in `extension-after-fix/guard-failure/`, with unchanged source/run identity. Lesson: provider-attempt accounting must filter its event type rather than assume the shared rate-limit table contains only paid calls. Parent browser warning/error inspection returned an empty list. No deployment or merge conclusion is implied.
Isolated backend8035/frontend5220 were stopped after final checks; all artifacts remain.
