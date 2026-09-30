# Conversational activity verification

Date: September 30, 2026. Branch: `codex/conversational-progress`.
Base: `a083406f6c8e8ea5812ac8c90d698f80751c72e9`.

This ordinary UI extension replaces the default-open provider reasoning transcript
with public work activity. The user requested elapsed overall work time, short
conversational updates, quieter actual search rows, and collapsed activity retained
with the assistant answer after completion and reload. Startup wording in PR68 is
outside this change.

## Implemented boundaries

`backend/agent/activity.py` owns one recorder and workflow-to-public-text mapping.
It consumes known workflow phases and statuses. Purpose-focused prose explains
what the next step contributes to the user's request. Book, web, render and review
operations produce quiet tool rows. Generic update completions are omitted;
meaningful architect and challenger completion details remain bounded public
findings. Identifier-shaped text is excluded. Arbitrary provider reasoning and
arbitrary event details are not public update sources.

Component and connection completion use an explicit draft summary from
`staged_graph_workflow._stage_progress`, derived from that same attempt's actual
graph. The summary contains a title limited to 80 characters, component and
connection counts, and at most two component labels limited to 48 characters each.
Public facts are sanitized and invalid summaries are dropped, including boolean,
negative or oversized counts, impossible zero-component/nonzero-connection
combinations, malformed labels and unexpected fields. There is no preview cache:
earlier previews cannot supply counts for a later attempt. Draft wording remains
preliminary and states that checks precede presentation.

SSE and WebSocket record activity at their transport send boundaries. Each supplies
elapsed time from its existing monotonic request clock and serializes recording
and delivery. Existing `workflow_progress` events remain available. The new
`activity_step` event carries public text, phase, status, kind, sequence, and elapsed
time. No summarizer model or additional provider request is introduced.

The shared stream loops consume provider events but accumulate and emit only
answer text and supported public events. The obsolete provider-thinking forwarder
is removed. Transports reject incoming `thinking_delta` and agent-supplied
`activity_step` events at the recording boundary. The frontend ignores legacy
thinking events. Private reasoning is not answer content or retained activity.

`MessageActivity` validates a completed duration and ordered steps. Bounds are 48
steps, 32,768 serialized UTF-8 bytes, 400 characters per step, and 86,400,000 ms.
Sequences are unique and increasing; elapsed offsets are nondecreasing and cannot
exceed completed duration. Extra fields and incorrect types are rejected.
Consecutive identical public steps are dropped; retained sequence identities do
not restart when older steps are removed.

`useAgentStream` associates live activity with the current client request identity
and ignores stale or node-selection activity. On terminal completion it attaches
canonical metadata to the first assistant message for that request and clears live
state. Thread mapping restores saved activity. `MessageList` places activity before
the owning answer, or at the conversation end before an answer exists.
`ThinkingIndicator` now renders native disclosure activity: live "Working for"
and completed "Worked for" labels, update paragraphs, and muted tool rows.
Completed activity is collapsed. The client timer measures overall work, while the
saved duration is authoritative after completion. Timer ticks are outside the
polite announcement text. Adjacent same-phase tool active/complete pairs render
once as the completed row. This projection does not remove or rewrite canonical
steps, duration or sequence metadata. Activity stays outside the answer-content
node.

Activity records are feedback only. They do not enter model prompts, authorize
graph changes, change publication rules, or alter provider budgets and message
limits. Stop, steering, and retry retain their existing orchestration ownership.

## Canonical data ownership

