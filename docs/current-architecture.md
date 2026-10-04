# Current Architecture

Last updated: 2026-09-30

This is the current runtime contract for the production-quality demo.

## Runtime Overview

- `frontend/`
  - React + TypeScript + D3
  - authenticated, steerable WebSocket chat
  - private candidate rendering, typed progress events, and progressive explanation cards
- `backend/`
  - FastAPI
  - LangGraph routing with staged applied graph creation and editing by default
  - server-owned graph contracts, progressive previews, and deterministic maturity and render checks
  - Supabase-backed user/thread/message persistence
  - FAISS-backed book retrieval loaded by a non-blocking readiness task
- `ingestion/`
  - PDF chunking, embedding, and checksum-pinned FAISS artifact generation
- `infra/terraform/gcp/`
  - Cloud Run + Artifact Registry + Secret Manager

## Chat history

Each chat has a 75-message cap, counting both user and assistant messages. Completed
exchanges are stored atomically in pairs, so ordinary chat can store 74 messages.
Routing, answer synthesis, architecture roles, staged and legacy diagram generation,
review gates, critics, and node follow-up suggestions receive the complete saved
conversation. Message contents are neither truncated nor automatically summarised. Conversation history remains untrusted context;
the current request and the saved current diagram define the requested operation.

A failed diagram attempt exposes `generation_failed` after its failure explanation.
The assistant message stores `retry_request` with the original content and generation
options. A Retry generation button appears directly beneath that attempt and survives
thread reload. Confirmed failures start a fresh request with `retry_source_request_id`.
The server checks ownership and restores the failed turn's exact effective request,
including accepted steering. Only the expected graph version may change for an
extension retry. Raw messages retain the 2048-byte limit; canonical restored requests
use the existing three-steer envelope. A failure event remains uncertain until the
client confirms durable storage. Connection failures first recover the original
request using its idempotency key so a saved result is not generated twice. If no
result was committed, the client replays the original request with its acknowledged
`steering_updates`; the server validates and restores those corrections before
generation. Rejected corrections are never replayed. Retry preserves the composer
draft and runs against the current saved diagram.

Empty drafts do not appear in history, count toward the saved-chat limit, or become
the latest saved chat. A message or stored graph makes a thread visible. Retained
draft IDs remain addressable. An active first-turn lease prevents draft eviction.
The sidebar refreshes after generation finishes and ignores stale history responses.

Opening a blank composer never evicts a saved conversation. The existing history
cap is applied in the completed-turn transaction. Concurrent completions serialize
on the user's profile row in Postgres and SQLite's write lock locally.
Idle empty drafts have a separate cap of `max_threads_per_user`. Creating a draft keeps
its new ID and removes the oldest unleased empty drafts above that cap. A thread-scoped
chat lease protects an in-flight turn from cleanup. An older idle tab can lose its
draft after enough newer drafts are opened; its next request reports that the thread
is missing before generation starts. Draft admission, stream leases, and completed
turns take the same per-user lock in Postgres and SQLite's write lock locally.

## Request and Steering Flow

