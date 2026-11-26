# Changelog

All notable changes to this project are documented in this file.
The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Added
- Foundational polyglot monorepo scaffold using Turborepo and pnpm workspaces (see spec 0001)
- Web console in apps/web built with Next.js 16 App Router, React 19, Tailwind CSS, and Vitest test harness
- Agent engine service in apps/agent built with Python FastAPI and pytest test suite managed by uv
- Local development service definitions in docker-compose.yml for PostgreSQL 16 persistence and Redis 7 task broker
- Monorepo architecture specification defining execution isolation, single writer database ownership, and streaming contracts (see spec 0001)
- PostgreSQL database schema with UUIDv7 primary keys for tenant organizations, repositories, credentials, tasks, task runs, sandbox runs, and immutable audit logs (see spec 0002)
- AES 256 GCM authenticated encryption for repository tokens and provider credentials with unique nonces and tampering protection
- Clean Architecture domain entities and async SQLAlchemy repositories with tenant isolation, run locking, and optimistic concurrency control on checkpoint state
- Reversible Alembic migration featuring partial unique indexes for repository soft delete and PostgreSQL database triggers enforcing append only audit log immutability
- Drizzle ORM read schemas in the web console matching the database schema for cross workspace type safety
- Dark theme design system built with Tailwind CSS v4 CSS first theme tokens in OKLCH color space for developer console UI (see spec 0003)
- Accessible component library with Class Variance Authority and Radix UI primitives including Button, Badge, Card, Dialog, Tabs, Table, Input, and Select
- High performance virtualized terminal log viewer (TerminalViewer) featuring ANSI color rendering, auto scroll pinning, search filtering, and clean plain text clipboard copy
- Global command palette (CommandDialog) with keyboard shortcut support (Cmd+K or Ctrl+K), quick navigation across tasks, repositories, and settings, and local storage recent task caching
- Console application shell with collapsible sidebar navigation, persistent cookie state, dynamic breadcrumb header, and route views for tasks, task details, repositories, and workspace settings
- Vitest component and view integration test suite with 44 tests covering design primitives, keyboard navigation, and breadcrumb state stability
- Cyclical autonomous engineering and review engine pairing Forge coder with Reviewer critic for bounded test and repair cycles (see spec 0004)
- GitHub webhook ingestion pipeline verifying HMAC SHA256 signatures and routing issue triggers with duplicate task filtering
- Review iterations schema and Alembic migration recording structured critic findings, diff snapshots, and pull request tracking columns
- Sandbox workspace runner executing baseline tests on untouched base branches before agent edits to detect preexisting test failures
- Automated pull request creation on GitHub with extracted patches, changelog summaries, and immutable audit log trails upon reviewer approval
- Live task streaming endpoint over Server Sent Events backed by capped Redis Streams with `Last-Event-ID` cursor replay and keep alive pings (see spec 0006)
- LangGraph human in the loop clarification interrupts with PostgreSQL checkpoint persistence, sandbox timeout extension, ARQ task resumption, and a 15 minute expiration watchdog
- Authenticated task collaboration endpoints for developer steering guidance, optimistic concurrency clarification replies, and task cancellation with audit logging
- Transcript archival storing gzip compressed terminal logs and structured stream events in PostgreSQL alongside an in flight transcript fallback endpoint
- Console task detail inspector and `useTaskStream` hook displaying live ANSI terminal logs, phase filtered step progress, clarification banners, and steering controls

### Fixed
- Infinite re render loop in breadcrumb context hook by memoizing item comparisons and bailing out on stable content
- React hydration mismatch in sidebar collapse state by reading cookie values through useSyncExternalStore with server fallback
