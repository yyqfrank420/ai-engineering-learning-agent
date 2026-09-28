# Graph history and additive continuation

Base: `99c2b6d2c7bbf418a12d146dac324ef33eb2c9d0`, branch
`codex/graph-history-continuity`. The local verification identity also records every
source hash and the uncommitted diff, since validation preceded the release commit.

## Scope

The compact design has Undo/Redo, a version picker, and answer links. Picker selection
previews a saved graph; Restore changes the active graph. Chat scrolling does not select
versions. Undo/Redo retrace the session path, including sibling branches. Other branches
remain in the picker. Request labels distinguish versions.

Uncertain continuation requests offer extension or a new chat. Additive generation keeps
saved records and their metadata, with bounded additions. New diagrams cannot replace an
existing diagram through transport admission, agent entry, or late model routing.

## Offline evidence

- Backend: 3,163 tests passed, two skipped; coverage exceeded the 90% requirement.
- Frontend before the final transition layout lock: 527 tests passed; lint, TypeScript
  and production build passed. The lock passed 71 focused tests, lint and TypeScript, including pending-save flush and
  layout emission after unlocking.
- Pipeline policy: 368 passed, five skipped; manifest validation passed.
- Scoped and repository Ruff checks passed. Bandit found no security issue; its existing
  `ci_runner.py` suppression warnings are unrelated to this change.
- Impeccable found one unchanged Markdown blockquote border. It is a semantic quote
  marker, outside the new history controls. No new detector finding.

The isolated browser fixture used real history routes and SQLite with model calls disabled.
It covered read-only previews, Undo/Redo across sibling branches, answer links, manual edits,
reloads, saved positions, desktop/mobile controls, wrong-owner 404 and stale-version 409.
No generation requests, unexpected network requests or page errors occurred. A separate
provider-disabled test submitted an ambiguous new subject, chose Start a new chat, and verified
that exactly one request targeted the newly created thread with `graph_action=new`. The original
thread, messages and graph remained unchanged; the provider ledger stayed at zero. Browser testing
caught and corrected a collapsed canvas caused by the added toolbar wrapper.

## Database verification and rollout

Two independent reviews checked storage invariants. A disposable local Postgres database
ran the migration against public and staging schemas. Checks covered owner isolation, RLS,
revoked client grants, same-thread constraints, versioned restore retries, retained branches,
transaction rollback, duplicate-request concurrency, layout saves, and deletion cascades.
An existing-data upgrade retained graphs and messages without historical backfill.

Production Auth and production table lock duration were not simulated. Migration DDL has
five-second lock and sixty-second statement limits. Review the production table sizes before
applying. The new code reconciles older writers' current graphs before history operations;
intermediate writes from old code cannot be reconstructed after they have been overwritten.
Drain old writers if complete history is required across the rollout itself.

Keep the expanded schema when rolling application code back. Downgrade deletes retained
revisions and message associations; it needs a separate backup/restoration plan.

## Fresh generation evidence

Run `local-graph-history-7a51ef2f-f5f1-4ce8-a3d7-65648d07a147` used a fresh local database,
real retrieval, production model settings, and source diff `be23abcc` with a full source-hash
manifest. Account: `dev@local`; frontend 5204, backend 8021. The two requests were:

1. Design an AI tutoring application for a university course. Show how students ask
   questions, retrieve course materials, and receive cited answers.
2. Add a teacher review and feedback layer on top of this tutoring system, including a
   review queue and a way to use approved feedback to improve course materials.

The first result had 8 nodes, 14 directed edges and 5 groups. The student client was moved
with the keyboard from (137,106) to (138,106) and its layout saved before extension. The
second request presented the inline clarification choices; Extend was selected. It produced
12 nodes, 30 directed edges and 8 groups. All original node, edge and group records matched
the baseline exactly; every saved node position remained unchanged.

Both turns passed without a repair. All four quality gate reviews approved their applicable
rules with zero findings. All four private render reports had zero clipped nodes/edges and
zero overlaps. The final extension report had minimum text size 13.51px at 1440x960 and all
three required overview edge labels visible. Ten provider attempts succeeded, under the
20-attempt ceiling. Recorded-usage cost estimate was $0.362248 for both turns combined.
No additional judge was called.

In the live UI, Undo returned to 8 nodes; Redo returned to 12. The moved client retained its
exact coordinates. Reload and reopening the chat retained the extension. The first answer's
View diagram link opened the 8-node read-only preview; Return to current restored the 12-node
view. Browser warning/error log was empty. History interactions did not add provider calls.

Evidence lives in `work/graph-history-verification/live/` outside the repository, including
source identity, committed snapshots, provider-attempt ledger, and gate/render summaries.
The first service launch was stopped before submission for the final transition layout lock;
its archived database contained zero threads, messages, telemetry rows or attempt events.
No cached result or reference graph was used as generation evidence.