1. The frontend authenticates with Supabase and opens `WS /api/chat/ws`.
2. The bearer token is sent in the first frame, never in the WebSocket URL.
3. The client sends a `start` command with thread and mode controls.
4. LangGraph routes, restores terse follow-ups to the full design intent, and searches that canonical
   query rather than the raw fragment. Book retrieval and enabled web research run in parallel; the
   product UI enables web grounding by default while retaining an explicit book-only control. Their
   results become bounded source records. Staged authoring and review share these records and
   maturity-specific acceptance criteria. Legacy architecture planning retains its review checklist.
   Web research uses the authenticated Moonshot standalone Basic search API with
   API contract release `web_research_v2`. It sends one normalized canonical design
   query or original topic, without a model rewrite, retries, or fallback providers.
   Each research turn permits one actual API call, a 20-second server search timeout,
   and a 30-second HTTP timeout bounded by the worker's 30-second asynchronous deadline. A successful nonempty Basic search costs $0.002;
   no additional language-model tokens are generated. The nonempty provider result
   array incurs the fee before local filtering. Actual returned plaintext
   snippets, titles, and source URLs become bounded evidence. At most six sources
   reach synthesis after URL validation, noise filtering, and deduplication.
   Errors, empty results, or unusable snippets report research unavailable and
   continue with book evidence. Logs contain bounded provider/error codes, never
   queries or source bodies. Internal evaluation captures retained URLs with the
   exact submitted query and `moonshot_search` provenance. The existing
   `MOONSHOT_API_KEY` and `MOONSHOT_BASE_URL` settings are used; no scraping
   dependency or separate search credentials are required. API contract changes
   receive a new code release identity. Roll back the adapter and worker release
   together through the normal application deployment.
   Synthesis preserves sourced numbers, units, ranges, and comparators. Ambiguous source
   formatting is stated or its quantitative claim omitted, without silently repairing a number.
   The optional route classifier uses one low-effort provider attempt, at most 1,024 output
   tokens, and a 10-second deadline. Provider unavailability falls back to the search path
   with the same history, research setting, and graph controls. Explicit graph requests and
   recognized memory follow-ups keep their deterministic routes. During a classifier outage,
   an otherwise unrecognized design clarification may answer with history instead of rebuilding
   the earlier design. Authentication, request validation, evaluation quotas, and programming
   errors remain visible failures. Answer generation keeps its own retry and fallback policy.
5. `GRAPH_PIPELINE_MODE=staged` is the default for applied create and edit requests.
   `legacy` remains an explicit rollback. Concept diagrams retain their existing path.
   Each request uses one graph pipeline. Steering or cancellation ends the request-scoped state
   machine before a replacement request begins.
6. Kimi K3 at low effort produces a component wire, then a connection wire. The component wire
   contains the root index, title, assumptions, capabilities, and each component's label, type,
   responsibility, group label, group kind, and primary-flow membership. It does not contain a
   composition layer. Scoped edits instead emit additions and permitted field updates in
   server-selected slots. The server assembles complete candidates from immutable prior records
   and authorized removals. Both stages receive the same applicable criteria as their reviewers.
   Service expansion requests have a separate orchestrator planning call that selects existing
   application services and classifies the request as low or high complexity. Clients, stores,
   and standalone retrieval processes retain ordinary routing. High complexity selects the
   `expand_application_services` tool with `SERVICE_EXPANSION_MODEL=claude-opus-5-5` and medium
   effort for both draft stages and their bounded corrections. Low complexity uses the ordinary
   builder. This complexity decision is separate from prototype or production maturity.
   The server permits one to three internal nodes per selected service and preserves existing
   records. Each internal node has type `component`, the displayed label `Component`, and
   `parent_service_id` referencing its owning service. Wire `parent_index` resolves to that ID
   at the server boundary. Ownership survives projection, reload, and unrelated removals.
   Expansion connections stay within the parent's existing interfaces and internal components.
   Both render and semantic gates remain required. These expansions use the staged contract
   even when the default pipeline is legacy. Explicit answer-only requests retain the graph;
   high complexity answers use Opus 5.5 medium with a 180-second maximum, bounded by the remaining
   terminal deadline. A terse continuation uses the preceding user expansion request.
7. The server owns IDs, group records, breadth-first sequence derivation, projection, graph
   versions, selected maturity, exact edit admission, validation, state transitions, and
   persistence. The component-only candidate has no edges. During edits the live UI retains the
   connected diagram until a connected preview is available. Live regions place interfaces,
   application services, and data stores left to right, with logs below and external dependencies
   above the right side. Generic region names are resolved into these concrete presentation roles;
   stored groups remain unchanged. Component authoring v24 requests responsibility-specific names
   and keeps internal API adapters outside external groups.
   Zone borders and corners resize the frame around its contents, clamped to the padded member
   bounds. Resizing centers the complete content bounding box below the zone header, preserving
   relative node positions. Older asymmetric saved padding is centered without changing the frame.
   Additional padding is saved in `view_state.zonePadding`, keyed by presentation region ID.
   Dragging a zone translates every member and retains this padding. Nodes, zone frames, and borders
   snap to matching edges and centers within six screen pixels, with temporary alignment guides.
   Alt/Option bypasses snapping; Shift constrains node and zone movement to one axis. Arrow keys
   nudge a focused node, zone, or border by one diagram unit, or ten with Shift. Fit includes expanded
   frames. These controls do not alter graph contracts.
   Its render gate emits a reversible
   preview before one Sonnet medium component gate call. The full candidate follows the same render,
   reversible-preview, then connection-gate order. These previews remain nonauthoritative until
   semantic acceptance and persistence. One malformed gate result ends the request. Each layer has at most
   two candidates. A connection retry cannot reopen an accepted component layer.
   Primary membership selects the main walkthrough. Reachability traverses all accepted directed
   contracts, including feedback, deployment, and non-primary transit components. The server
   groups selected nodes by shortest distance and
   numbers the emitted stages consecutively; this walkthrough does not claim causal execution order.
   Initial and corrected connections use the same structural checks. Control behavior is reviewed
   against accepted responsibilities.
