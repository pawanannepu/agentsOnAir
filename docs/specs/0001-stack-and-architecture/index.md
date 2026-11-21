# 0001. Stack and architecture

**Date**: 2026-11-21
**Status**: In Progress

## Summary

This decision defines the foundational technology stack and repository architecture for agentsOnAir. We adopt a monorepo structure with Next.js for the web console and Python FastAPI with LangGraph for the autonomous agent execution engine. Untrusted code execution runs inside isolated E2B hardware microVM sandboxes with a local Docker fallback, while PostgreSQL and Redis manage application state, checkpointing, and background queues. This foundation gives us fast developer velocity on the web front end alongside the rich AI ecosystem in Python, keeping the architecture clear and maintainable.

## Decision

**Chosen option**: Option 1: Polyglot monorepo with Next.js web console and Python FastAPI agent engine.

We adopt a Turborepo monorepo separating the Next.js web console from the Python FastAPI agent service, using E2B microVMs for sandboxed execution, PostgreSQL for persistence, and Redis for background queues.

**Implementation skills**: `nextjs-app-router-patterns` (`wshobson/agents`, `.agents/skills/nextjs-app-router-patterns/`) · `fastapi-templates` (`wshobson/agents`, `.agents/skills/fastapi-templates/`) · `clerk-nextjs-patterns` (`clerk/skills`, `.agents/skills/clerk-nextjs-patterns/`)

## Proposed stack

| Layer | Choice | Reason |
|---|---|---|
| Monorepo & build | Turborepo | Clean workspace separation for web console and Python agent engine |
| Web console | Next.js App Router (TypeScript) with Tailwind CSS | Fast server rendering, streaming agent views, and rich UI ecosystem |
| Agent API service | FastAPI (Python 3.12) | Native async performance, automatic OpenAPI documentation, and typed validation |
| Python package manager | uv | Subsecond package installation, lockfile resolution, and virtual environments |
| Real time streaming | Server Sent Events (SSE) via direct connection | Direct browser to FastAPI streaming avoids Vercel serverless function timeouts |
| Telemetry event bus | Redis Pub/Sub | Bridges live graph steps and terminal output from ARQ workers to SSE endpoints |
| Agent orchestrator | LangGraph (Python) | Resilient cyclical graphs for plan, code, test, and review iterations |
| Sandbox runtime | E2B microVM sandboxes with Docker fallback | Hardware isolated Firecracker microVMs with a local Docker provider for offline work |
| Primary database | PostgreSQL 16 | Relational ACID guarantees, JSONB flexibility, and state checkpointing |
| Database ownership | Single writer (`apps/agent`) | SQLAlchemy 2.0 and Alembic own migrations and all agent state table writes |
| Database access (Node.js) | Drizzle ORM (read only) | Type safe read queries for web console dashboards, generated from database schema |
| Task queue & broker | Redis with ARQ | Async Python worker queue with native coroutines, job timeouts, and heartbeat pings |
| Authentication | Clerk | Fast organization multi tenancy, GitHub OAuth, and session token verification |
| Code host integration | GitHub App with Octokit | Fine grained repository permissions, webhook delivery, and Checks API |
| Artifact storage | Cloudflare R2 / AWS S3 API | S3 compatible object storage with zero egress fees for run logs and diffs |
| Observability & traces | OpenTelemetry with Langfuse | Specialized LLM tracing, token cost accounting, and step level replays |
| Production hosting (Web) | Vercel | Global edge deployment, instant preview environments, and Next.js optimization |
| Production hosting (Agent) | Fly.io or AWS ECS | Long running container workers for FastAPI services and Redis queues |

## Architectural contracts and boundaries

### Client to backend communication and authentication
Next.js serves the web application shell and standard dashboard views. When a developer starts or inspects an active task, the browser opens an EventSource connection directly to FastAPI (`api.agentsonair.com/api/v1/tasks/{id}/events`). This direct path avoids Vercel serverless function timeouts during long running agent runs. Authentication is verified through Clerk JWT tokens validated against Clerk JWKS public keys in FastAPI using an `HTTPBearer` security dependency. Inter service calls between Next.js server actions and FastAPI use a shared internal service secret.

### Database schema ownership and dual ORM pattern
`apps/agent` is the sole schema owner and writer for task runs, agent states, sandbox metadata, and audit logs. Schema changes are managed through Alembic migrations. `apps/web` connects to the same PostgreSQL database using Drizzle ORM in a read only mode to render dashboard views without duplicate write logic. Schema definitions for Drizzle are automatically refreshed using `drizzle-kit introspect` during continuous integration.

### Telemetry pipeline and streaming bus
LangGraph runs inside background ARQ worker processes. As graph nodes execute, custom callbacks publish event payloads to a Redis Pub/Sub channel (`task:{id}:stream`). The FastAPI SSE endpoint subscribes to this Redis channel asynchronously and pushes events to the browser client.

### Sandbox lifecycle and local development parity
Each `TaskRun` binds 1:1 with an isolated sandbox session with an explicit 10 minute timeout. An hourly background reaper checks PostgreSQL for abandoned tasks and cleans up orphaned microVM sessions. A `SandboxProvider` abstraction allows developers to toggle between `E2BSandboxProvider` in cloud staging and production and `DockerSandboxProvider` during local offline development.

### Task orchestration, checkpoints, and cancellation
ARQ acts as the job dispatcher carrying `task_id` arguments to worker pools. LangGraph uses `AsyncPostgresSaver` in PostgreSQL as the single source of truth for graph history, state checkpoints, and recovery. When a user pauses or cancels a task from the web console, a cancellation flag is written to Redis (`task:{id}:abort`), which graph nodes check before invoking tools or sandbox commands.

### Monorepo build integration
Python package management in `apps/agent` uses `uv`. Root `package.json` scripts execute `uv run` commands so Turborepo can pipeline linting, type checking with pyright, and pytest runs alongside Next.js tasks, with lockfiles tracked in `turbo.json` inputs.

## Consequences

**Positive**:
* Best in class tools for each domain: modern React on the front end, leading agent frameworks in Python on the backend.
* Direct browser to FastAPI streaming avoids intermediate gateway timeouts during extended multi minute agent tasks.
* Single writer database pattern prevents dual ORM schema desynchronization and split brain business logic.
* Hardware isolated sandboxes prevent prompt injection escapes and malicious code from compromising host infrastructure.
* Stateful checkpointing allows interrupted or failed agent tasks to resume seamlessly without losing work.
* Clear boundary between web console and backend workers allows independent scaling and isolated failure domains.

**Negative / tradeoffs**:
* Polyglot development requires developers to install both Node.js and Python with `uv` locally.
* Direct browser to API communication requires configuring CORS policies and public API subdomains.
* Running cloud microVMs introduces an external runtime dependency and variable cost per sandbox run.

**Neutral**:
* Local development will use Docker Compose for local PostgreSQL, Redis, and MinIO storage services.
* Database schema changes will be driven primarily through Alembic migrations in the Python workspace.

## Follow-up

* [x] Set up Turborepo workspace configuration with `apps/web` and `apps/agent` directory structure using `uv`.
* [x] Create Docker Compose configuration for local PostgreSQL, Redis, and MinIO development services.
* [ ] Implement Clerk JWKS JWT validation dependency in FastAPI.
* [ ] Create `SandboxProvider` protocol with E2B and local Docker implementations.
* [ ] Configure GitHub App credentials and webhook signature verification in the agent service.
* [ ] Configure GitHub MCP and PostgreSQL MCP as development servers when live database and repository inspection are required.
* [ ] Capture project coding conventions and installed skill rules into root `AGENTS.md` via `/audit`.
