# Current Architecture

Last updated: 2026-09-22

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

## Request and Steering Flow

1. The frontend authenticates with Supabase and opens `WS /api/chat/ws`.
2. The bearer token is sent in the first frame, never in the WebSocket URL.
3. The client sends a `start` command with thread and mode controls.
4. LangGraph routes, restores terse follow-ups to the full design intent, and searches that canonical
   query rather than the raw fragment. Book retrieval and enabled web research run in parallel; the
   product UI enables web grounding by default while retaining an explicit book-only control. Their
   results become bounded source records. Staged authoring and review share these records and
   maturity-specific acceptance criteria. Legacy architecture planning retains its review checklist.
   Web research selects Brave explicitly through DDGS with safe search. Ordinary research keeps
   the original topic in one query; applied design requests also search the domain workflow and
   failure modes. At most six source snippets reach synthesis. Search results carry no guarantee
   of relevance or factual support; synthesis must cite supported findings or state the evidence
   limitation. Internal evaluation captures the retained URLs' query and backend provenance.
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
7. The server owns IDs, group records, breadth-first sequence derivation, projection, graph
   versions, selected maturity, exact edit admission, validation, state transitions, and
   persistence. The component-only candidate has no edges. Its render gate emits a reversible
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
   gate. Opus low writes the explanation after both gates pass. Deterministic explanation fallback
   keeps an accepted graph publishable when the explanation call fails.
   Each gate returns an array with one result per applicable rule, a short reason, and explicit
   candidate record indexes. One shared item schema avoids expanding the provider's compiled grammar
   for every rule. The server requires every rule exactly once and derives approval and blocking
   findings. Missing
   rules or malformed results fail validation. Protected evaluation captures retain the reasons,
   including passing checks. Candidate records carry server-assigned indexes in review prompts;
   reviewers do not count positions in an unnumbered array. No extra review calls are added.
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
   The completed connection review checks ordering, failure outcomes, and retry controls,
   including same-key reconciliation and authorization, policy, freshness, and fencing before
   execution. Streaming transport mechanics guide authoring rather than independently blocking a
   diagram. Explicit requested behavior and contradictory delivery contracts still block publication.
   Harmless extra returns or duplicate descriptions are advisory; missing required payloads and
   paths that bypass required controls remain blockers. Retryable internal
   writes retain their controls even when the design has no external business mutations. Review
   reasons quote the control contracts and cover every applicable producer or path.
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
post-fit node-title floor with each private candidate. The renderer chooses horizontal or ranked vertical placement from the
resulting fit scale. A rank-ordered compact layout covers the full 60-node backend safety ceiling
when either ordinary plan would be unreadable. Bottom-lane height is derived from its densest
column. The browser still measures the real SVG. The server rejects overlapping node cards or
responsibility-zone boundaries, clipped nodes or edges, missing required labels, and unreadable
node titles. The non-browser staging client consumes the same criteria from the candidate event,
and its compact fallback covers the same 60-node ceiling. The browser and staging clients reject a
candidate that omits or changes the fixed criteria. The capacity correction passes offline tests and a local Chromium replay of
paid diagnostic `31825436257`; that paid workflow did not emit protected publication success.

FastAPI becomes available after database initialisation, then loads the FAISS artifacts and index in
a background thread. `GET /api/prepare` reports the current server-owned milestone and completed/total
units; the frontend renders that exact progress and never advances it with an elapsed-time animation.

Every production frontend turn includes a UUID `client_request_id`. Completed user/assistant
pairs are unique on that key at the database boundary, and a network retry replays the stored
assistant response. The temporary SSE compatibility endpoint still tolerates legacy callers that
omit the key; the WebSocket product path always supplies it.

Thread admission, active streams, chat requests, OTP/internal login attempts, and public analytics
capture use shared transactional storage. Rate-limit identifiers are HMAC-derived before
persistence, so Cloud Run scale-out neither resets the limits nor stores raw emails/IPs in the
limiter table.

The staged path gives each active role one explicit owner. Kimi K3 low authors bounded component
and connection wires. Sonnet 5 medium gates each candidate once. The server owns graph mutation,
validation, maturity, and all state transitions. Opus 5 low writes the explanation stream and has a
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

The September 12 simplification keeps two authoring stages because a complete graph can be a large
output. Component review catches responsibility defects while that stage can repair them; connection
review owns interactions after components freeze. The remaining limitation is explicit: connection
correction cannot redesign components. A rejected graph stays unpublished. This bounded pipeline
still makes five calls without correction; prompt simplification does not establish lower live latency.

Semantic corrections to a new design use the existing delta assembler. The server retains
every candidate record in order and permits updates to the review's indexed records plus
bounded additions. Cited records can be witnesses to a missing path without needing changes.
Each semantic correction slot accepts `null` to retain the original record verbatim, or a
complete authorized update. Explicit user edits keep their non-null field contracts.
An indexless finding permits updates across the candidate. Capabilities
describe the complete corrected design; other component metadata stays fixed unless the
finding concerns it or is global. Corrections cannot omit
records or remove a required connection. Structural failures still use the original repair
path, and explicit user edits retain their existing removal permissions. A semantic repair
that needs deletion can still fail review; it does not gain removal authority implicitly.
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
