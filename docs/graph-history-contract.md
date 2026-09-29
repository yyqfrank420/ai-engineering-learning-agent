# Diagram continuity and history

A follow-up must preserve the learner's work. Extending a diagram and starting a separate
one are distinct operations. An unresolved intent check asks the user which operation they
want. It never turns the word "ask" into automatic permission to replace a diagram.

## Submission

The composer retains the draft during intent checks and failed thread creation. A clear
addition can extend the current diagram; uncertain intent offers Extend this diagram and
Start a new chat. The separate option creates and opens a new conversation before sending
its request. Requests for explanations keep the current diagram. Initial broad learning
requests still produce a custom diagram without a choice screen.

Typed graph actions travel through both transports. The server checks the current graph
under the shared thread lease before provider calls. Extension requires the expected
current graph version. A new diagram cannot replace an existing diagram in the same chat.
Stale clients get a visible conflict. Agent entry also enforces this invariant for steering
and internal callers.

Additive extension has server-owned mutation permissions. Existing components, directed
connections and groups retain their identities and content. The builder may add records
within remaining safety limits and connect the added layer to existing components. Exact
field edits retain their separate existing authority. Structural checks, private rendering
and graph review still apply. Unresolved model questions preserve the accepted graph.

## History and layouts

The database owns graph revisions. Each checkpoint stores graph content and its matching
server-only semantic contract. Parent links retain the branch created by an edit after
Undo. A thread points to its active revision; its current graph is the materialized working
copy. Assistant messages link to the revision produced by their turn. No graph contract is
returned through a public history response.

Undo restores the active revision's parent. During the session, Redo follows the path just
undone. Explicit restore, a content change, or a thread switch clears that path; without a
session path, Redo selects the newest child. Older branches
remain in the compact numbered version picker. View diagram links beside answers
are the main entry to earlier diagrams. The viewed answer link has a selected state.
Picker entries and earlier-answer links open a read-only preview. Selecting the
current answer returns to the working graph. Restore makes that version current; Return to current leaves the working graph
unchanged. Scrolling messages never changes the canvas.

Each revision retains its saved node positions, zone padding and viewport. Layout changes
update that revision's layout and the working copy in one transaction. Content revisions
are appended on accepted generation and manual content edits, not on every pointer move.
Before generation or a history transition, the canvas flushes pending layout writes. A
failed flush leaves the user in place with an error. Extension also preserves positions
saved while the generation was running. Existing nodes stay fixed; new nodes avoid their
occupied space. Historical previews permit pan and zoom but cannot save layout or trigger
AI actions against the current graph.

Restoring requires the expected current graph version and shares the thread generation
lease. A successful activation receives a fresh graph version token, so a delayed layout
write from an earlier activation cannot overwrite it. Restoring the already-active target
is an idempotent no-op. Failed, stale or unauthorized restores never replace the graph.

## Existing data and rollout

Earlier releases saved only the latest graph body. History starts with the current saved
graph when the new code first reads or changes it. Previously overwritten diagrams cannot
be reconstructed from the conversation prose. Any recovery claim needs a saved artifact.

The migration adds revision storage and nullable references. Existing conversations remain
readable. New code must reconcile the current graph against its checkpoint when an older
writer changes the graph during rollout. The migration does not rewrite historical graph
bodies. Existing conversation-retention and deletion rules also remove their revisions.

Keep the expanded schema when rolling application code back. Dropping the revision table
would destroy retained history; a destructive downgrade requires a separate backup and
restoration plan. Independent migration review and real Postgres checks are required before
release. Generation changes require fresh local generation evidence before opening a PR.
