# Freeform replies with pending diagram choices

Date: 2026-10-04. Runtime fix: `194f2fb`. Integration base: `d0fb135`.

After an ambiguous follow-up offers diagram choices, Send or Enter submits the same draft as `answer`. Dismiss hides the choices and retains that answer fallback. The current conversation and saved diagram remain the context. Explicit Extend and Start a new chat actions remain available. Draft edits and thread switches clear the pending choice. Failed sends retain the draft; duplicate sends and stale intent responses retain their guards.

## Offline evidence

- Related frontend tests: 69 passed, including current-thread diagram context and highlighted-text request assembly before selection clearing.
- Changed `ChatInput.tsx` coverage: 98.23% lines, 96.85% statements, 96.55% functions, 93.2% branches. Existing coverage thresholds passed. Coverage was scoped to the changed production file.
- ESLint, TypeScript, production build, and `git diff --check`: passed.
- Backend continuity and answer-only routing tests: 21 passed. They check exact canonical graph context through SSE and WebSocket, stale/missing version rejection, persistence publication, and suppression of prior edit intent.
- CI policy tests: 480 passed, 5 skipped. Canonical manifest validation passed.
- Browser composer harness: second Send, Dismiss then Enter, rejected-send draft preservation, and retry without repeated classification passed. The harness used the real composer with deterministic classification and send acceptance; it did not run a model.

The frontend run used:

```sh
npm run lint
npm exec --no -- vitest related --run --coverage \
  --coverage.include=src/components/Chat/ChatInput.tsx \
  src/components/Chat/ChatInput.tsx \
  src/components/Chat/ChatInput.test.tsx src/App.test.tsx
npm run build
```

Backend tests used `backend/tests/test_graph_continuity_transports.py` and the two answer-only routing tests in `backend/tests/test_service_expansion_routing.py`. Backend coverage instrumentation collected no data because the source arguments used filenames; no backend coverage percentage is claimed. The backend checks used mocked providers and the frontend app coordination tests mocked transport hooks. These checks establish their stated boundaries, without live generation claims.

Node 26 emitted an existing localStorage experimental warning during frontend tests. The backend run emitted an existing Starlette/AnyIO deprecation warning. No product warnings were suppressed.

## Evaluation exception

The user explicitly requested offline backend CI/CD checks and context-preservation regressions, and waived paid live evaluations for this change. Local model credentials and a configured backend were unavailable. The exception covers fresh local generation and the paid GitHub live-evaluation gate. Offline GitHub CI must pass before merge. No paid model calls or changes to branch-protection settings are authorized by this record.
