# Canonical Quality and Release System

## One local and GitHub entry point

`ci/quality.json` owns offline groups, commands, tracked-test assignment,
change-impact rules, live suites, and PR budgets. Follow the
[test-scope policy](engineering-principles.md#test-scope):

```bash
./scripts/ci offline
./scripts/ci offline --base origin/main --head HEAD
./scripts/ci offline --group api-integration
./scripts/ci offline --full
./scripts/ci browser --suite pr --target http://localhost:5173
./scripts/ci live --suite pr --target https://candidate.example \
  --input artifacts/live-eval/browser-results.json
```

The default offline command compares the branch to local `origin/main` and
includes staged, unstaged, and untracked files. Fetch the baseline when stale.
`--base` selects another baseline; adding `--head` restricts verification to a
committed range. Missing Git refs fail explicitly. `scripts/prepush_check.sh`
delegates to this default and forwards options. An empty local change set runs no
checks. CI keeps manifest validation even for an empty event range. Policy tests run only\nwhen their contracts change.

CI selects and executes checks using the same event scope. Backend source changes
run their owning domains and mapped consumers. Backend test-only edits, optionally
with documentation, run only changed test files. Mixed source changes retain the
affected domain suites. Unchanged dependency audit inputs skip their audits.
Shared backend settings and unknown owners require full verification; policy and
runner edits use the relevant selection and workflow contract tests.

Frontend source changes use Vitest's transitive dependency graph. Changed test
files join the same invocation. CSS, public assets, and HTML use lint and build
checks. Shared frontend configuration, package changes, or deleted source/test
modules require full frontend coverage. Deleted modules require this fallback
because Vitest excludes them from dependency discovery. Package changes and
explicit full frontend checks also run the dependency audit.

Explicit `--group` runs a whole group; `--full` runs all groups. Full backend
coverage replaces duplicate domain test executions. Repeated backend test files
across domain groups execute once, while non-test checks such as migration and
Terraform validation remain selected. Record the justification for broader
verification. Reuse passing evidence while its relevant inputs remain unchanged.

The manifest validator discovers every `backend/tests/test_*.py` file and fails
when a test is omitted or a stale path remains. Full backend coverage enforces a
90% line floor. Full frontend coverage includes every production TypeScript and
TSX module, including modules no test imports, and enforces 90% statements, lines,
and functions plus 75% branches. Offline suites use dummy credentials and fake
provider clients; live model evaluation remains a separate protected gate.

The stable branch checks are `CI required` and `Live eval required`. Both workflows
listen to `pull_request`, trusted pushes, and `merge_group`. AI-impacting changes run
the automated browser and semantic checks. Human corpus labels and judge calibration
are optional evaluation tools; pending review metadata does not block execution or
promotion. A successful live check records the tested Git tree and immutable image
digest. Production still requires that exact image and successful smoke checks.
Run `scripts/configure_main_branch_protection.sh owner/repo` to inspect the current
and proposed branch protection without writing. Add `--apply` only after reviewing
the payload.

## Trust and staging isolation

Live, scheduled, and production-smoke browser workflows build the frontend and
serve it through Vite preview with the security headers from `frontend/vercel.json`.
The preview proxies HTTP and WebSocket API traffic to the candidate backend.
`NODE_ENV=development` preserves the existing development-only internal auth
bootstrap. These runs exercise deployed CSP restrictions, including private diagram
capture; they do not claim full production-build semantics.

The live workflow uses `pull_request`, never `pull_request_target`. Paid live
generation runs are required when changes affect generation behavior. The manifest
identifies non-runtime documentation, offline test files, CI policy, composer
interaction code, and audited presentation owners whose copy or icons do not
affect generation. These changes receive a successful no-live-calls result and require meaningful offline or UI
checks for the affected behavior. Mixed changes still require paid evaluation when
any changed path affects generation. Unknown paths remain fail-safe AI-impacting.
CI policy changes run affected selection, runner, and workflow contract checks.
A broader matrix requires a concrete dependency or failure justification.
A policy-only edit does not require a paid generation run.

Classification uses paths and cannot determine the meaning of individual edits
within a shared runtime file. Audited presentation-only frontend source changes
can be recorded in
`impact.reviewed_presentation_changes`: each record contains `path`, full Git
`before_blob` and `after_blob` hashes, a `reason`, and completed offline/UI
`verification` evidence. Source modifications and deletions are supported. Added
source CSS uses forty zeroes for `before_blob`; other additions are rejected.
Audited modifications to `frontend/package.json`, `frontend/package-lock.json` and
`frontend/index.html` use the same exact-content check. These metadata paths cannot
use addition or deletion records. Use forty zeroes for a source deletion's
`after_blob`. CI matches
the exact base/head content transition and the checked-out HEAD blob and mode.
A synthetic merge that changes the reviewed content receives no exception.
Stale records, renames, file type or mode
changes, and path-only classification receive no exception. Malformed records fail
validation. Other generation-affecting paths in the same change still require paid
checks. These records never exempt backend runtime. Remove obsolete records when
updating this ledger. Keep stable presentation code in separate owners
when practical. A future runtime prompt stored in Markdown remains
generation-impacting. `frontend/src/components/Chat/ChatInput.tsx` owns composer
interaction and is verified with offline frontend and context-preservation tests.
Backend request routing, transport, and private renderer geometry remain protected
because they can affect generation or diagram publication.
The existing CSS/assets classification is unchanged. GraphCanvas CSS still
requires generation evaluation unless its exact content transition is audited.
An unaudited dependency or metadata change also remains generation-impacting.
Presentation audits must verify that shared private rendering is unchanged.

Changes limited to non-runtime files, composer interaction, or audited frontend
presentation retain the approved running backend. These frontend changes can
deploy without paid generation calls. This classification does not cover backend
runtime changes, including copy edits inside backend runtime files.

An AI-impacting fork receives no secrets and fails with instructions for a
maintainer to copy the reviewed patch to a same-repository branch.

Same-repository AI changes wait for approval of the `staging-eval` GitHub
Environment. Its federated GCP identity is bound to that exact
Environment-bearing OIDC subject, can read only staging secrets, and cannot
impersonate the separate production deployer. The `production` Environment has an
independently bound identity. Production accepts only successful push or manual
workflow runs from this repository's `main` branch, checked before source checkout.
Staging mutation is globally serialized. A database
advisory lock is held while the constant `staging` schema is dropped, recreated,
and migrated from scratch. `DB_SCHEMA` accepts only `public` or `staging`;
application connections and Alembic both pin their search path. Before and after
reset, probes must show that the staging login cannot select from or update
`public.profiles`. The staging login has no database-wide schema-creation privilege;
it can invoke only a fixed, security-definer reset function that recreates the
constant `staging` schema. While the lock is still held, reset derives a stable UUID
from the allowlisted internal-test email and inserts that identity into
`staging.profiles`. The browser then authenticates through the app's protected
internal-login flow. The staging role has no access to managed Supabase Auth or
production application tables. Production retains its `auth.users` foreign key and
`auth.uid()` policies; staging uses the equivalent request-JWT subject expression in
its policies because Supabase intentionally restricts the managed `auth` schema.

One-time database setup is an explicit write:

```bash
SUPABASE_ADMIN_DB_URL='...' STAGING_DB_PASSWORD='...' \
  python scripts/provision_staging_role.py --apply
```

Review the script and recovery plan first. It creates/rotates only
`agent_staging`, revokes its explicit public privileges, grants object creation only
inside `staging`, and exposes the fixed reset function. Store its URL as
`staging-supabase-db-url`. Store a separate, main-only migration identity as
`production-migration-db-url`.

## Browser evidence and budgets

The PR suite contains eight journeys: grounded RAG, memory, education, research,
node follow-up, graph expansion, an applied domain, and prompt injection. Empty and
oversized input stay in deterministic API tests and spend no model calls.

The education journey replaces the removed graph-off control journey. The seven
graph-bearing turns need four batches at the two-case graph concurrency limit.
Four 970-second turn deadlines plus 180 seconds of setup require 4,060 seconds;
the browser suite cap is 4,200 seconds. The application attempt cap is 78, covering
70 logical calls plus the allowed adapter retries on complete successful paths.
The first-pass path uses 42 calls. Additional failure recovery can exhaust the cap
and must fail the run. Judge calls remain capped at 16; infrastructure retries stay
disabled. These are ceilings, not target spending.
The staging job allows 100 minutes: 70 for browser work, 20 for semantic review,
and 10 for setup and evidence upload.

Playwright uses the real frontend and production WebSocket protocol. The eight PR
cases run with total concurrency four and a separate two-case graph lane, so two
independent graph-producing journeys can run together. Every case
attempt receives its own authenticated browser context and thread. Turns within a
multi-turn case remain sequential on that context, and result ordering remains the
canonical corpus ordering even when cases finish out of order.

Browser corpus `2026-09-28.v1` uses the product's fixed automatic depth, enabled
diagrams, and enabled research. It verifies these settings on each outgoing start
message. The composer resolves the server's intent check without a choice dialog.
Completion requires the composer to leave its generating state and a captured
WebSocket `done` event; the follow-up send arrow can remain visible during generation.
Diagram paths expose their underlying
directed connection members so the browser can verify every connection, including
duplicates and replies, when the canvas bundles several records into one path.

A completed transport is not evidence that a new diagram was generated. Empty
turns are rejected unless they contain a newly approved, nonempty graph. Keeping a
previous graph, replaying a completed request, or showing a failure notice does not
count as fresh generation. Provider failures and invalid model output remain
failures; the application does not substitute a reference diagram or bypass review.

The WebSocket `ready` event advertises `turn_timeout_ms`, derived from the server's
workflow deadline plus 60 seconds for delivery. The client bounds connection setup
to 30 seconds per attempt, retains one pre-start retry, and never retries started
work automatically. A started-turn timeout asks the user to reopen the chat before
retrying because the result may already be saved. Terminal answers stop waiting for
a missing canvas acknowledgement after three seconds. These bounds prevent silent
waiting; they do not establish a 100% model-generation success rate.

Private diagram evaluation stays mounted across chat and dashboard navigation.
It measures the completed SVG geometry without waiting for animation frames or
font promises, since background tabs can defer painting. The renderer uses system
fonts; adding asynchronous fonts requires a bounded readiness policy. Image capture
has a three-second deadline and submission retries have a single 2.5-second budget.
Capture failures produce rejection reports. No failure image can approve a diagram.
The server retains its 15-second evaluation deadline for suspended or disconnected
browsers.

Staging request concurrency is 16, owned by
`ci/quality.json` at `live.budgets.staging_request_concurrency`. Terraform and both
evaluation deployments read that budget. Runtime validation requires at least
twice the browser case concurrency to leave HTTP capacity alongside long-lived
WebSockets. A September 11 full-corpus run exhausted the previous four-request
limit with four browser cases and received Cloud Run 429 responses because its
single instance had no request capacity. Staging retains a maximum of one instance
and serialized evaluation workflows. Each deployment verifies Cloud Run's returned
request concurrency against the budget before browser evaluation and records the
verified value in `deployment.json`. Production retains its separate concurrency
setting.

The Anthropic semaphore allows four streams per application process/Cloud Run
instance; it is not a global account cap. It bounds Opus architecture and Sonnet QA
calls. Kimi graph construction uses the Moonshot OpenAI-compatible endpoint and the
two-case graph lane remains the suite-level concurrency bound.

Each attempt records received events, final answers, graph JSON, rendered-node
counts, screenshots, redacted traces, persistence, cleanup, fallback, and typed
blocking failures classified as `quality` or `infrastructure`. Paid browser cases
do not retry automatically. A whole-case retry repeats every model call made before
an infrastructure fault, so a new protected run requires an explicit operator action.

For the allowlisted internal identity on the isolated `staging` schema only, the
retrieval workers also emit bounded book passages, external search snippets, and
provenance so citations can be verified; production users never receive these
evidence events. Traces are rewritten before upload so bearer credentials and the
internal password are redacted. JSON, JUnit, HTML, screenshots, and traces are
retained for 30 days and are not committed as answer truth.

To diagnose a small set without replaying the whole corpus, manually dispatch
`Scheduled evaluation` with suite `diagnostic` and one to eight space-separated
case IDs. The same targeted mode is available locally by repeating `--case`, for
example `./scripts/ci browser --suite diagnostic --case citations ...`. Diagnostic
runs use the PR-sized time, application-call, and judge-call budgets. A manually
dispatched full or diagnostic run can build an ephemeral image when that exact tree
has no previously passed image. Its temporary tag is removed after evaluation.
Scheduled and nightly runs require an existing `approved-tree-<tree>` image to avoid
implicit candidate builds. Only the successful protected PR evaluation publishes that
tag; scheduled captures do not grant deployment approval.

`Semantic review replay` has two isolated modes. The default `full-scheduled` mode
preserves the existing behavior: it authenticates a successful full scheduled run,
reuses its deterministic browser capture, and records semantic proposals without
generating application answers again. `pr-selective` is a trusted, main-dispatched
manual review lane for rejudging an ordered subset of the eight PR cases from one
exact failed same-repository `Live eval required` run. It requires the exact run ID,
artifact name, source head SHA, authenticated reviewer, and a specific reason.

The selective lane verifies the completed failed PR run and immutable GitHub
artifact, binds the recorded deployment to the two distinct source-head/base merge
parents, tree, and image digest, and then uses `eval.evidence_replay subset` to write
a diagnostic capture containing only the selected results, case states, and
attributed telemetry. It runs `scripts/ci live --suite diagnostic --capture-replay`
with the selected cases, so it performs judge calls only: it does not open a browser,
call the application model, authenticate to GCP, deploy, or mutate staging. Every
selected semantic decision must be `pass` or `manual_review` with a passing blocking
status. Failure, infrastructure errors, reordered/duplicate results, or missing
provenance fail closed. The
30-day replay artifact contains the subset capture, live result, and provenance with
original/derived hashes, source run/head/tested commit/tree/digest, selection,
artifact digest, replay commit/actor, reviewer, and reason. Selective replay is
review evidence only and does not itself publish an image approval or deploy.

The `Live eval required` workflow also supports failed-only PR verification through
`workflow_dispatch`. Supply `source_run_id`, `source_run_attempt`,
`reviewed_diff_sha256`, and a review `reason`. The diff hash is SHA256 of
`git diff --binary SOURCE_HEAD CANDIDATE_HEAD`. Optional
`application_attempt_limit` and `judge_attempt_limit` inputs restrict the default
78/16 attempt caps. Both must be positive integers within those defaults.

The resume lane authenticates the failed protected PR attempt, uploaded artifact,
deployment, unchanged base, candidate tree, reviewed diff, corpus and judges.
Quality-failed cases run again on fresh application threads. Judge infrastructure
failures replay their saved captures. Validated passing cases retain their original
application and judgment lineage. The authenticated source manual-review policy
also applies to the combined result: report-only `manual_review` cases retain their
literal decision and old lineage without new calls; blocking ones replay and remain
blocking until resolved. Retained outcomes are not fresh verification of the repair.

`eval.pr_resume prepare` saves the selection and explicit judge budget before
deployment. `eval.pr_resume judge` revalidates that budget against the workflow
argument, reserves it once, and shares the remainder across fresh and replay phases.
The combined artifact records each case's original or fresh evidence. The native
required check and image approval require complete validated coverage under that
policy. A new paid attempt requires explicit operator authorization.

PR evaluation limits are eight cases, 78 application provider attempts, and 16
judge provider attempts. The current PR corpus has 42 first-pass calls and up to 70
logical application calls on its complete repair paths. Allowed retries and fallbacks
raise the successful-path allowance to 78 provider attempts. The tagged staging
revision atomically reserves one shared quota record before each provider request
and rejects attempt 79 before it is sent. Failed-turn recovery can exhaust this
quota. Production traffic does not set this
evaluation-only quota. The timeout chain is deliberately nested: the backend
agent envelope is 940 seconds, with model work stopping at 910 seconds to retain persistence
headroom. The Playwright turn waits at most 970 seconds so it can capture the typed terminal event,
and Cloud Run accepts a request for at most 1000
seconds. The browser-suite timeout scales with the number of turns and the two-wide
graph lane, with a 70-minute hard ceiling. Semantic judging is capped at 20 minutes
for PR/smoke/diagnostic suites and 60 minutes for full suites. Each semantic judge
request has a 120-second deadline and at most one transport retry. This request
deadline shares the suite's existing wall-clock and provider-attempt budgets;
it does not extend either limit. Exhausted retries record a safe exception class
and HTTP status when available, without provider messages or request data.
The outer GitHub jobs
allow 100 minutes for the PR gate and 150 minutes for scheduled evaluation, including
installation, deployment, judging, artifact upload, and cleanup; the former 15/30
minute limits no longer apply.

Scheduled nightly and full suites use the same pre-request quota with a 150-attempt
cap. Diagnostic dispatches use the 78-attempt PR cap.
Every scheduled browser failure or blocking semantic outcome fails the workflow.
Borderline semantic findings are retained as nonblocking review information. Scheduled artifacts retain evidence for 90 days. `deployment.json`
binds the run to its commit, Git tree, immutable image digest, tagged Cloud Run revision,
pipeline mode, and suite. The browser results record the cases that ran.

Protected internal staged evaluations capture each valid semantic gate result together
with its candidate records and review inputs. These captures require an evaluation run
ID and an allowlisted non-production caller. They are absent from ordinary responses
and analytics. This retains the first rejection when a correction later fails.

Each turn records total, first-event, and first-token latency plus client and server
request IDs. Those IDs join browser evidence to per-operation model telemetry,
including provider/model, generation duration, provider semaphore queue wait,
fallback, and every provider attempt. Reports publish deterministic nearest-rank
p50/p95 summaries for case end-to-end, turn end-to-end, first event, and first token;
final infrastructure-failed cases are excluded from those baselines. Latency remains
report-only with no manifest thresholds while five clean runs are collected.
Reviewed baselines can then add blocking thresholds without changing the 940-second
correctness deadline. Stage durations may overlap and are reported independently
rather than added into a false critical path.

Application cost accounting is likewise retry-aware: all threads from all browser
attempts are attributed back to their case, then split by model operation and
provider attempt. Input/output tokens, prompt-cache reads, queue wait, and estimated USD use a dated
price table; fallback and failed charged attempts are included. Protected evaluation revisions enable
Anthropic's five-minute prompt cache for repeated stable role prompts. Production app revisions leave
it disabled because sparse traffic may not recover the cache-write premium. Kimi automatic-cache hits
use their discounted input price. Judge usage is
reported separately and per case. Judge totals remain unknown when an attempt
lacks complete usage, resume provenance is unverified, or budget admission is
rejected; valid recorded charges remain a known subtotal. An unknown model price
is an infrastructure failure, never zero cost. Cost limits are currently
report-only and unset while at least five clean runs establish per-case and suite
baselines; only reviewed limits should be promoted to blocking. Explicitly
incomplete provider usage, including a timeout before an acceptance event,
leaves total cost unknown and reports a known
subtotal. This accounting uncertainty is nonblocking in report-only mode and blocks
when cost policy is blocking. Malformed or missing telemetry remains an infrastructure
failure. Unrecovered provider rate limits, transport failures, and
timeouts remain infrastructure failures and never masquerade as quality regressions.

## Automated semantic policy and optional calibration

`backend/eval/corpus/v1/cases.json` is a versioned 20-case corpus containing prompts,
UI modes, deterministic expectations, and anchored rubrics. The PR suite selects
eight cases. Generated answers remain evidence artifacts.

Deterministic and critical semantic failures block immediately. A clear noncritical
failure gets one independent second judgment; two clear failures block. More than
15% failing noncritical dimensions is a clear failure. A borderline dimension cannot
hide that failure. Borderline-only results and judge disagreements remain
`manual_review` in reports and use the default `report-only` exit policy. Infrastructure
errors, missing accounting, and configured blocking cost limits still fail.
`--manual-review-policy blocking` explicitly restores a blocking review policy.

The corpus may retain `pending_human_review` metadata while automated checks run.
That status records the absence of human labels; it is not a release prerequisite.
`semantic-rubric-judge-v17`, Anthropic, and `claude-sonnet-5` are the versioned judge
selection. The Anthropic request uses high reasoning effort with a 16384-token
budget shared by reasoning and structured output. Its prompt directs the judge
to reserve room for complete schema output. The judge receives the case
and rubrics before artifact sources, with numbered evidence chunks in source
order. Reports record the active provider, model, and prompt release.
Calibration remains pending.

`corpus_sha256()` hashes prompts, rubrics, UI modes, and deterministic expectations.
It excludes human approval metadata, so adding labels cannot change behavior identity.
The optional `--require-approved-corpus` mode verifies the full human approval manifest
and calibrated judge identity. Optional calibration requires a complete 20-case
capture, reviewed grades, reviewer identity, and immutable evidence provenance.
Manually dispatch `Scheduled evaluation` with suite `full` to collect that capture.
It does not publish a deployment approval tag.

For the first calibration, keep aggregate corpus approval pending while recording
all 20 human-reviewed cases and the pinned judge and browser evidence identity.
Every case's `review_run_id` must match the pinned `evidence_run_id`. Compute the
baseline from a full semantic replay of that capture with `--capture-replay`;
the original application-run report is not a semantic replay. The frozen
judge-selection JSON contains `format_version: 1`, `provider`, and `model`.

```bash
PYTHONPATH=backend python -m eval.calibration \
  --input artifacts/live-eval/live-results.json \
  --evidence artifacts/live-eval/browser-results.json \
  --context artifacts/live-eval/replay-context.json \
  --judge-selection artifacts/live-eval/judge-selection.json
```

After calibration passes, record its computed results and complete aggregate
corpus approval and the approved manifest hash. Calibration does not approve the
corpus or change its review records.


## Immutable judge-calibration evidence

Judge calibration replays the exact browser evidence that humans reviewed; it never
generates fresh application answers. The manual `Promote calibration evidence`
workflow reads the pinned identity from the approved corpus. It authenticates the
exact completed same-repository `Scheduled evaluation`, source commit and run
context, source corpus behavior, ordered complete 20-case browser capture, dashboard
success, and browser digest. The source may be a candidate branch and may conclude
`failure`. Complete captured product failures are eligible negative examples; missing turns,
terminal events, answers, artifact references, or infrastructure-failed cases are ineligible.
Calibration retains deterministic failures even when its semantic judge passes a response.
Every human-reviewed case must identify that same evidence run. It then stores both the
content-addressed browser JSON and its promotion manifest under
`reviewed/<corpus-sha>/` in the private GCS evaluation-evidence bucket. Uniform
bucket access, public-access prevention, versioning, a one-year retention policy,
and a two-year lifecycle protect the evidence from casual replacement or deletion.

The weekly `Judge calibration` workflow resolves the reviewed evidence digest,
source run, and source commit from the corpus calibration identity, downloads and
rehashes that exact GCS object, and runs `--capture-replay`. Only judge calls are
charged. Before replay it requires both GCS objects, rehashes the browser capture,
and verifies that the promotion manifest matches the pinned corpus digest, evidence
digest, source run, source commit, and judge model. Missing objects or identity
mismatches fail visibly; there is no pending/no-op success path. After authenticating
the untouched legacy capture, it writes a replay copy with the current behavior-only
corpus digest; the approved evidence hash still covers the untouched original. It
then compares the active judge prompt/model with the fixed human grades and fails below 85%
agreement, above one critical false pass, on an identity mismatch, or after an
agreement drop greater than five percentage points from the approved calibration.
Reports are kept in 90-day GitHub artifacts and copied to GCS calibration history.

The judge receives the public graph's directed flow, synchronization, descriptions, and sequence.
The final graph is encoded once when it equals the last turn's graph. A different final graph
retains its own evidence, including a final state that matches an earlier turn. The 80,000-character
prompt limit rejects oversized packets without truncating graph contracts.
For new captures it receives the exact synthesis-visible book and research strings. Older retrieval
telemetry is labeled as incomplete knowledge of the model input; source text beyond the supplied
excerpt cannot certify the answer's grounding. Judge release v6 records this changed evidence contract.

An override is an audited `workflow_dispatch` requiring original run ID, full
commit SHA, authenticated reviewer, and reason. Dispatch it from the tested
commit's own branch/ref; the workflow requires `GITHUB_SHA` to equal the supplied
commit so GitHub attaches the required check to the right revision. The protected
workflow downloads the original deployment identity, verifies the exact
commit/tree/digest, records a 30-day audit artifact, and only then publishes the
exact-tree approval tag.

## Exact-digest production promotion

Successful staging evaluation tags the immutable image digest with the Git tree
hash. The production workflow starts only after a successful main `Live eval
required` run and will not rebuild a missing approval. It then:

1. applies the reviewed migrations to `public` with the main-only identity;
2. deploys the approved digest as a no-traffic production candidate;
3. exercises readiness, internal authentication, dashboard, persistence, graph
   rendering, cleanup, and one real-model browser journey;
4. sends 100% traffic to that tagged candidate only after success.

The previous Cloud Run revision is left available for rollback. Nightly runs rotate
four cases, while Sunday runs cover the full corpus. Staging revision and ephemeral
image tags are removed after evaluation; the content-addressed approval tag and
30-day evidence remain.