| Concern | Owner and behavior |
| --- | --- |
| Authoritative source | Nullable `chat_messages.activity` on the canonical assistant row. Production uses PostgreSQL JSONB; local SQLite uses JSON text. |
| Writer | Transport-owned recorder snapshot passed to `thread_store.persist_turn`, in the existing atomic turn transaction. Chat request bodies cannot supply activity. |
| Readers | Ownership-scoped completed-turn replay, thread-message retrieval, and the owning conversation UI. |
| Transformation | Shared backend recorder maps known events to public steps; the strict storage model validates metadata. Frontend parsing validates the wire shape before rendering. |
| Idempotence | Existing client request identity and atomic turn persistence choose one canonical user/assistant pair. A duplicate write preserves the original answer and activity. Terminal replay and reconciliation read that saved winner. |
| Reconciliation | Completed-turn metadata replaces transient activity. Replaying a completed request does not start a new saved duration. Reload restores metadata through `get_messages`. |
| Retention | Activity follows the canonical message's existing retention and ownership-scoped deletion. There is no separate writable history, retention schedule, or backfill. |

Legacy NULL metadata stays absent. Invalid optional stored metadata is omitted
with a warning containing only the exception type; canonical messages remain
available. Activity is separate from `retry_request` and telemetry.

## Migration0010 rollout and rollback

`backend/db/migrations/versions/20260930_0010_message_activity.py` follows0009.
It adds a nullable JSONB column without a default or backfill and an assistant-only
object CHECK named `ck_chat_messages_activity`. The CHECK is `NOT VALID` to avoid
a historical row scan while constraining new writes and updates. DDL uses local
5-second lock and 60-second statement timeouts. SQLite initialization/upgrades,
the PostgreSQL schema guard, and `docs/supabase/schema.sql` include the column.

Deploy the additive migration before code that selects or writes activity. Verify
the column type, nullability, absent default, and constraint before application
rollout. Older writers can omit the column and retain NULL metadata. No production
migration was executed by this verification task.

Rollback application code while retaining the additive column. The Alembic
downgrade drops the column and loses activity; it is not data-restoring rollback.
Back up the database before a deliberate downgrade if retained activity must be
recoverable. Production table size, lock latency, and deployed-version inventory
still require deployment review.

## Current tone cleanup verification

The tone cleanup extends prior revision
`49c69e0b13497de650b7fd759ef3a6bce3064c77`. It changes public activity wording,
same-attempt draft facts and the adjacent tool-row presentation projection. No
new model call, schema or prompt change was introduced. CI classifications,
runtime exemptions, `PRODUCT.md` and design files are unchanged.

The checked source SHA256 values are:

- `backend/agent/activity.py`: `3ee638cb26b193959408c32dc47a95ee5fc76e8366b83083b4fd5d08462a97ff`.
- `backend/agent/staged_graph_workflow.py`: `6ff03571bfd2cb8242d0f17f9c412fb178245d6abf7f74d84aef4f0a3a000a28`.

Targeted checks passed 408 backend tests and 22 frontend tests, owned-file ESLint,
TypeScript checking, Ruff and `git diff --check`. The detector ran once and returned
an empty violation list.

The current full canonical `./scripts/ci offline` run passed all 11 groups and 26
commands, exit 0, on 2026-09-30 from 14:30:33 to 14:34:55 UTC. The seven source/test
hashes remained unchanged. Its tracked diff SHA256 was
`a3a0c96d30c1b311deb91241f6d0910063d15a7d23eb31d1fab7a608d995f168` at base
HEAD `49c69e0b13497de650b7fd759ef3a6bce3064c77`. Evidence is retained in the parent
workspace's `work/tone-verification/canonical-result.json` and `canonical.log`.

Backend coverage passed 3,537 tests with 2 optional PostgreSQL skips and 92%
coverage. Frontend passed 592 tests across 44 files. API tests passed 299, agent
checks 2,603, storage 147, evaluation 477, ingestion 7, infrastructure 19 and
pipeline policy 388. All applicable lint, security, dependency audits, builds,
artifact, Terraform and migration checks passed; audits found zero vulnerabilities.
Existing dependency deprecations, Node localStorage notices, Bandit suppression
warnings and optional PostgreSQL, ingestion and Bash skips remain. This is not a
warning-free run.

