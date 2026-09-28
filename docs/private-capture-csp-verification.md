# Private diagram capture CSP verification

Verified locally on 2026-09-28. This records the capture fix and one fresh generation for `AI blogs/content generation pipeline`. Production rollout has not been verified by this evidence.

## Failure and fix

`HiddenGraphEvaluator.rasteriseSvg` loaded serialized SVG through a `blob:` URL. Production CSP permits `img-src 'self' data: https:` and blocks `blob:` images. The component candidate could be generated successfully, then fail private screenshot capture before its semantic review. The previous user response concealed this distinction behind a generic diagram failure.

The renderer now loads the SVG through an encoded `data:image/svg+xml` URL. CSP remains unchanged. Capture failure, layout rejection and preview timeout retain distinct server failure codes and user responses. The staged workflow preserves `render_failure_code` in admission diagnostics.

## Frozen runtime

The live evidence is in local `work/production-content-incident/live/`:

| Identity | Value |
| --- | --- |
| Base commit | `e07070f5b5266f538c86678384d7785291cf11cb` |
| Frozen source diff SHA-256 | `c86c6450ec165e5ec3f45e15e590e650b243e550d5dcd0dc3848da46dac31a70` |
| Renderer source SHA-256 | `31c45b994b22863d0ea34e48839fd2410da6d5e88b4d6dcafa20e98a4a714f3c` |
| Run | `local-private-capture-csp-7473c1dd-da87-45b1-a7e7-745b97bad929` |
| Source freeze | `2026-09-28T17:50:17.182628+00:00` |
| Backend / frontend ports | `8017` / `5199` |

`identity.json` records all source and corpus hashes; `frontend-build-manifest.json` records emitted asset hashes. The isolated frontend build ran through Vite preview with production security headers. `readiness.json` confirms a healthy backend, loaded FAISS and zero pre-request threads, messages, model telemetry or attempt-ledger entries. This used a fresh local SQLite store and development authentication, without production account data.

## Fresh generation and persistence

One browser-submitted request produced an accepted graph with **11 nodes and 41 edges**. The component preview and complete graph both captured at the private 1440x960 viewport with zero overlaps, clipped nodes or clipped edges. The complete graph displayed all seven required overview edge labels.

`accepted_snapshot.json`, `private_evaluations.jsonl` and `review_capture*.jsonl` establish:

- Five successful provider calls, each with one accepted provider attempt and `used_fallback=0`: Kimi K3 components and connections, Sonnet 5 component and connection reviews, and Opus 5 answer synthesis.
- Both semantic reviews approved attempt 1 with no findings or diagnostics. No component or connection repair was needed.
- No cached generation was reused. The store started empty, both candidates were newly generated, and recorded cache creation/read tokens were zero.
- Complete usage for all five calls: 39,924 input tokens, 11,386 output tokens and estimated cost **$0.264993** at the recorded `2026-08-07` price release. The attempt cap was 10; five attempts were consumed.

The answer and fitted graph were reviewed in the browser. After reopening the thread, `persistence-comparison.json` confirms exact decoded graph, contract, messages and telemetry equality. Provider attempts remained five before and after reload. The paid backend was then stopped.

## Production-header capture regression

`csp-fixture/provenance.json` and `capture-audit.json` separate saved transport fixtures from fresh model generation. This fixture used zero provider calls and the exact production CSP. The old renderer from `ec7309d98a28620551129c6f9dfa334bf2fc242e` failed both a 13-node component preview and a 7-node, 11-edge complete graph. Both returned the failed-capture placeholder and server classification `browser_capture_failed`.

The fixed renderer captured both fixtures as 1440x960 JPEGs without capture errors; the current server channel accepted their uploads. Four fixed captures passed. These exercise capture and transport validation, with saved graph inputs; they provide no new semantic-generation evidence. Visible mobile viewport behavior is not established by this record.

## Failure telemetry and offline checks

`graph_critic._record_render_failure` writes a correlated `graph_render_failure` analytics event and an independent warning. It retains explicit stage, stable failure code, named failed checks and bounded finite numeric render metrics. It excludes raw browser error strings, SVG, screenshot payloads and arbitrary client properties. The upload channel reduces failed capture reports to `browser_capture_failed`. Queue-to-worker-to-SQLite persistence was checked independently: the nested metrics and correlation survived, while raw error/SVG/image sentinels were absent from storage and warning output. Analytics queue or database failure can still lose the durable event; the independent warning remains.

`canonical-backend-static.log` records successful canonical `api-integration` (239 tests), `agent-rag-llm` (2,289 tests) and `static-security` groups. Ruff and Bandit completed; three dependency audits found no known vulnerabilities. `frontend-csp-ci.log` records 466 passing frontend tests and zero audited vulnerabilities. Existing tool deprecation and annotation warnings remain in those logs.

This evidence verifies the CSP defect, a fresh complete generation and reload persistence on the frozen local runtime. It does not establish universal generation success or a deployed production result.
