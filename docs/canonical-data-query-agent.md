# Canonical example: data querying AI agent

Approved by the product owner on 20 October 2026 with: "can make this a canonical
example - this is good". Use this example when reviewing diagram presentation and
how an answer explains a concrete AI system.

## Approved reference

Prompt: `data querying Ai agent`.
Diagram title: `Data Querying AI Agent (Natural Language to SQL)`.
The approved view shows 11 components, six zones and five walkthrough steps.

Source: `Screenshot 2026-10-20 at 3.27.07 PM.png`.
Original image SHA256:
`d8dddbc7c84cd3d95b5e6c7a718662eeb79cd0a44d58b2a8413f2485078eea89`.
The original screenshot is retained with the local task outputs as
`canonical-data-query-agent-reference.png`. It includes browser and account chrome,
so it is kept outside the published repository.

## Presentation standard

- The diagram is the main workspace beside its explanation. Chat history remains
  compact, and pane boundaries are clear.
- The header gives the diagram title and discreet component and zone counts.
  Keep the removed overview-description row absent.
- Zones identify responsibilities with a restrained colored frame and matching
  heading. Labels wrap inside their boundaries with space above and below.
- Component labels are readable at the chosen zoom. Secondary type labels stay
  quieter than component names. Connections and arrowheads remain distinguishable.
- The main request path reads across the workspace. Supporting model-provider,
  data and audit responsibilities sit beside that path without obscuring it.
- Controls stay compact. Walkthrough controls sit below the canvas. The diagram
  remains pannable when its readable size exceeds the viewport.
- The explanation refers to the displayed component names and walks through a
  concrete question, the SQL request, execution and the resulting answer.

## Visible system responsibilities

| Zone | Components shown |
| --- | --- |
| Analyst interface | Analyst client |
| Request entry and authentication | API gateway |
| Query agent services | Query agent orchestrator; Schema context selector; SQL proposal validator; Answer grounding checker; Query execution service |
| External model provider | LLM provider |
| Data stores | Analytics data warehouse; Schema catalog |
| Logs and monitoring | Audit log store |

The accompanying answer uses "How much did we sell last month?" as its example.
It describes scoped schema access, SQL drafting, a single read-only SELECT with
row and cost limits, execution, checking the answer against returned rows, bounded
regeneration and abstention, and audit recording. This is a useful reference for
explaining responsibilities and safety boundaries in an applied agent diagram.

## Use in reviews

Compare responsibility grouping, label containment, visual hierarchy and the match
between the explanation and its diagram. Adapt component counts and topology to
the question. This example does not require every system to contain 11 components
or six zones.

Approval covers the visible example. It does not certify every underlying edge,
SQL control or citation. The visible 4m 43s generation duration is not a latency
target. Keep sources accessible without exposing long raw URLs in the answer.

This reference supports manual reviews. For a structured fixture, use the actual
saved graph export to preserve identifiers, complete edges and coordinates.
