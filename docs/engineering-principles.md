# Engineering and AI Principles

This is the repository's canonical engineering standard. It adapts the supplied
Engineering Principles and AI Principles to this project. `AGENTS.md`, `CLAUDE.md`,
and Cursor rules point here instead of maintaining competing copies.

These principles guide decisions; they are not a reason to ignore a more specific
user requirement or to perform a sweeping rewrite. Prefer small, continuously
refactorable changes with evidence that they work.

## Engineering

### Make correctness easy to see

- Follow the Zen of Python: explicit, simple, flat, readable, and unsurprising.
- Keep functions focused. Split a function when its state or local variables become
  difficult to hold in your head, not at an arbitrary line count.
- Prefer immutable values and pure transformations. Limit variable reassignment and
  make side effects obvious at the call site.
- Do not add one-line wrappers, speculative abstractions, or indirection without a
  measured benefit.
- Comments explain non-obvious constraints, business decisions, workarounds, and
  trade-offs. They must not narrate code that clear names can explain.
- Use static analysis, types, tests, schema constraints, and automated checks instead
  of relying on reviewer memory.

### Put ownership in the lowest sensible layer

- Organise code by domain and responsibility. Do not introduce new generic `helpers`
  or `utils` modules. Improve legacy generic locations incrementally when nearby code
  is already changing and the move reduces complexity.
- API handlers authenticate, validate, and translate transport concerns. They should
  delegate domain and persistence behaviour.
- Agent nodes own orchestration decisions. Adapters own vendor protocols. Storage
  modules own persistence rules and transactions.
- Prefer one discoverable parameterised interface over several nearly identical
  functions selected by name.
- Handle empty collections, missing optional values, duplicate delivery, and
  out-of-order events deliberately. An "unlikely" state still needs defined behaviour.

### Design orchestration for retries and races

- Every externally retried write needs an idempotency key enforced at the durable
  boundary, normally by a database uniqueness constraint. A request ID used only for
  logs is not an idempotency guarantee.
- Make retry behaviour explicit. Never replay a partially streamed side effect unless
  the operation is proven safe to repeat.
- Protect read-check-write sequences with a transaction, lock, atomic statement, or
  constraint. Tests should cover duplicate and concurrent delivery where practical.
- Avoid cycles in which a process derives its next input from its own materialised
  output unless the feedback loop is an explicit, measured domain requirement.
- Degrade gracefully under load: bound concurrency, queue work, cap resource use,
  time out external calls, and preserve a useful reduced service when possible.

### Keep data canonical and durable

- Production Postgres is the golden copy for user, thread, message, runtime, and
  telemetry state. Process memory and local SQLite are development/runtime aids, not
  alternative production truths.
- Store raw, untransformed evidence or events when later interpretation may change.
  Build materialised views or summaries from that canonical record.
- Do not silently discard malformed or unexpected data. Reject it, quarantine it, or
  record a visible failure with enough context to recover.
- Customer-facing calculations and rounding belong in the backend. Frontends may
  calculate display-only geometry.
- Put units in persisted field and telemetry names, such as `_ms`, `_bytes`, or
  `_epoch`, even when the application type also carries the unit.
- Normalise independent dimensions in the database. Use a composed enum only when
  the domain names the combination, it removes invalid states, and every small variant
  has distinct exhaustively matchable behaviour. Otherwise use separate fields or a
  validated product type.

### Change schemas safely

- Use expand-then-contract for breaking changes: add compatible schema, deploy code
  that tolerates both shapes, verify all consumers have moved, then contract in a
  separate deployment.
- Set a short `lock_timeout` for production data definition language (DDL). Build large
  indexes concurrently where the database supports it.
- Inventory API, worker, analytics, and external consumers before a rename, drop,
  semantic change, stricter constraint, or foreign-key change.
- Every production migration needs independent review, a verification query, and a
  realistic rollback or forward-recovery plan.

### Hoist volatile inputs and protect boundaries

- Read time, randomness, environment, and request identity at the highest practical
  boundary, then inject them into domain functions. This makes behaviour reproducible.
- Keep environment access in the canonical configuration layer except for isolated
  command-line entry points and migration bootstrapping.
- Never put access tokens or secrets in URLs, logs, prompts, analytics, or user-facing
  errors.
- Authorise before revealing whether a protected identifier exists. Ownership-scoped
  queries should return the same public result for missing and unauthorised resources.

## AI systems

### Build a platform, not prompt-shaped one-offs

- Route model calls through the shared provider adapter so models and vendors remain
  swappable. Keep provider-specific request and response handling out of agent nodes.
- Reuse shared retrieval, telemetry, evaluation, safety, and persistence primitives.
- Use a specialised model or deterministic component when the input is narrow, errors
  are costly, or latency/cost requires it. A general model may orchestrate specialised
  components but must not duplicate their rules in prose.

### Treat models and prompts like released code

- Prompts, model identifiers, sampling/reasoning settings, and tool schemas are source
  controlled and reviewed.
- Give production prompt/model combinations a stable release identity or content
  fingerprint in telemetry. A failure must be traceable to the exact model and prompt.
