# Diagram quality follow-up, 2026-09-28

## Failure boundaries and changes

External API outages now display "The external API service is unavailable. Please
try again." A closed-loopback provider check with a fake key verified the exact
notice and its persistence without contacting an external provider.

Broad teaching requests could become an unrequested product walkthrough. The
component generator and shared review criterion now preserve the subject's
breadth; examples support the subject. Applied-service instructions apply to
requested system designs. Component ownership review distinguishes producing an
input, evaluating it, storing evidence, approving a decision and executing it.
Competing authority over the same operation still blocks. Connections must supply
the required handoffs. Add-only edits preserve existing owners.

Explanation blocks previously validated citation metadata without checking inline
URLs. An answer could change a supplied URL and omit it from that metadata. Both
paths now validate against the same supplied identities. Markdown parsing handles
destinations, escapes and entities; code examples do not count as citations.
Unsupported blocks follow the existing rejection path. Oversized model blocks
reject rather than truncating a citation. Trusted server disclosures and completion
sentences no longer truncate accepted content.

Front matter has no chapter number. Shared book-reference formatting now uses
only known locations: `Chapter 6, p.299`, `Book, p.1`, `Chapter 6`, or `Book excerpt`.
The formatter is shared by evidence, synthesis, node detail and canonical graph
references. Malformed model placeholders cannot become supported references.

Routing used to split an authored component name at conjunctions before matching
an edit target. "Expand the Evaluation and educator oversight component" became
a create request. Clause splitting now preserves exact authored node/group names,
including punctuation and normalized whitespace. Negation, quoted text and
separate new-system requests retain their existing handling. The existing edit
scope then enforces one addition and preserves locked records.

Prompt identities are components v30, component gate v19, synthesis v30 and node
detail v1. Models, effort, deadlines and retry limits are unchanged. No migration
is included. Rollback uses the previous application revision.

## Retained failures

[Protected run 36421644021](https://github.com/yyqfrank420/ai-engineering-learning-agent/actions/runs/36421644021)
failed on PR52 head `708e9764ac1e21830165da38825c99898d08fc15`. CI passed, but the
live run found education scope narrowing, rejected expansion candidates and an
altered source URL. That run is not release approval.

The first local run used that head plus binary diff SHA256
`e4de9b92fffa8a5fc46617419abc53422ffda5f0b80959214dad1178997e48fa`.
It made 12 application calls. Its education answer exposed `Chapter None, p.1`;
its expansion replaced eight components with ten. Successful graph gates did not
establish correct preservation. Reopening made no additional provider calls.

A separate single Sonnet call reviewed the original saved SLO Evaluator candidate
under the clarified ownership policy and approved all four component rules.
It used 10,747 input and 3,826 output tokens. This was a fresh review of saved
input, not new diagram generation.

## Fresh local verification

The final application check used head `708e9764ac1e21830165da38825c99898d08fc15`
plus binary diff SHA256
`237167f60f5bc8e4a3659f21946edfc7f1210c9458622019bfcdd34ed71d2f17`.
The frozen inventory also hashed the new source module. All source files remained
unchanged through both UI turns. The account was `dev@local`, with a new empty
SQLite database, retrieval assets only, and production storage, authentication
and telemetry disabled. A shared 18-attempt ceiling covered both turns.

The exact request `tell me about ai engineering in education` produced a fresh
12-component topic map with 32 connections and three sequence steps. One bounded
component correction fixed capability flags. The answer covered techniques,
applications and governance and used the supplied `Book, p.1` reference. Version:
`dcdd04b0-98c3-4354-9aef-8693091cad02`.

The next typed request expanded "Evaluation of learning outcomes and model
quality" while preserving the topic and existing components, adding exactly one
directly connected responsibility. The protected edit path generated
"Evaluation pipelines and test sets". All 12 original node objects and all 32
original edge objects remained identical. Only one node and two feedback
connections were added. Version: `004c7bc3-81cd-4831-bf79-0933c9a5eaee`.

The two turns made 12 fresh application calls with complete usage records:
98,741 input and 14,153 output tokens. Provider prompt-cache accounting is distinct
from reused outputs. No saved diagram or answer supplied either generation.
Reloading and reopening preserved both answers and the accepted graph without
new calls. Browser warnings/errors were empty. Local servers were stopped after
verification. Including the failed local run and saved review, 25 actual provider
attempts were used across these local checks.

The final backend suite passed 2,965 tests with two skips and 92% coverage, above
the 90% floor. Whole-Python Ruff and Bandit passed. Dependency audits had already
passed for the unchanged final pins. These checks establish the recorded journeys;
they do not establish a universal generation success rate or citation entailment.
Protected PR CI and live evaluation remain separate release requirements.
