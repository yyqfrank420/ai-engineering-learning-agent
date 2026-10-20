# Diagram header description removal

Baseline: origin/main, `04a82b48db7ad6374b4039b0c7105b2a82b4bbfc`.
Exact reviewed source blob pairs are in `ci/quality.json`.

Deleted the entire "Overview / Core workflow. Supporting detail is simplified."
header row, its two CSS selectors and its unused accepted-graph display prop.
The App change deletes only the prop passed to this row. Tests remove the obsolete
row case and display-flag assertions while keeping preview, persistence and readiness
checks intact. Title, title subtitle and component counts retain their rendering.

D3Graph, HiddenGraphEvaluator, graph generation, private rendering, transport,
selection, callbacks and persistence have no source changes. No provider calls are
required for this presentation deletion.

Canonical frontend checks passed ESLint, 58 related tests, TypeScript and the
production build. Rollback uses the normal frontend source/deployment rollback.
No database or backend changes are needed.

The isolated local preview mounted actual GraphCanvas with an overview graph,
application CSS, no authentication and no thread. Desktop and mobile headers
contained no overview description and met the canvas without an empty gap.
Title remained visible; no horizontal overflow, console errors or API requests
were observed. The screenshot was inspected at both viewport sizes.
CI policy tests passed 504 tests with five existing local capability skips.
The scoped layout detector found no issues.
