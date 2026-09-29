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