8. Prototype gates exclude production criteria. Production semantic requirements derive from the
   component wire's capabilities. There is no Opus root architecture pass and no final full-model
   gate. Sonnet 5.5 low writes the explanation after both gates pass. Deterministic explanation fallback
   keeps an accepted graph publishable when the explanation call fails.
   Each gate returns an array with one result per applicable rule, a short reason, and explicit
   candidate record indexes. One shared item schema avoids expanding the provider's compiled grammar
   for every rule. The server requires every rule exactly once and derives approval and blocking
   findings. Missing
   rules or malformed results fail validation. Protected evaluation captures retain the reasons,
   including passing checks. Candidate records carry server-assigned indexes in review prompts;
   reviewers do not count positions in an unnumbered array. No extra review calls are added.
   A repair review receives the previous validated rule evidence and the exact changed records
   and context. This history stays within its stage and request. Current complete rule results
   determine admission; prior approval cannot override a blocker or incomplete response.
   Reviewers retain evidence for unchanged paths unless changed dependencies or a concrete
   overlooked defect invalidate it.
   Prototype action review preserves explicitly requested controls and requires authorization
   and failure handling for concrete external mutations. Generic educational tools do not
   require a separate approval, audit, or rollback workflow. An existing component may own
   the guardrail. Production action controls remain unchanged.
   Naming, conciseness, and component detail depth do not block staged publication. Authoring and review share a
   materiality standard: reject broken requested behavior, contradictions, unusable main
   flows, and violated required controls. Optional implementation detail and alternative
   valid decompositions do not justify rejection. Correctness and explicit requirements
   remain binding. Generation aims for the smallest coherent graph; size limits are ceilings.
   Full connection generation authors exchanges: one directed contract and an optional return
   contract. The server expands the return with reversed endpoints. One-way interactions remain
   one-way, and synchronous/asynchronous timing does not imply a return contract. Canonical graph
   records, scoped edits, and record-preserving corrections continue to use directed edges.
   Shared criteria require necessary interactions across component
   boundaries; compatible internal operations belong in component responsibilities. Production
   component authoring receives the canonical final controls as conditional guidance for choosing
   executable owners. Component review checks scope, ownership, feasibility, and capability flags.
   The shared `learning_or_release` criterion includes owned offline training, batch updates,
   and releases requiring human approval. Live deployment and automatic feedback are not required.
   Dataset curation, passive downstream consumption, and frozen inference alone do not qualify.
   Component generation v46 and component review v27 share this ownership rule.
   The completed connection review checks ordering, failure outcomes, and retry controls,
   including same-key reconciliation and authorization, policy, freshness, and fencing before
   execution. Streaming transport mechanics guide authoring rather than independently blocking a
   diagram. Explicit requested behavior and contradictory delivery contracts still block publication.
   Harmless extra returns or duplicate descriptions are advisory; missing required payloads and
   paths that bypass required controls remain blockers. Retryable internal
   writes retain their controls even when the design has no external business mutations. Review
   identifies the retry, redelivery, competing delivery, or uncertain-commit behavior declared
   for the specific write before requiring its reconciliation protocol. A datastore or a
   committed/rejected response alone does not establish that behavior. Explicitly requested
   guarantees and declared unsafe retries remain blocking. A declared atomic durable commit of
   the effect and same-operation deduplication with safe same-key replay satisfies reconciliation
   within that boundary. A key alone, race-prone check-before-write, or separately committed marker
   does not. Effects outside that boundary still need safe target-side idempotency or authoritative
   reconciliation before retry. Compensation uses the same controls
   as normal actions; existing validation and approval contracts must explicitly cover it.
   Its producer must invoke those controls directly or through a declared delegation; another
   producer's validation path does not establish that coverage.
   Review reasons quote the control contracts and cover every applicable producer or path.
   Required inputs and execution outputs must reach each declared consumer with their actual
   payload across every intermediary. Connection reviews identify the producer, consumer, payload,
   and hop indexes. Matching request/reply pairs alone do not establish that route. Component
   containment and generic parent lifecycle ownership do not supply a missing child result;
   a reply naming a different artifact cannot carry it implicitly. Explicit same-owner handling
   and authoritative persistence with a consumer read remain valid without extra edges.
   Deterministic proposal validation applies only to declared model-action producers, including
   model-selected read-only and internal tools. Answer-only inference without proposed actions
   needs no per-action validator. Authoritative lifecycle ownership and correlated provenance
   and audit remain required where applicable.
   Capability flags select system-level review criteria. Individual retrieval obligations apply
   to their declared artifact and consumer path. Outcome-data reads do not impose a factual
   retrieval dependency on an unrelated creative generator. Material factual claims still need
   entailment validation for both internal and external evidence.
   Walkthrough reachability does not establish execution or authorization. Semantic review still
   requires actual runtime/control contracts for invocation, approval, and execution; a feedback
   or deployment connection cannot substitute for those behaviors. This lets offline evaluation
   appear in a walkthrough without inventing an invocation or rewriting its evidence connections.
