# AI Engineering Learning Agent

Learn how AI systems fit together through conversation and interactive architecture diagrams.

Ask for a system, inspect its components, follow the walkthrough, and refine the design through chat. Built for people who can code and want to understand AI engineering, with *AI Engineering* by Chip Huyen as a reference source and optional web research for current context.

[Getting started](#getting-started) · [How it works](#how-it-works) · [Development](#development) · [Documentation](#documentation)

## What you can do

- **Learn through questions.** Ask about AI engineering concepts and discuss tradeoffs using book retrieval, conversation history, and optional authenticated web research. Research uses one Moonshot Basic search request and retains returned source snippets; unavailable research continues with book evidence.
- **Build a visual understanding.** Generate architecture diagrams, inspect component responsibilities and connections, and follow a guided walkthrough.
- **Refine a design.** Request targeted changes through chat. Scoped edits preserve retained component IDs and locked records; a rejected edit keeps the previously approved graph.
- **Make the canvas your own.** Move components and zones, resize zone borders, and save diagram positions, pan, and zoom with the conversation.
- **Steer an answer in progress.** Correct a request while it runs or stop generation from the chat interface.

Try a prompt such as:

> Design a customer-support assistant that retrieves answers from internal documentation. Explain the components and how they connect.

Then follow up:

> Add a human review step before the assistant sends a refund request.

## How it works

The React frontend pairs chat with a D3 diagram canvas. A FastAPI backend runs a request-scoped LangGraph workflow and streams progress over an authenticated WebSocket connection.

For an applied architecture request, the default staged pipeline:

1. Interprets the request and retrieves relevant book passages and optional web context.
2. Proposes components, checks their structure and browser rendering, and reviews their responsibilities.
3. Builds connections against the accepted components and reviews the complete design.
4. Writes the walkthrough, saves the accepted graph, and publishes the result.

Opus 5.5 (`claude-opus-5-5`) authors components and corrections at high effort; initial connections use low effort. Opus 5.5 medium reviews each staged candidate. Sonnet 5.5 handles legacy graph QA and writes the walkthrough.

Each stage allows one correction. Previews remain provisional until the graph passes its checks and is saved. If requirements are unclear, the agent can ask clarifying questions before building connections.

See the [current architecture](docs/current-architecture.md) for routing, model roles, persistence, and failure handling. `GRAPH_PIPELINE_MODE=legacy` remains an explicit rollback option for the applied graph pipeline.

| Part | Technology | Location |
| --- | --- | --- |
| Browser app | React, TypeScript, Vite, D3 | [`frontend/`](frontend/) |
| API and orchestration | Python, FastAPI, LangGraph | [`backend/`](backend/) |
| Book retrieval | FAISS and a local embedding model | [`backend/rag/`](backend/rag/) |
| PDF ingestion | Chunking, embeddings, index generation | [`ingestion/`](ingestion/) |
| Authentication and persistence | Supabase Auth, Postgres; SQLite for local development | [`backend/adapters/`](backend/adapters/) |
| Infrastructure | Cloud Run, Artifact Registry, Secret Manager, Terraform | [`infra/terraform/gcp/`](infra/terraform/gcp/) |

## Getting started

You need Python 3.12, Node.js 20.19+ or 22.12+, and npm. Chat generation uses Anthropic and Moonshot API credentials. The normal sign-in flow uses Supabase Auth and Cloudflare Turnstile.

### 1. Clone and configure

```bash
git clone https://github.com/yyqfrank420/ai-engineering-learning-agent.git
cd ai-engineering-learning-agent
cp backend/.env.example backend/.env
cp frontend/.env.example frontend/.env
```

Update the copied environment files before starting the app:

| File | Configuration |
| --- | --- |
| `backend/.env` | Add `ANTHROPIC_API_KEY` and set `MOONSHOT_API_KEY`. Configure the Supabase URL, anon key, JWT issuer, and Turnstile secret for your development project. HS256 projects also need `SUPABASE_JWT_SECRET`. Set `FRONTEND_ORIGIN=http://localhost:5173`. |
| `backend/.env` | Leave `SUPABASE_DB_URL` empty to use local SQLite. To use Postgres, configure a development database and apply the [repository migrations](scripts/apply_supabase_schema.sh) before startup. |
| `frontend/.env` | Set `VITE_SUPABASE_URL`, `VITE_SUPABASE_ANON_KEY`, and `VITE_TURNSTILE_SITE_KEY` for the same development setup. Leave `VITE_API_URL` empty to use Vite's proxy to port 8000. |

`ANTHROPIC_API_KEY` must be added explicitly; it is currently missing from the backend example file. Configure Supabase Auth to allow the local callback URL and use Turnstile keys that support localhost. Keep service credentials in the backend environment.

The repository includes the FAISS index artifacts in [`data/faiss/`](data/faiss/), so an ordinary checkout does not need PDF ingestion. Clear the example `FAISS_ARTIFACT_URL` and `FAISS_ARTIFACT_SHA256` values when using these local files. The embedding model may need to download on first use.

### 2. Start the backend

```bash
cd backend
python3.12 -m venv .venv
./.venv/bin/python -m pip install -r requirements-dev.txt
./.venv/bin/python -m uvicorn main:app --reload
```

### 3. Start the frontend

In a second terminal, from the repository root:

```bash
cd frontend
npm ci
npm run dev
```

Open [localhost:5173](http://localhost:5173) and sign in. The app checks backend readiness automatically after sign-in and refresh. Sending a message becomes available once the retrieval index is ready. If startup fails, the composer shows the error and a **Retry** button.

## Development

Read the [engineering principles](docs/engineering-principles.md) before contributing. Run tests for affected behavior and dependencies. The default command selects changed files against the local `origin/main` merge base, including staged, unstaged, and untracked files:

```bash
./scripts/ci offline
```

Fetch `origin/main` before verification when the local baseline is stale. Use `--base REF` to select another baseline, or `--base REF --head REF` to check a committed range without working-tree changes. A missing baseline fails rather than silently running everything.

Backend test-only edits run the changed test files. Backend source edits run the affected domains and known dependent domains. Frontend edits use Vitest's dependency graph; styling changes run lint and build checks. Shared frontend configuration and deleted source files require full frontend coverage because the dependency graph cannot select deleted modules.

Use `--group` to deliberately run a whole group, or `--full` when broader impact justifies all groups:

```bash
./scripts/ci offline --group pipeline-policy
./scripts/ci offline --full
```

`scripts/prepush_check.sh` uses the same affected-file default and forwards these options. Full verification includes ingestion, security, migrations, infrastructure, and the backend container and requires tools such as Terraform and Docker. Unknown owners and shared backend settings still require broader checks. Record the reason for broader verification, and stop once relevant checks pass.

Ingestion checks use a fake embedder and the tracked index artifacts by default. Set `AI_ENGINEERING_PDF_PATH` to check source-PDF parsing; opt into real local-model tests with `RUN_INGESTION_MODEL_TESTS=1`.

Live browser and model evaluations are separate protected checks. See the [quality and release guide](docs/quality-system.md) for commands, credentials, evaluation budgets, and evidence requirements.

## Deployment

The deployment target is Vercel for the frontend and Cloud Run for the backend, with zero minimum backend instances. Automatic startup checks handle retrieval readiness after a cold start.

Production promotion requires an approved immutable image for the exact Git tree and a successful smoke check before traffic moves. Check the release evidence for the validation and deployment status of a specific revision.

See the [hosting plan](docs/expansion-plans/cloud-run-cost-first.md) and [Terraform guide](infra/terraform/gcp/README.md) for infrastructure details.

## Documentation

| Guide | Covers |
| --- | --- |
| [Product](PRODUCT.md) | Audience, learning goals, and interaction requirements |
| [Current architecture](docs/current-architecture.md) | Runtime behavior, graph workflow, and data flow |
| [Quality and releases](docs/quality-system.md) | Local checks, protected evaluation, and production promotion |
| [Build plan](docs/build-plan.md) | Ongoing product and engineering work |
| [Engineering principles](docs/engineering-principles.md) | Contributor standards and safety boundaries |
| [Documentation index](docs/README.md) | Further design notes and historical references |

Maintained by [Frank Yang](https://github.com/yyqfrank420).
