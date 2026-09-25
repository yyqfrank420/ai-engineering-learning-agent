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

Laptop-first browser experience with comfortable full diagram interaction and editing.
Learners ask for a system, inspect its graph, follow its execution sequence, select
components for explanations, and request changes or local expansion through chat.
They also arrange blocks, move zones, and reshape zone borders.

Generation can take one to two minutes. Learners need understandable activity feedback
throughout that wait, followed by a diagram and an explanation that agree.

Phone and tablet interaction requirements remain undecided. Laptop-first does not
authorize a read-only replacement for the core diagram workflow.

## Capabilities and constraints

- Keep D3 as the diagram renderer for direct control over appearance and interaction.
  Improve the existing renderer without migrating to another editor framework.
- Diagrams are enabled by default. Ambiguous requests should offer a clear choice
  about diagram generation near the conversation input.
- Explanations should use learner-facing terms and concise prose. Implementation
  notes, repetitive caveats, and internal workflow jargon should not dominate answers.
- Reduce initial information density without removing architectural depth. Keep
  component responsibilities and connection details available through interaction.
- Show truthful generation activity. Keep the generation experience present until
  the graph is ready, then release the completed explanation.
- Editing should preserve the surrounding system and existing learner work.
- Direct editing should let learners revise component names, types, subtitles, and
  descriptions, plus each directed connection's label and metadata. Selection reveals
  the relevant fields; double-clicking a node or pressing F2 focuses its name.
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
4. Make the full learning and editing workflow comfortable on a laptop.
5. Preserve learner context and show understandable, truthful progress.

## Open decisions

- Product name and the book's prominence in the product identity.
- Phone and tablet editing expectations.
- Any product-specific accessibility standard beyond the existing engineering requirements.
