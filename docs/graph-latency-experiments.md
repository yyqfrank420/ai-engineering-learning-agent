# Graph latency and first-attempt quality

The product target is a first useful graph just over one minute on average,
with high first-attempt review acceptance. Completion latency remains a separate
measure. A component map, a connected graph, and a saved approved graph are
different milestones and must be reported separately.

## Baseline

Staging run `35647919042`, source `ac674eb`, generated 20 components and 83
directed edges without correction. Its first component map appeared at 117.6
seconds; the complete turn took 381.1 seconds. Component generation took 108.3
seconds, component review 24.3 seconds, connection generation 174.2 seconds,
connection review 30.4 seconds, and explanation 39.5 seconds. Both staged
reviews passed on their first attempts. Independent inspection still found
missing event-change input and incomplete release transitions for one target.

This is one complex production-depth case. It does not establish an average,
a first-pass rate, or the performance of ordinary learning questions.

## Evidence informing the changes

- [Kimi's reasoning-effort documentation](https://platform.kimi.ai/docs/guide/use-reasoning-effort)
  supports `low`, `high`, and `max`. The
  [K3 guide](https://platform.kimi.ai/docs/guide/kimi-k3-quickstart) recommends
  `low` when reasoning takes too long. The baseline staged author explicitly used
  `high`; it did not accidentally fall back to the provider's `max` default.
- [OpenAI's latency guide](https://developers.openai.com/api/docs/guides/latency-optimization)
  prioritizes generated tokens and serial requests. Input trimming is usually
  a smaller speed improvement. Keep structured records compact and use code
  for deterministic assembly.
- [Anthropic's workflow guidance](https://www.anthropic.com/engineering/building-effective-agents)
  favors simple workflows and treats extra model calls as a latency and cost
  tradeoff. Parallelism applies only when tasks have independent inputs.
- [Anthropic's evaluation guidance](https://www.anthropic.com/engineering/demystifying-evals-for-ai-agents)
  distinguishes task outcomes, trials, and graders. Repeated trials and
  inspection of retained traces are needed to judge model variability.

These sources motivate experiments. They do not prove the product meets its
target or that reducing reasoning effort preserves quality.

## Experiment rules

Keep deterministic schema, mutation, rendering, persistence, explicit-request,
and safety checks. Naming preferences and optional implementation detail do
not withhold an otherwise usable answer. Authoring and review share that
standard so generation does not have to guess what the reviewer will require.

Screen lower authoring effort with one new candidate per stage and the normal
reviewer. Stop on failure, record it, and inspect the cause before spending on
another call. Do not use repairs in the first-attempt acceptance numerator.
Retain exact prompts, schemas, outputs, source hashes, timing, and complete cost
telemetry. Reuse existing captured inputs before running a fresh browser journey.

A screen against an older captured request with updated prompts is a directional
comparison, not a controlled A/B test. Small samples must show their denominator.
Report mean latency only for completed comparable trials; list timeouts and
failures separately so excluding them cannot hide poor reliability.

No new service, model provider, or orchestration layer is needed for the first
experiment. Do not reduce output limits solely to force speed: truncation can
create another paid attempt and lower first-attempt quality.

## Local screening results on September 21

| Screen | Components | Component review | Connections | Connection review | Outcome | Estimated cost |
| --- | ---: | ---: | ---: | ---: | --- | ---: |
| Low effort, original source context | 27.1s | 12.8s | 51.2s | 30.9s | Rejected | $0.143563 |
| Low effort, concise ownership and source-only context | 33.2s | 12.7s | 40.1s | 44.3s | Approved | $0.157100 |

Each screen made four calls and no repairs. The first produced 11 components and
40 edges; its compensation recommendation stopped at storage without reaching
approval or execution. Some descriptions ended mid-word at schema limits.
The second produced 14 components and 64 edges, with complete descriptions and
an execution path for compensation. Its component map was ready at 34.6 seconds,
connected candidate at 87.4 seconds, and final review at 131.6 seconds, including
1.4 seconds of local setup. These timings exclude browser rendering and synthesis.

The second review also claimed some mechanisms that the graph did not explicitly
state. Commit `9defb83` adds concise ownership guidance for writer deduplication,
stream backpressure and ordering, an example of outcome actions, and a requirement
that review reasons acknowledge unspecified detail. The cloud check below includes
those final prompt adjustments; the local approval does not validate them.

The new default is low authoring effort with the existing reviewer model,
review effort, schemas, and correction limits. These two screening trials do not
establish a high first-pass rate. Their combined estimated cost was $0.300663.

## Cloud browser results

Run `35654002226` tested commit `9defb83` on staging. Cloud CI passed all 11
canonical groups on the same source tree. Both browser cases passed deterministic
and final semantic evaluation. Persisted graphs exactly matched emitted graphs;
rendered node IDs, edge identities, and versions matched both.

| Case | Component map | Connected draft | Saved approved graph | First component / connection review |
| --- | ---: | ---: | ---: | --- |
| Educational agent with tools and memory | 34.5s | 65.8s | 140.4s | Pass / fail |
| Production marketing system | 35.1s | 84.9s | 143.0s | Pass / pass |
| Mean, two cases | 34.8s | 75.3s | 141.7s | 2/2 / 1/2 |

The educational case needed one connection correction. It used 35.6 seconds for
generation and review of that correction. There were no provider or browser
retries. The run made 13 application calls and two final judge calls, with complete
usage and an estimated total cost of $0.578664. The production case finished its
turn in 143.4 seconds, compared with 381.1 seconds in the earlier single-case
baseline. This is an uncontrolled comparison across changed prompts and effort.

Independent inspection found no demonstrated missing requested behavior in the
new production graph. It contains adjustment inputs for copy, targeting and event
definitions, approval revalidation, executable compensation, and separate canary,
promotion and rollback contracts for its serving target. It has 13 components and
51 connections, compared with 20 and 83 in the baseline.

The prototype rejection followed a depth-independent rule requiring approval,
audit and recovery for external mutation. The candidate had generic tool labels,
a true external-effects flag, and guardrail-checked dispatch, but no concrete
external mutation was identified. The follow-up changes only the staged prototype
rule: preserve explicit requested controls; require authorization and failure
handling for concrete mutations; allow existing guardrail ownership for generic
educational tools. Production and legacy requirements remain unchanged. This
follow-up was not part of the two-case browser run.

A single review-only replay of the unchanged original prototype candidate passed
all four connection rules under the corrected policy. Its original request,
evidence and nine connection records were preserved. The reviewer cited existing
guardrail-checked dispatch and the result or blocked-call response. The call took
14.6 seconds and cost an estimated $0.022046 with complete usage and no retry.
This checks the known rejection; it is not a fresh generation or a browser result.

The connected graph is complete structurally but remains a provisional preview.
Durable publication waits for semantic review, explanation, and atomic persistence
of the messages, graph, and contract. Explanation took 20.8 and 33.2 seconds in these
cases. Publishing earlier would require changes to cancellation, replay, and
persistence semantics; this experiment retains those invariants.

The measured connected-draft average is near the product target. A 1/2 connection
first-pass result does not meet the desired high pass rate, and two cases cannot
establish a production average. Keep the original rejection in reported results.