The current mocked browser batch uses steps emitted by the actual recorder,
fixture SHA256
`cd3806cfd87e63b898340f8cd342a7dedff97a55f777f5d69500613e0c386224`.
Its `work/tone-verification/report.json` identifies the exact recorder source
above and matching frontend before/after hashes. Desktop 1440x1000 and mobile
390x844 passed normal and 200% wrapping checks, timer advancement without repeated
polite announcements, three adjacent tool-pair projections, retry/degraded/failure
states, collapsed completion, reload and native keyboard disclosure. Browser
errors, external requests and provider calls were zero. HTTP and WebSocket
responses were mocked; this is current presentation evidence, not a fresh
provider run.

The second and final capture round corrected only the mobile scroll position so
the actual eight-component draft paragraph, both component labels and its
pre-check sentence were visible alongside the quiet check row and connection
update. The completed 17-second history remained collapsed. The six authoritative
capture paths were replaced; `report.round1.json` retains the first-round report.
`report.json` records `capture_round: 2` and matching source/CSS hashes before and
after. No product code or styling changed for the correction.

A fresh default agent used the supplied finish-reviewer fallback and inspected all
six authoritative current captures, `PRODUCT.md`, source and report evidence. It
returned `ship` with no material fixes. No additional detector, capture round or
provider call was requested. Only this documentation changed after the canonical
run; source/test identities remain the checked values.

## Prior implementation evidence retained in revision 49c69

The following evidence predates the tone cleanup. The real-provider captures and
PostgreSQL results verify the earlier implementation; they are not relabeled as
current tone-copy evidence. The provider captures describe the tree before the
subsequent unused-state cleanup, as recorded below.

The preceding canonical offline run passed all 26 selected checks. Its source fingerprint,
start/end timestamps, commands, and output are retained in
`work/conversational-progress/offline.log` in the parent workspace. The backend
coverage suite passed 3,489 tests with 2 skips; coverage enforcement passed.
Frontend coverage passed 590 tests in 44 files. Existing dependency deprecation
warnings remain in the log; this record does not claim a warning-free run.

Actual disposable PostgreSQL verification used official PostgreSQL17.6 on a
localhost-only owned container. The harness applied the real Alembic chain
through0009, seeded legacy rows, and applied actual0010. It passed schema and
NULL-compatibility assertions, old-writer insertion, invalid role/type rejection,
the schema guard, native JSONB round-trip, four concurrent identical writes,
same-request winner preservation, fresh-process reload, ownership rejection, and
corrupt-optional-metadata handling. The owned container was removed. Evidence is
in the parent workspace's `work/conversational-progress/postgres/results.md`,
`results.log`, and `verify_activity.py`.

These PostgreSQL checks used backend ownership filters and the backend database
role. They did not exercise managed Supabase Auth, authenticated-role RLS
execution, production lock timing, or rolling deployed versions.

One actual local Moonshot/Anthropic browser generation passed. It used the isolated
synthetic fixture, whose first 52 messages exactly matched the authored history;
the remaining 8 came from scripted test prompts and model replies. Two initial
approval-review rejections were resolved with that provenance evidence, without
another human permission request. No production or personal chat was used.

The fresh extension saved 19 activity steps, including four actual tool rows.
No public `thinking_delta` events appeared. Terminal `done.activity` exactly
matched the canonical assistant row returned by GET. All 62 messages, graph
content and layout survived reload; the unsent composer draft survived completion.
Desktop and mobile restored the same collapsed "Worked for 1m 26s" history
(duration 86,636 ms), with keyboard open/close checks. Browser errors were absent.
The run used five existing-pipeline provider attempts: the retained quota moved
from 21/34 to 26/34, without reset or automatic repetition. Evidence is in
`work/conversational-progress/live` in the parent workspace.