9. The transport atomically persists graph data and its server-only contract before emitting
   authoritative `graph_data` and `done`. `auto` edits inherit stored maturity. A legacy graph with
   no stored contract defaults to prototype. A bounded edit that selects a different maturity
   fails before model calls with instructions to retain the current maturity or explicitly rebuild.
   Scoped review includes the prior objective, exact delta, and affected dependencies. Prior approval
   is trusted only when the stored graph fingerprint, both reviewer identities, and global context
   still match. Changed maturity, capabilities, assumptions, title, or root require full review.
   Both gates still inspect current records against their applicable semantic requirements.
   Reviewer identities bind prompt content, model settings, rubric definitions, and response schema.
   Scoped projection preserves authored edge presentation and sequence descriptions. Component
   labels are reviewed by the staged component gate; edit admission does not reapply the legacy
   generic-label heuristic to those accepted records. Exact edit authority and structural checks
   remain mandatory. Authorized node
   deletion removes only that node's sequence memberships and incident edges, then renumbers steps.
   Only an explicit graph rebuild can authorize restaging at another depth. Scoped edits preserve
   locked assumptions and prior composition records. Capability changes are reviewed against the
   complete candidate and determine subsequent connection requirements. Adding one responsibility
   with an unspecified attachment permits one or two directed edges between that responsibility and
   the named existing anchor. It does not permit unrelated endpoints or baseline changes. Explicit
   connection counts and directions retain exact authority.
   The prior durable graph is restored after failure, retry exhaustion, steering, stop, timeout, or
   persistence failure. The 90-second prototype first-preview target is an SLO. Generation calls
   reserve 130 seconds, gates reserve 55 seconds, and saved time can extend a generation call to
   240 seconds while preserving downstream budgets. The request ceiling includes orchestration
   and private renders.

The model never writes SVG. Its typed graph JSON is an intermediate representation with named
responsibility zones, ordered sequence steps, and runtime/control/feedback/deployment edge classes.
The D3 renderer deterministically compiles that structure into responsive branded SVG, preserving
interaction, accessibility, layout evaluation, and compatibility with previously stored graphs.

