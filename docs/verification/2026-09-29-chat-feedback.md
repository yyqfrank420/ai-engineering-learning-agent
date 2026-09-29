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
and 198 staged workflow tests. Lint, TypeScript and production build passed.

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

The prior PR61 staging research connection-wire failure remains open. This change does not
claim that the ordinary generation quality gate or production deployment has passed.