A separate explicitly mocked local-transport batch checked desktop 1440x1000
and mobile 390x844 live timer advancement, public paragraphs/tool rows, completion,
keyboard disclosure, and canonical mocked GET/reload. All checks passed, with no
browser errors, external HTTP, or overflow. These captures are labeled MOCK and
are distinct from the real-provider evidence. The actual mobile collapsed capture
needed a read-only scroll correction to bring its summary into view; product code
was unchanged. Evidence is in `work/conversational-progress/ui`.

A fresh independent finish review returned `ship` for the activity surface, with
no material fixes. It inspected the pinned reference, all mocked states and the
real completed/reload captures, including the corrected mobile collapsed view.
A fresh fallback reviewer used the shipped degraded instructions because the
specific Impeccable reviewer role is not exposed by this harness.
After the live capture, the parent removed newly unused frontend workflow-progress
state and stale test fields. Legacy wire events remain accepted. This cleanup
changed no rendered component, styles, model input, or provider behavior. The
canonical frontend group was rerun and passed all 590 tests, lint, coverage,
build and audit; the affected hook/App suite passed 116 tests. Its before/after
fingerprints are recorded in `frontend-unused-state-cleanup.json` beside the log.
The real-provider captures describe the preceding tree; the later cleanup was
verified offline without another provider request.

No cloud deployment or production migration was performed.

## Official research basis

- [OpenAI Codex model guidance](https://developers.openai.com/api/docs/guides/latest-model?model=gpt-5.3-codex) documents short conversational progress/intent preambles and separate commentary/final-answer phases.
- [Codex App Server items](https://learn.chatgpt.com/docs/app-server#items) distinguish assistant messages, reasoning, and tool activity; [item deltas](https://learn.chatgpt.com/docs/app-server#item-deltas) distinguish readable reasoning summaries from raw reasoning when supported.
- [OpenAI reasoning summaries](https://developers.openai.com/api/docs/guides/reasoning#reasoning-summaries) are opt-in summaries; the Responses API does not expose raw reasoning tokens. This is not a claim that every OpenAI surface hides raw reasoning.
- [Cursor SDK interaction updates](https://cursor.com/docs/sdk/typescript#interaction-updates) document separate text, thinking, tool lifecycle, and duration signals.
- [Cursor compact chat mode](https://cursor.com/changelog/1-4#compact-chat-mode) documents reduced visual emphasis for tool icons and collapsed diffs in that release.
- [Current Cursor CLI output formats](https://cursor.com/docs/cli/reference/output-format) distinguish assistant and tool events and suppress thinking in print mode.

The elapsed label and subdued tool row are this product's implementation and the
user's reference direction. These sources do not establish another product's
exact timer semantics, hidden summarizer architecture, or internal UI pipeline.

## Incumbent system comparison

The degraded Impeccable Documenter instructions were used because the shipped
documenter role was unavailable in this harness. This pass checked `PRODUCT.md`,
`frontend/src/index.css`, `MessageList.css`, `ThinkingIndicator.css`, and their
rendering components. No existing `DESIGN.md` or design sidecar was found. This
ordinary extension does not authorize creating a new global visual identity;
product and system files were preserved.

Palette: existing dark base/panel/overlay surfaces remain; activity uses subdued
text with the incumbent violet focus accent.
Type: Inter and existing fallbacks remain; activity uses 0.875rem body text and
0.8125rem summary/tool text.
Layout: activity stays in the chat flow, has a 72ch maximum width, and wraps long
text; diagram editing and viewport ownership remain with existing components.
Depth and shapes: the activity adds no boxed transcript or card surface; native
disclosure uses a subtle top divider and a visible keyboard-focus outline.
Behavior: live updates are readable paragraphs; saved history is collapsed and
retains its canonical duration and order.

Drift not canonized or repaired: activity CSS contains local literal text colors
alongside the incumbent global CSS variables. Existing source comments and
component naming still use "thinking" terminology. These are reported facts,
not new design rules; repair is outside this documentation boundary. Source
comparison is supplemented by the desktop and mobile captures above.