The server sends the authoritative 1440 by 960 CSS-pixel evaluation viewport and 11 CSS-pixel
post-fit node-title floor with each private candidate. The private evaluation renderer chooses horizontal or ranked vertical placement from the
resulting fit scale. A rank-ordered compact layout covers the full 60-node backend safety ceiling
when either ordinary plan would be unreadable. Bottom-lane height is derived from its densest
column. The browser still measures the real SVG. The server rejects overlapping node cards or
responsibility-zone boundaries, clipped nodes or edges, missing required labels, and unreadable
node titles. The non-browser staging client consumes the same criteria from the candidate event,
and its compact fallback covers the same 60-node ceiling. The browser and staging clients reject a
candidate that omits or changes the fixed criteria. The capacity correction passes offline tests and a local Chromium replay of
paid diagnostic `31825436257`; that paid workflow did not emit protected publication success.

The interactive canvas keeps left-to-right placement at every pane width. It opens at a readable
scale with panning; Fit provides a full-map overview. Live layout version 17 invalidates older
vertical positions. `diagramConnections.ts` projects directed records into one connection per
unordered component pair. Both arrowheads appear only when records exist in both directions.
Selecting a connection opens every underlying directed exchange, including its description and
technology. This projection never changes persisted edges or the data sent for expansion.

The overview selects a connected spanning forest from real relationships, preferring runtime
flows and shorter connections. Component hover or keyboard focus reveals incident relationships;
Connections reveals every bundled pair. One effect owns live path opacity, hit targets, keyboard
access, and walkthrough visibility. Future-step components and their connections stay hidden even
when Connections is enabled. The live view does not create inline edge labels or step badges.
Local orthogonal routing tries clear corridors around node cards before taking outer detours.
Routes are cached within each render and recomputed after dragging. Overlapping manually placed
cards can still force intersections; this router does not solve arbitrary obstacle mazes.

Declared groups use semantic tier placement with soft background regions and one heading per region.
This keeps unrelated components outside each boundary. Learner-facing cards omit repeated
zone and tier labels.
Cards show the component name and technology/type subtitle; hover and component details expose its description.
These disclosure rules do not delete graph data
or change private candidate evaluation; publication checks alone do not verify live-view usability.

## Direct graph editing

The selected-component inspector edits its name, type, technology subtitle, and responsibility
description. The selected-connection inspector edits each underlying directed record's label,
technology, description, flow class, and sync mode. A bundled visual connection does not merge its
directed records. Double-clicking a node, or pressing F2 while it is focused, focuses its name field.
The existing D3 canvas, visual language, learning details, and chat expansion remain in place.
Freeform notes are outside the editor. Accepted edits append a durable graph revision.

Edits are drafts until explicit Save. Cancel discards the draft. Closing or changing selection must
not silently discard unsaved text. The UI distinguishes unsaved, saving, saved, and failed states;
a failed save retains the draft for correction or retry. `PATCH /api/threads/{thread_id}/graph`
accepts only the editable fields and an `expected_version`. The server applies the edit to the
canonical stored graph, validates it, and persists a new version atomically. A stale version or
active generation lease returns 409. Node IDs, edge ordering and endpoints, sequence membership,
groups, and saved layout remain stable. An edge index selects a directed record only within the
submitted `expected_version`; applied `edge_id` and `relation` are derived metadata and can change
when its label changes. No client-side preview becomes canonical before the successful response.

An edited graph no longer carries the generated approval of the prior graph version. Attribution
attached to a changed record is removed; any retained source context does not claim that the
learner's wording was source-authored or reviewed by the generation gates. Manual values are marked
per record in `user_edited_fields`. Later scoped patches preserve unrelated manual fields and their
markers; an explicit patch that changes a marked field replaces that value and removes its marker.
Compatible canonical graph selection carries manual fields across only where record identity is
unambiguous. An explicit new create starts fresh in a new chat. Subsequent scoped edits use the edited canonical
graph and follow their applicable validation and approval path.

