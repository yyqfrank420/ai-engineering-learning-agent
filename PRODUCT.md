# Product

<!-- impeccable:product-schema 1 -->

## Platform

web

## Users

People who can code and are new to AI engineering and system architecture.
They learn through questions, practical system examples, and interactive diagrams.

## Product purpose

Help learners understand and develop AI system architectures. The experience should
explain component responsibilities, connections, and design choices at a useful depth.
Understanding the system is the outcome; generating a diagram alone is insufficient.

## Scope and positioning

The subject is broad AI architecture. Chip Huyen's AI Engineering book is one source,
not the boundary of the product's knowledge or the set of architectures it may generate.

RAG is optional supplementary verification intended to reduce hallucinations.
Missing retrieved passages must not, by itself, prevent architecture generation or
restrict it to systems described in the retrieved material. This is the confirmed
product requirement; it does not assert that the current implementation satisfies it.
Source attribution must remain truthful. Generated design suggestions must not be
represented as statements from a source that does not support them.

## Operating context

Responsive browser experience with full diagram interaction and editing on desktop,
tablet, and phone.
Learners ask for a system, inspect its graph, follow its execution sequence, select
components for explanations, and request changes or local expansion through chat.
They also arrange blocks, move zones, and reshape zone borders.

Generation can take one to two minutes. Learners need understandable activity feedback
throughout that wait, followed by a diagram and an explanation that agree.

On narrow workspaces, Chat and Diagram views each use the available workspace.
Switching views preserves conversation drafts, diagram state, and editing controls.
History opens in a dismissible drawer on phones and tablets. Wider workspaces retain
resizable side-by-side panes. Touch controls and input fields remain usable across
portrait, landscape, and software-keyboard layouts.

## Capabilities and constraints

- Keep D3 as the diagram renderer for direct control over appearance and interaction.
  Improve the existing renderer without migrating to another editor framework.
- Validate topic relevance and prompt injection before routing, retrieval, or diagram work.
  Redirect unrelated requests to AI engineering and AI system architecture.
  Explicit unrelated follow-ups stay out of scope even when a prior diagram exists.
- The composer always uses automatic depth with diagrams and research enabled.
  Broad learning requests include a diagram without a separate choice dialog.
  Follow-up explanations preserve the current diagram unless a change is requested.
- A successful diagram request produces a fresh custom diagram. Cached or reference
  diagrams do not substitute for generation. Provider and connection failures must
  appear as understandable feedback; they must never count as successful generation.
- Explanations should use learner-facing terms and concise prose. Implementation
  notes, repetitive caveats, and internal workflow jargon should not dominate answers.
- Reduce initial information density without removing architectural depth. Keep
  component responsibilities and connection details available through interaction.
- Show concise live activity from actual workflow events after input validation.
  Empty activity and rejected requests have no thinking panel. Keep one
  Stop control in the composer and use an upward arrow for sending. Stop during a
  rendered preview accepts that candidate and skips remaining AI reviews. If only
  components are ready, preserve them and finish their connections and answer.
  Structure, edit-authority, rendering, and persistence checks still apply. Reveal validated answer sections as soon as their matching diagram has painted, with a
  bounded terminal wait if the browser cannot acknowledge it.
- Editing should preserve the surrounding system and existing learner work.
- Extending a diagram retains saved components, connections, and positions. Uncertain
  follow-ups offer Extend this diagram or Start a new chat. Sending the draft again
  uses the current diagram as context and leaves it unchanged, including after
  dismissing the choices. Separate designs open a new conversation.
- Diagram history follows the conversation: each answer links to its diagram.
  Undo/Redo and a compact numbered version picker keep every saved revision accessible.
  Browsing history is read-only until Restore; scrolling the chat
  never switches versions. Each version retains its saved layout.
- Direct editing should let learners revise component names, types, subtitles, and
  descriptions, plus each directed connection's label and metadata. Clicking a node
  opens its details. A muted Edit button sits beside Close. Edit or F2 opens the
  form and focuses its name.
  Connections start as compact rows naming the other component and their direction.
  Expanding a row reveals every directed exchange and its technical metadata.
  Save and Cancel are explicit. Failed saves retain the draft and show the failure.
  Edits preserve graph identity, topology, and layout. A subsequent generation starts
  from the saved edit and receives a fresh review.
- Retrieval coverage is separate from architectural correctness. Optional RAG must
  not become a publication prerequisite. Correctness checks still have a role.

## Evidence on hand

- The user's confirmed product decisions in the September 25, 2026 init interview.
- Existing React, TypeScript, and D3 application in `frontend/`, with the graph
  canvas and conversation workflow available locally at `http://localhost:5176/`.
- Saved architecture regression examples in
  `frontend/src/components/GraphCanvas/__fixtures__/`.
- Implementation and verification descriptions in `docs/current-architecture.md`
  and `README.md`. Older book-companion positioning in those files does not override
  the broad architecture scope confirmed here.
- User-supplied screenshots and repeated feedback about readability, meaningful
  labels, progressive explanation, and editor interactions.
- Canva's [text editing](https://www.canva.com/help/add-and-edit-text/),
  [connector labeling](https://www.canva.com/help/connect-lines-to-elements/), and
  [selection controls](https://www.canva.com/help/glow-up/) document interaction
  patterns for focused editing. They are design references for this D3 editor, not
  evidence that graph annotations or persistence already exist here.

No learning-outcome benchmarks, customer testimonials, or licensing claims have been
provided for use as product claims.

## Product principles

1. Teach the system through concrete responsibilities and relationships.
2. Preserve depth while introducing detail at the learner's pace.
3. Use evidence to strengthen generation without bounding it to retrieval coverage.
4. Keep the learning and editing workflow usable across desktop, tablet, and phone.
5. Preserve learner context and show understandable, truthful progress.
6. Let controls explain themselves. Remove repeated subtitles and success narration;
   retain concise errors, pending feedback and the preview state.

## Open decisions

- Product name and the book's prominence in the product identity.
- Any product-specific accessibility standard beyond the existing engineering requirements.
