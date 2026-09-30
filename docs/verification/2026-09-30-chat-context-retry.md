# Chat context and generation retry verification

## Tested source

Base: `0080a2786f31713f19c6cd3022e7addd2b6d69ee`. Tested working-tree binary
diff SHA256: `aa0a14539b03f205ef7562f39520f5e7e4d776aa77191674e7668b7245598b35`.
The live source manifest records 431 file hashes, checked unchanged during verification.
The diff digest excludes the then-untracked regression file
`backend/tests/test_full_history_generation_context.py`; its separately recorded SHA256 is
`6161137949f6bbcbfac85beb32dea85d6f761339da0d8160369418ba5a2769b0`.
This verification record was added after those checks.

## Canonical offline checks

All 11 groups and 26 commands in `./scripts/ci offline` have passing evidence for their
final changed scope. The full run stopped at a newly reported transitive brace-expansion
audit vulnerability. Remaining groups ran through the same canonical runner. After the
compatible lockfile updates to 1.1.21 and 5.0.12 and a checkout-owned clean `npm ci`,
`./scripts/ci offline --group frontend` passed on the final source.

- API: 299 tests; agent/retrieval/model adapters: 2,533; storage: 122; evaluation: 477.
- Full backend: 3,442 passed, two opt-in PostgreSQL skips; coverage 92%, above the 90% gate.
- Frontend: 571 tests across 43 files; lint, TypeScript/production build and audit passed.
  Coverage: 93.36% statements, 85.86% branches, 94.89% functions and 95.94% lines.
- Ingestion: seven passed, ten optional-input/dependency/model skips. Migration/isolation:
  19 passed. Pipeline policy: 388 passed, five Bash-version skips.
- Artifact validation, Ruff, Bandit, all three Python dependency audits, migration compile,
  Terraform formatting/initialization/validation, Docker image build and manifest validation passed.
  Final dependency audits found no vulnerabilities.

Existing warnings concern Starlette/AnyIO and LangChain deprecations, Node localStorage
availability, and ineffective Bandit suppression comments. No gate was suppressed.
Unit tests verify exact preservation of 75 long Unicode messages, original latest-request
content, history-dependent prompt fingerprints and history trust boundaries. Legacy critic
and generation paths have prompt-level test evidence; the actual browser journey uses the
staged generation and review flow.

## Disposable PostgreSQL checks

An isolated local PostgreSQL 17.6 database ran the actual staging Alembic chain through 0009.
Legacy rows survived unchanged. The nullable JSONB column and assistant/object constraint
were checked through PostgreSQL catalog reads and rejected invalid inserts and updates.
Actual storage methods roundtripped Unicode retry metadata. Four concurrent identical writes
produced one canonical user/assistant pair. Unauthorized reads and writes respected the
ownership boundary. The two opt-in message-sequence migration tests passed without skips.
Only the disposable container was removed. No production database was used.

## Local real-provider browser journey

The local UI used isolated SQLite and FAISS data, account `dev@local`, and real
Moonshot/Kimi and Anthropic/Claude calls. The fixture held 52 messages and 15,254 characters;
an early constraint marker followed character 14,403, outside the recent six messages.
Fixture messages were not generated-answer evidence. Fresh generation, additive expansion
and successful retry retained explicit teacher approval before publication and durable audit
fields in the rendered graph and answer.

The four stages produced fresh version `57632796...`, expansion `a4e24857...`, an injected
capture failure, and retry version `a537873a...`. The browser render-report fault preserved
the expansion graph and durable canonical retry metadata. Reload retained the Retry generation
button. Clicking that actual button succeeded with new request `43da8e82...` and original
retry source `09dd3465...`. Final reload retained all 60 messages exactly, the canonical graph
and saved layout; viewport reflow was the only layout comparison exception. The unsent composer
draft was visually confirmed in the after-retry screenshot; this was not a programmatic check.
The capture fault does not simulate a provider outage.

The provider ledger recorded 21 attempts against the retained 34-attempt ceiling, including
five initial harness calls sent to the wrong thread. The ceiling was never reset. Every provider
response succeeded. Browser console and page-error lists were empty. Research fallback warnings
reported no Brave/DDG snippets; local PostHog was intentionally disabled without a key.
Post-retry inspection blocked every new generation start and made no model calls.
Mock transport/UI screenshots cover retry placement and controls, but provide no fresh-generation
evidence. Legacy paths retain unit-test evidence only; the real-provider journey exercised staged
flow. After retry, a separate no-model session dragged a node, saved and reloaded its exact changed
position with the same graph version and messages. Restoring the original view state through
`/api/threads/{id}/graph` returned 204; canonical graph, layout and all 60 messages matched exactly.

Evidence is retained outside the repository in `work/pr65-offline-approved.log`,
`work/pr65-postgres/results.md` and `work/pr65-verification/`, including source hashes,
persisted snapshots, browser results and provider telemetry. Local checks do not establish
production lock latency, managed Supabase authentication or protected staging evaluation.
