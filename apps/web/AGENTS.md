<!-- BEGIN:nextjs-agent-rules -->

## This is NOT the Next.js you know

This version has breaking changes — APIs, conventions, and file structure may all differ from your training data. Read the relevant guide in `node_modules/next/dist/docs/` (resolved from this file's directory; in monorepos the `next` package may not be visible from the repo root) before writing any code. Heed deprecation notices.

This block is written and re-added by `next dev` — verify at `node_modules/next/dist/server/lib/generate-agent-files.js`. Removing it from a diff only re-creates the uncommitted change; committing it with your work keeps the tree clean.

<!-- END:nextjs-agent-rules -->

# Web Console

## Overview

Web console user interface for agentsOnAir built with Next.js App Router and Tailwind CSS. It provides live streaming views of autonomous agent task runs, sandbox logs, and developer settings.

## Key files

| File | Owns |
|---|---|
| `src/app/layout.tsx` | Root HTML shell, global typography, and shared providers |
| `src/app/page.tsx` | Landing dashboard view with real time service status |
| `src/app/globals.css` | Tailwind CSS configuration and global styling tokens |
| `tests/page.test.tsx` | Front end component tests using React Testing Library and Vitest |

## Commands

```bash
# Run local Next.js development server
pnpm --filter web dev

# Build production bundle
pnpm --filter web build

# Run component test suite
pnpm --filter web test

# Typecheck and lint
pnpm --filter web typecheck
pnpm --filter web lint
```

## Conventions

- Inherits root rules from [AGENTS.md](../../AGENTS.md).
- React Server Components by default; mark client components with `use client` only when interactivity or browser state is required.
- Connect directly to the FastAPI Server Sent Events endpoint for live task streaming to avoid serverless function timeouts.
- Read only database access: query PostgreSQL via Drizzle ORM for read dashboards; all writes route through the agent service.
- Follow WCAG AA accessibility standards with accessible labels, keyboard focus states, and semantic HTML elements.

## Gotchas

- In Next.js 16, route parameters and search parameters in server components are asynchronous promises that must be awaited.
- Direct EventSource connections from the browser to the API server require proper CORS configuration on FastAPI.

## Agent skills

- [clerk-nextjs-patterns](../../.agents/skills/clerk-nextjs-patterns/): `clerk/skills`, Next.js patterns for middleware, server actions, and caching with Clerk
- [nextjs-app-router-patterns](../../.agents/skills/nextjs-app-router-patterns/): `wshobson/agents`, Next.js 14+ App Router, Server Components, and streaming
- [tailwind-design-system](../../.agents/skills/tailwind-design-system/): `wshobson/agents`, Tailwind CSS design system tokens, components, and layout styling

## Related specs

- [0001 Stack and architecture](../../docs/specs/0001-stack-and-architecture/index.md)

_Drafted by /audit from the repo, worth a quick human pass. Edit freely: once a line stops matching this draft, later runs treat it as curated and will flag rather than overwrite it._
