# agentsOnAir

## Stack

- **Monorepo**: Turborepo with pnpm
- **Web console**: Next.js App Router (TypeScript) with Tailwind CSS
- **Agent engine**: FastAPI (Python 3.12) with uv
- **Data & queue**: PostgreSQL 16, Redis, ARQ
- **Sandbox runtime**: E2B microVM sandboxes with Docker fallback

## Build approach

Tracer Bullet (prove the whole loop works end to end through every layer before broadening features)

## Commands

```bash
# Install dependencies
pnpm install && uv sync --directory apps/agent

# Run development servers
pnpm dev

# Build all workspaces
pnpm build

# Run all tests
pnpm test

# Typecheck and lint
pnpm typecheck && pnpm lint
```

## Specs

Stored in `docs/specs/`. Format: `docs/specs/NNNN-title.md`.

## Rules

- Code follows Clean Architecture with strict separation between domain, application, infrastructure, and presentation layers.
- Outer layers depend on inner layers, never the reverse. Domain logic has zero framework or external imports.
- Entities contain core business rules and enforce their own invariants as plain objects.
- Use cases orchestrate domain logic and call infrastructure interfaces via dependency inversion.
- Cross boundary communication uses DTOs or plain objects without leaking domain entities.
- Validate environment variables at startup and enforce strict types with no any.
- Use consistent error handling and structured API responses across endpoints.
- Document public APIs and maintain accessibility baseline on web UI components (WCAG AA).
- Colocate files by feature within each workspace.

## Tooling

- Linter and formatter: ESLint and Prettier for web, Ruff for Python.
- Pre commit checks: lint, format check, and typecheck before commit.
- Testing gate: unit and integration tests (Vitest and pytest) plus CI checks on push.

## Git

- integration: off

## Agent skills

- [clerk-nextjs-patterns](.agents/skills/clerk-nextjs-patterns/): `clerk/skills`, Next.js patterns for middleware, server actions, and caching with Clerk
- [fastapi-templates](.agents/skills/fastapi-templates/): `wshobson/agents`, FastAPI production async patterns, dependency injection, and error handling
- [nextjs-app-router-patterns](.agents/skills/nextjs-app-router-patterns/): `wshobson/agents`, Next.js 14+ App Router, Server Components, and streaming
- [tailwind-design-system](.agents/skills/tailwind-design-system/): `wshobson/agents`, Tailwind CSS design system tokens, components, and layout styling
MCP servers: github (recommended), postgresql (recommended)

## Context files

- [apps/web/AGENTS.md](apps/web/AGENTS.md) (Web console front end Next.js App Router)
- [apps/agent/AGENTS.md](apps/agent/AGENTS.md) (Autonomous agent engine FastAPI service)

_Drafted by /audit from the repo, worth a quick human pass. Edit freely: once a line stops matching this draft, later runs treat it as curated and will flag rather than overwrite it._
