# Agent Service

## Overview

Autonomous agent execution engine for agentsOnAir. It runs cyclical LangGraph workflows in background workers, manages sandbox execution in E2B microVMs, and owns database migrations as the single database writer.

## Key files

| File | Owns |
|---|---|
| `app/main.py` | FastAPI application factory, middleware, and route mounting |
| `app/core/config.py` | Environment variable validation and runtime configuration |
| `tests/test_health.py` | Service health checks and API integration test suite |

## Commands

```bash
# Run local API server
pnpm --filter agent dev
# Direct uv command: uv run uvicorn app.main:app --reload --port 8000

# Run test suite
pnpm --filter agent test
# Direct uv command: uv run pytest

# Typecheck and lint
pnpm --filter agent typecheck
pnpm --filter agent lint
```

## Conventions

- Inherits root rules from [AGENTS.md](../../AGENTS.md).
- Sole database schema owner: all migrations and writes belong to this service.
- Use native async coroutines for all I/O, database access, and HTTP calls.
- Define request and response contracts with typed Pydantic models.
- Validate all environment variables during startup in `app/core/config.py`.

## Gotchas

- Background workers stream execution logs to Redis Pub/Sub channels before FastAPI pushes them to browser clients via Server Sent Events.
- E2B microVM sandboxes require explicit lifecycle cleanup to prevent orphaned resources.

## Agent skills

- [fastapi-templates](../../.agents/skills/fastapi-templates/): `wshobson/agents`, FastAPI production async patterns, dependency injection, and error handling

## Related specs

- [0001 Stack and architecture](../../docs/specs/0001-stack-and-architecture/index.md)

_Drafted by /audit from the repo, worth a quick human pass. Edit freely: once a line stops matching this draft, later runs treat it as curated and will flag rather than overwrite it._