- Select checks that exercise the changed behavior. Generation changes require focused
  regression tests and representative fresh generation evaluation. Copy, icons,
  documentation, and offline-test-only changes use appropriate offline or UI checks
  without paid generation calls. Mixed changes retain the generation checks. Never
  rely only on a successful API response.
- Maintain a rollback path: configuration rollback for models and normal deployment
  rollback for prompts/pipelines. Monitor quality, safety, latency, and cost after release.

### Assume every model can fail

- A model will hallucinate, be confidently wrong, and encounter poisoned context.
  Treat model output, retrieved text, web results, tool output, chat history, and
  model-generated artifacts as untrusted data.
- System prompts must state trust boundaries. Validate structured outputs with schemas
  and deterministic checks before publishing or acting on them.
- Give models the minimum tool permissions and data needed. Do not infer authorisation
  from natural-language content.
- Agent retries must be safe. Side-effecting tools require durable idempotency, policy
  checks, audit records, and bounded retry behaviour.

### Store context deliberately

- Short-range context is durable conversation history.
- Long-range context is selected structured facts, not an opaque transcript summary.
  Users must be able to inspect, correct, and delete facts retained about them.
- Business systems of record remain outside model memory. Models access them through
  narrow authorised tools rather than copying them into an AI-specific shadow store.
- Shared memory construction is a backend responsibility and must be provider-agnostic.

### Constrain costly writes

- Keep the current assistant's tools read-only unless a feature explicitly requires a
  write.
- Costly, trust-sensitive, or externally visible writes use a dedicated contextual flow
  that shows the exact proposed change and asks the user for explicit confirmation.
- Do not let a general model improvise confirmations or retry an ambiguous write until
  it succeeds. Prefer typed forms, deterministic validation, policy gates, and a clear
  cancel path.

## Test scope

- Select tests for changed behavior and affected callers, dependencies, contracts,
  and shared infrastructure. Unchanged code belongs in the selection when the
  change can affect its behavior.
- Do not run unrelated suites by habit, after each edit, or solely because a test
  runner defaults to the full suite.
- Broaden testing only for a concrete impact, shared configuration or dependency
  change, selection uncertainty, or an unresolved failure. Record the reason.
- Stop after relevant checks pass. Repeat checks only after further changes or
  new evidence that affects their result.
- Avoid duplicate execution of the same tests within a verification run. Collect
  coverage during the required execution where supported.
- Apply the same scope to subagents, local verification, CI, and live evaluations.
  Documentation-only changes use document review and applicable static checks.

## Working agreement

Before editing:

1. Read the relevant code, tests, current architecture, and `git status`.
2. Treat existing uncommitted changes as someone else's work unless ownership is clear.
   Do not edit an actively changed file for an unrelated task; choose a non-overlapping
   location or coordinate first.
3. State assumptions that materially affect architecture, data, or public behaviour.

While editing:

1. Make the smallest coherent change at the owning layer.
2. Add constraints and tests at the failure boundary, including empty, duplicate,
   unauthorised, malformed, timeout, and fallback cases that apply.
3. Delete superseded code and documentation in the same change when safe.
4. Keep canonical documentation current; label historical designs as historical.

Before handing off:

1. Run only the tests and static checks justified by the test-scope policy.
2. Distinguish failures introduced by the change from failures already present in an
   active worktree.
3. Report what changed, evidence run, residual risk, migrations/rollout needs, and any
   principle intentionally deferred.

Before opening or updating a pull request, or triggering cloud CI/CD evaluations:

1. Select verification for the affected behavior. Generation-affecting changes need
   relevant fresh generation evidence. Copy, icon, styling, documentation, offline
   test, and CI policy changes that do not affect generation need meaningful offline
   or UI verification; they do not require paid model calls solely for verification.
2. For application changes, exercise the affected local flow using the dev/local
   account and current source, with development services and storage. For generation
   changes, submit a representative request, inspect the rendered diagram and answer,
   and check affected editing, failure recovery, and reload/persistence behavior.
   Documentation, test-only, and CI policy changes do not require an unrelated app run.
3. Inspect relevant browser and backend errors. If a defect requires a change,
   fix it locally and repeat the affected checks. Reuse passing evidence while its
   relevant inputs remain unchanged. Keep existing model-call and spending limits.
4. Record the tested revision, account/environment where applicable, actions, results,
   and remaining gaps. Mocked transports, captured fixtures, unit tests, and screenshots
   support verification. They do not replace fresh generation evidence when generation
   behavior changed.
5. If required local verification is blocked, report the blocker and obtain an explicit
   exception before opening or updating a pull request or starting cloud evaluation.
   Applicable cloud checks remain required after local verification passes.

The CI manifest classifies paths conservatively. Copy inside a mixed runtime module
can still trigger generation checks because path classification cannot identify the
edit's semantics. Established non-runtime files, frontend composer interaction,
and audited presentation owners do not require paid generation checks. Backend
runtime files, backend request routing, prompts, transport, and private rendering
remain protected. Skipping paid evaluation does not authorize skipping relevant
offline checks or changing backend deployment guarantees.