The interaction borrows the direct text editing, connector labeling, and selection-dependent
controls documented in Canva's [text editing](https://www.canva.com/help/add-and-edit-text/),
[connector](https://www.canva.com/help/connect-lines-to-elements/), and
[editor](https://www.canva.com/help/glow-up/) guides. These sources inform the small editing
surface; they do not define this application's persistence or approval contract.

FastAPI becomes available after database initialisation, then loads the FAISS artifacts and index in
a background thread. `GET /api/prepare` reports the current server-owned milestone and completed/total
units. The frontend shows the current milestone with an indeterminate loading indicator. Milestone
counts do not predict elapsed time, so startup has no percentage or determinate progress bar.
The indicator stops animating when reduced motion is requested.
Authenticated workspaces start this check automatically, including after a page refresh. Checks run
serially and stop on failure until the user chooses Retry. Workspace teardown cancels requests and
polling; late responses cannot update a different account or a newer attempt. A token refresh for the
same user does not restart preparation.

Diagram-enabled turns retain the canvas after completion, including a clear empty state when no
diagram is published. The conversation shows short labels for concurrent active operations and
the latest completed milestone. Each server phase owns its active and terminal events. Book
retrieval runs off the event loop so web search and stream delivery can continue. The canvas has
no progress overlay. Internal event titles, details, and completed activity logs are omitted;
terminal errors remain in the conversation.
The frontend reveals validated explanation sections while generation continues once each section's
graph version matches the displayed, painted diagram. Generic or unversioned answer text waits
for the terminal result and graph paint. D3 reports readiness
after fonts and two animation frames, with a three-second terminal grace period in the hook.
Private candidate evaluation measures synchronous SVG geometry without waiting for paint. Its
evaluator remains mounted across chat and dashboard routes and bounds image capture to three
seconds. A painted preview can release matching versioned explanation sections before the final save;
the terminal commit remains the authority for graph history. Text-only mode continues streaming normally; a terminal
failure without a graph releases the available explanation instead of waiting for a missing graph.

Before an idle diagram-enabled submission, the composer calls the authenticated, read-only
`POST /api/threads/{thread_id}/diagram-intent` endpoint. The composer always sends automatic depth,
graph on, and research on. A new conversation can generate immediately. With a saved diagram,
clear additions extend it, explanations leave it unchanged, and ambiguous requests show an inline
choice: Extend this diagram or Start a new chat. The separate option creates and opens a chat
before sending. Unavailable intent checks and failed chat creation retain the draft with feedback.
Typed `graph_action` and expected graph version travel through both transports. Server admission
rejects fresh creation over a saved graph and rejects stale extension requests before model calls.

## Diagram history

`graph_revisions` retains accepted graph bodies with their server-only contracts, parent links and
request labels. `chat_threads.active_graph_revision_id` identifies the working revision;
`chat_messages.graph_revision_id` associates an answer with its result. Publication and manual
content edits append revisions in the same transaction as their canonical state. A layout save
updates the active revision and materialized graph together, without creating a content revision.

Undo activates the parent; Redo returns along the path just undone. An explicit restore, a content
change or a thread switch clears that session path; without one, Redo selects the newest child.
All retained branches remain in a compact numbered version picker. View diagram links beside
answers provide the main history entry and indicate the viewed revision. Earlier versions open
a read-only preview with Restore and Return to current controls. Selecting the current answer
returns to the working graph. Chat scrolling never switches the graph. Before a transition, the
canvas flushes pending layout saves. Failed saves keep the user in place. Existing positions remain
fixed during extension; new components are placed around them.

History endpoints are owner-scoped. Restore shares the generation lease and compares the current
graph version, then assigns a fresh activation version. Repeating an already-active restore is a
no-op. Old diagrams first become checkpoints when read or changed by this release; overwritten
historical graphs cannot be recovered without another saved artifact. See
[the continuity contract](graph-history-contract.md) for operation boundaries and rollout rules.

Every production frontend turn includes a UUID `client_request_id`. Completed user/assistant
pairs are unique on that key at the database boundary, and a network retry replays the stored
assistant response. The temporary SSE compatibility endpoint still tolerates legacy callers that
omit the key; the WebSocket product path always supplies it.

Thread admission, active streams, chat requests, OTP/internal login attempts, and public analytics
capture use shared transactional storage. Rate-limit identifiers are HMAC-derived before
persistence, so Cloud Run scale-out neither resets the limits nor stores raw emails/IPs in the
limiter table.

The staged path gives each active role one explicit owner. Kimi K3 low authors bounded component
and connection wires. Sonnet 5 reviews components at medium effort and connections at low effort,
with the same complete rule coverage and 16,384-token completion ceiling. Connection review uses
low effort after a medium-effort repair review exhausted that ceiling before returning a verdict.
Connection generation v40 and review v37 require complete payload-route witnesses and distinguish
applicable proposal validation from answer-only inference.
Incomplete reviews still reject publication. The server owns graph mutation,
validation, maturity, and all state transitions. Sonnet 5.5 low writes the explanation stream and has a
deterministic fallback. The no-retry path makes five application model calls. The bounded maximum
is nine. Renderer infrastructure failures add no model calls. Retrieval and acceptance criteria
do not add model calls.

Browser diagnostics distinguish the first component map, the first connected draft, and the
new approved graph. Restored versions do not count as new approvals. Reports include latency
means and first-review pass counts, with failed attempts retained in the review denominator.
The current latency experiments and their limits are recorded in
[graph-latency-experiments.md](graph-latency-experiments.md).

Text answers use one short scope and evidence contract. UI depth changes detail within the user's
task; it does not turn a memory, summary, or explanation request into a system design. Prior assistant
proposals become requirements only when the user adopts them. Graph publication instructions apply
only to graph answers. Internal evaluation captures the exact book and research strings passed to
synthesis, including empty context, under the prompt release identity.

Graph explanations use `EXPLANATION_MODEL` (default `claude-sonnet-5-5`) independently of
`ORCHESTRATOR_MODEL`. Prompt release `architecture_blocks_v32` includes the user's September 28
writing rules against filler, stock phrasing, and decorative formatting. These rules apply to
authored prose; exact graph labels, citations, quotations, code, and schema keys retain their
original form. They do not add a publication gate. Routing and graph authoring models are unchanged.
The model can be rolled back through `EXPLANATION_MODEL`; reverting the prompt change restores v30.

The September 12 simplification keeps two authoring stages because a complete graph can be a large
output. Component review catches responsibility defects while that stage can repair them; connection
review owns interactions after components freeze. The remaining limitation is explicit: connection
correction cannot redesign components. A rejected graph stays unpublished. This bounded pipeline
still makes five calls without correction; prompt simplification does not establish lower live latency.

Semantic corrections use the existing delta assembler. The server retains unaffected
records in order and permits updates to the review's indexed records plus bounded additions.
Cited records can be witnesses to a missing path without needing changes. Each semantic
correction slot accepts `null` to retain the original record verbatim, or a complete
authorized update. Explicit user edits keep their non-null field contracts.
An indexless finding permits updates across the candidate. Capabilities describe the
complete corrected design; other component metadata stays fixed unless the finding concerns
it or is global.

For a first creation with no saved graph, the second existing attempt uses compact recovery.
It aims for a simpler overview of the same requested core workflow at the same maturity.
Only explicitly cited rejected records may be removed; an indexless global finding permits
updates but grants no removal authority. Removals are validated, and component root indexes
are remapped by the server. A removed required behavior still fails the complete semantic review. Connection
recovery cannot change accepted components. Structural corrections retain the same contract
and capacity checks. No additional provider attempts, review calls or deadline allowance are
introduced. An exhausted or unavailable review still cannot publish an invalid candidate.

Accepted recovery graphs carry server-owned `detail_level: overview`. This marker is bound
to the reviewed graph fingerprint and persists with the graph. The canvas and explanation
identify the overview, and subsequent edits retain that disclosure. Supporting detail may be
simplified; required outcomes, declared capabilities and controls may not be hidden. Existing
graphs, including explicit rebuilds with a saved baseline, retain their mutation authority
and are restored unchanged on failure. They never enter this new-create recovery path.

The `staged_graph_admission` analytics event distinguishes accepted, recovered, preserved and
withheld outcomes without storing graph text or reviewer reasons. Admission is not evidence
of durable delivery; correlate it with the transport's persistence and publication events.
Normal users receive concise correction activity without internal findings. Gate calibration
still requires human review of rejected and accepted examples; an automatic pass does not
establish a false-rejection rate or a guarantee of semantic correctness.

The staged render gate treats edge clipping, initial inline edge-label visibility, repeated
per-node group labels and zone-boundary overlap as presentation advisories. The interactive
canvas has panning, bundled connections and named regions that its private fit render lacks.
Capture failures, wrong node or edge counts, node overlap, clipped nodes and unreadable titles
remain blocking. Legacy render callers keep their existing checks. These advisories do not
consume model retries or change the semantic review.

Prototype memory does not itself create an approval or version gate. Gates required by
the request, accepted responsibilities, or production criteria remain binding.

During steps 4-7 the client may send `steer`. The server cancels the active workflow, emits
`response_reset`, and restarts with the steering correction folded into the same turn. `stop`
cancels server-side work. Steering is content-filtered, size-bounded, and capped at three updates.

## Why Both LangGraph and asyncio Exist

LangGraph owns workflow state, branches, and the review/revision loop. Ordinary `asyncio` remains
the correct local primitive inside nodes for parallel RAG/research I/O and transport cancellation.
The distinction is orchestration versus concurrency, not framework versus no framework.

## Compatibility Boundary

- `POST /api/chat` remains as a temporary SSE compatibility endpoint.
- `POST /api/node-selected` remains SSE because it is a one-shot server-to-client stream.
- New chat functionality belongs on the WebSocket protocol.
- Durable LangGraph checkpointing is intentionally not enabled yet: live callbacks, tasks, and
  tool bindings are request context rather than persistent graph data. Moving those handles into
  runtime context is the prerequisite for a database checkpointer.
- `GRAPH_PIPELINE_MODE=staged` is the default for applied create and edit requests.
  Protected and production deployments explicitly use the versioned backend default.
  Manual scheduled evaluations may select either mode for diagnostics or full-corpus review.
  The legacy whole-graph repair loop remains an explicit rollback and cannot mix writes with a staged request.
- The live staging harness also uses the WebSocket protocol. It submits a bounded contract render
  so deployment model evaluations cannot bypass the diagram gate; the product browser remains the
  authoritative evaluator of the actual D3 canvas at the fixed server-contract viewport.

## Primary Code Paths

- backend entrypoint: `backend/main.py`
- WebSocket protocol: `backend/api/chat_websocket.py`
- compatibility SSE endpoints: `backend/api/sse_handler.py`
- orchestration: `backend/agent/graph.py`
- applied designer: `backend/agent/nodes/graph_worker.py`
- independent reviewer: `backend/agent/nodes/graph_critic.py`
- stable review frame: `backend/agent/architecture_playbook.py`
- sequential architecture and review roles: `backend/agent/nodes/architecture_workers.py`
- browser evaluation channel: `backend/api/diagram_evaluation_channel.py`
- progressive explanation stream: `backend/agent/explanation_blocks.py`
- frontend transport: `frontend/src/services/agentTransport.ts`
- frontend stream state: `frontend/src/hooks/useAgentStream.ts`

The older spec in `docs/superpowers/specs/2026-03-31-ai-learning-agent-design.md` is design history,
not the current runtime contract.

## Accepting a preview during review

An explicit composer Stop during a rendered staged preview sends `accept_preview` with the
active request ID and exact eligible graph version. It leaves the socket open. The request-scoped
review control cancels only the active semantic reviewer, then the workflow finishes the answer
and persists through the normal turn transaction. Component acceptance preserves that component
candidate and generates its connections; deterministic validation and private rendering still run.
The remaining semantic review is skipped.

Publication uses `user_accepted`, with skipped review and accepted preview provenance in the
server-owned graph contract. Skipped review is never represented as model approval or reused as
completed review on a later edit. The UI disables repeated Stop and steering while finishing.
Navigation, account changes, disconnects, and normal cancellation never imply acceptance.
Stale request or candidate commands are rejected without cancelling the active turn.

Live activity is a bounded public feed derived from workflow events. Known startup, routing,
and steering statuses produce public context steps immediately. The expanded panel shows
"Working on your request." while no step has arrived. Book search, web search, rendering,
and review appear as tool steps; public design updates explain the current phase. Raw provider
reasoning, signatures, graph JSON, and retrieved tool content stay outside this feed.
The transports persist the activity with the completed message. Reload restores its steps
and duration without another model call. Completion collapses the feed, which can be reopened.
