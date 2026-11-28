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
- PostgreSQL migration and Drizzle schema definitions for `task_approvals`, append only `usage_events`, `org_monthly_usage`, and `task_runs.paused_seconds` (see spec 0008)
- Organization and repository guardrail policy endpoints (`GET /api/v1/organizations/guardrails`, `GET /api/v1/organizations/usage`, `GET /api/v1/repositories`, `GET /api/v1/repositories/{repo_id}/guardrails`, `PATCH /api/v1/repositories/{repo_id}/guardrails`) supporting repository level overrides (see spec 0008)
- Protected branch `fnmatchcase` glob validation across host GitHub publishing and sandbox `pre-push` hooks via system `core.hooksPath`, paired with post clone token stripping after `contents:read` checkouts (see spec 0008)
- Admin approval gate (`POST /api/v1/tasks/{task_id}/approvals/{approval_id}/decision`) pausing risky shell commands, sensitive path edits, force git operations, and oversized diffs via LangGraph interrupts and `task.approval_requested` SSE events (see spec 0008)
- Per call LLM token telemetry, ceiling integer cent cost accounting, `task.budget_updated` SSE events, and automatic halts on task cost, monthly organization spend, cycle count, or active runtime limits excluding paused wait time (see spec 0008)
- Sandbox network egress settings (`network_egress_mode`, `allowed_egress_domains`) and console views in `/settings`, `/repositories`, and `/tasks/[id]` for budgets, monthly spend, guardrail overrides, live dollar meters, and admin approval controls (see spec 0008)
- PostgreSQL migration and Drizzle ORM schemas for `review_rules` (with soft delete `deleted_at`), `review_rule_overrides`, `review_examples`, `review_finding_feedback`, `review_learned_preferences`, `pr_review_findings` (`rule_id`, `feedback_state`), and composite analytics indexes (see spec 0009)
- Organization and repository custom review rule and override REST endpoints (`/api/v1/organizations/review-rules`, `/api/v1/repositories/{repo_id}/review-rules`, `/api/v1/repositories/{repo_id}/review-rules/{rule_id}/override`) enforcing `org:admin` access, row locked 25 active rule caps, globstar path matching, and immutable `audit_logs` records (see spec 0009)
- Curated example pull request endpoints (`/api/v1/repositories/{repo_id}/review-examples`) verifying same repository ownership over GitHub HTTP, scrubbing credentials with `[REDACTED]`, extracting `modified_files`, and caching header preserving diff summaries within 1,500 tokens up to 5 examples per repository (see spec 0009)
- Dual channel finding feedback learning (`POST /api/v1/reviews/findings/{finding_id}/feedback` plus `pull_request_review_thread` and `pull_request_review_comment` webhooks gated by `OWNER`, `MEMBER`, or `COLLABORATOR` association and atomic `github_event_id` deduplication) advancing `review_learned_preferences` across `active`, `dampened`, and `suppressed` states with `org:admin` management endpoints (see spec 0009)
- Organization reviews list (`GET /api/v1/reviews`) and analytics overview endpoint (`GET /api/v1/analytics/overview`) computing PR review and autonomous task p50/p95 turnaround in milliseconds (excluding `paused_seconds`), finding acceptance rates, top triggered rules, and UTC daily cost breakdowns across `pr_review`, `forge`, and `reviewer` usage events (see spec 0009)
- Console pages and navigation for `/reviews` (finding `Accept` and `Dismiss` feedback controls with optional reason and team memory toggle), `/analytics` (custom SVG daily spend and turnaround charts with `7d`, `30d`, and `90d` and repository filters), `/settings` Organization Review Guidelines, and `/repositories` four tab drawer (`Guardrails`, `Rules & Overrides`, `Example PRs`, `Learned Preferences`) (see spec 0009)

### Changed
- Isolated GitHub pushes and pull request creation into `host_publish_node` inside the LangGraph workflow so write credentials stay outside sandbox workspaces (see spec 0008)
- Extended `PATCH /api/v1/organizations/settings` with bounded guardrail validation and `audit_logs` recording, and updated `POST /api/v1/tasks/{task_id}/respond` to reject approval pauses with `409 Conflict` (see spec 0008)
- Upgraded `ContextBudgetAllocator` to use `tiktoken` (`cl100k_base`) and reserve up to 6,000 tokens inside the 32,000 token Tier 1 budget for credential redacted, XML escaped `<custom_rules>`, `<team_preferences>`, and `<example_prs>` blocks across both `RunPRReviewUseCase` and `task_graph.py` `reviewer_node` (see spec 0009)
- Updated `CodeReviewAnalyzerNode` and `ReviewerCriticAgent` to validate returned `rule_id` values against injected active rules, filter `suppressed` patterns, and downgrade `dampened` patterns to `info` advisory findings before verdict resolution (see spec 0009)
- Updated `GitHubService` to perform real GitHub App JWT token exchange and HTTP reads for pull request metadata, diffs, and review comments, and extended `GitHubReviewPublisher.publish` to backfill `pr_review_findings.github_comment_id` after inline review submission (see spec 0009)
- Backfilled Spec 0005 `repositories.reviewSettings`, `pullRequestReviews`, and `prReviewFindings` definitions alongside Spec 0009 tables in `apps/web/src/db/schema.ts` (see spec 0009)

### Fixed
- Infinite re render loop in breadcrumb context hook by memoizing item comparisons and bailing out on stable content
- React hydration mismatch in sidebar collapse state by reading cookie values through useSyncExternalStore with server fallback
- Clerk v2 compact organization role normalization (`admin` to `org:admin`, `member` to `org:member`) during JWT verification so organization admins retain access
- Sandbox workspace clone initialization and diff capture handling pre initialized `.git` directories and staging untracked files with `git add -N` before generating diffs
