# 0007. Clerk sign in, route protection, and PostgreSQL organization sync

**Date**: 2026-11-26
**Status**: In Progress

## Summary

This decision defines how users sign in to the web console, how console pages and backend endpoints protect tenant routes, and how Clerk organizations stay synchronized with PostgreSQL. We use lightweight Next.js edge checks paired with server page guards wrapped in Suspense boundaries, and render prebuilt Clerk sign in, sign up, and organization switcher components styled to match our dark theme. On the backend, FastAPI receives Clerk organization events through a verified Svix webhook (a signed delivery service that Clerk uses for webhooks) and performs atomic fallback syncing via the Clerk Backend API in short lived transactions so newly created organizations work immediately without blocking live streams.

## Requirements

**User stories**:
- As a developer, I want to sign in and sign up using a clean, dark themed authentication flow so that I can access my team's engineering console securely.
- As an organization member, I want to switch between my Clerk organizations from the sidebar without seeing stale data or UUID errors so that tenant boundaries stay clear.
- As a security engineer, I want every organization creation, update, and deletion in Clerk mirrored accurately in PostgreSQL with immutable audit logging and strict role checks so that workspace access remains least privilege.

**Acceptance criteria**:
- **AC-1**: All console routes (`/`, `/tasks`, `/tasks/[id]`, `/repositories`, `/settings`) require an authenticated Clerk session enforced via `apps/web/src/proxy.ts` edge checks (redirecting unauthenticated requests with HTTP `307`) and per page server `requireConsoleOrg()` guards inside `<Suspense>` paired with `loading.tsx`, while `/sign-in`, `/sign-up`, and `GET /api/health` (`{"status": "ok"}`) remain publicly reachable. In `NODE_ENV=production`, missing or placeholder Clerk keys fail closed with HTTP `500` at request time (never breaking `next build`), while non production environments preserve the placeholder bypass for local tests and Vitest.
- **AC-2**: Visiting `/sign-in` or `/sign-up` renders Clerk prebuilt `<SignIn />` and `<SignUp />` components inside a centered `(auth)` shell that hides `Sidebar` and `Header`, styled to match the existing zinc dark tokens, wrapped in `<Suspense>`, delegating `redirect_url` and pending `choose-organization` task redirects directly to Clerk with `fallbackRedirectUrl="/tasks"`.
- **AC-3**: Signed in users without an active `orgId` on console routes are redirected to `(auth)/onboarding/organization`, guarded by `await auth()` (redirecting `!userId` to `/sign-in` and active `orgId` to `/tasks`), rendering `<TaskChooseOrganization redirectUrlComplete="/tasks" />` when `sessionStatus === "pending"` and `<OrganizationList hidePersonal />` otherwise. `Sidebar` renders `<OrganizationSwitcher hidePersonal />` below the brand header and `<UserButton />` in the footer, and selecting or creating an organization navigates to `/tasks`.
- **AC-4**: Any active organization member (`org:member` or `org:admin`) can view tasks and repositories, while `/settings`, `PATCH /api/v1/organizations/settings`, and organization admin mutations require `org:admin` (`has({ role: 'org:admin' })` in `apps/web` and `require_org_admin` checking `caller.org_role == 'org:admin'` in `apps/agent`). All task and review endpoints in `apps/agent` enforce `get_current_clerk_user` and tenant resolution via `authorize_task_org` without expecting Clerk's `org_...` string in `?org_id=`.
- **AC-5**: `POST /api/v1/webhooks/clerk` verifies incoming Svix headers (`svix-id`, `svix-timestamp`, `svix-signature`) using the `svix` Python SDK and `CLERK_WEBHOOK_SIGNING_SECRET` (returning `503` if unconfigured, `400` on missing headers or malformed payloads, `401` on invalid or expired signatures), handles `organization.created`, `organization.updated` (updating active rows only so delayed updates never resurrect soft deleted rows), and `organization.deleted` (idempotently setting `deleted_at` while keeping child rows and `audit_logs`) using atomic `INSERT ... ON CONFLICT (clerk_org_id) DO UPDATE`, and records `audit_logs` on actual state changes.
- **AC-6**: When `authorize_task_org` or `POST /api/v1/organizations/sync` encounters a verified Clerk JWT whose `clerk_org_id` is absent in `organizations`, FastAPI runs `SyncOrganizationUseCase` inside an isolated short lived committed transaction (never inside the long lived SSE `get_db()` session), fetching `name` and `slug` from the Clerk Backend API (`CLERK_SECRET_KEY`, `5.0s` timeout), upserting atomically, recording `audit_logs` (`actor_type="user"`), and returning HTTP `403` (`{"code": "org_inactive", ...}`) when Clerk returns `404` or `CLERK_SECRET_KEY` is unconfigured.
- **AC-7**: When FastAPI returns `403` with `code: "org_inactive"` or `"org_missing"`, a global recovery prompt inside `ConsoleLayout` renders `<OrganizationList hidePersonal />` with `session.reload()` instead of looping redirects, existing `"use client"` console views stay importable for `console-views.test.tsx`, and `pnpm --filter web build` succeeds with `cacheComponents: true`.

## Decision

**Chosen option**: Option 1: Edge plus per page server guards with atomic dual webhook and isolated lazy Backend API sync.

We adopt edge unauthenticated redirects in `apps/web/src/proxy.ts` paired with per page `requireConsoleOrg()` server guards, `(auth)` and `(console)` route groups, prebuilt Clerk UI components styled via shared `ClerkProvider` zinc theme tokens, and a dual FastAPI sync pipeline combining `svix` verified webhooks with isolated short lived Clerk Backend API fallback transactions.

**Implementation skills**: `clerk-nextjs-patterns` (`clerk/skills`, `.agents/skills/clerk-nextjs-patterns/`) · `clerk-orgs` (`clerk/skills`, `.agents/skills/clerk-orgs/`) · `clerk-webhooks` (`clerk/skills`, `.agents/skills/clerk-webhooks/`) · `nextjs-app-router-patterns` (`wshobson/agents`, `.agents/skills/nextjs-app-router-patterns/`) · `tailwind-design-system` (`wshobson/agents`, `.agents/skills/tailwind-design-system/`) · `fastapi-templates` (`wshobson/agents`, `.agents/skills/fastapi-templates/`)

## Rationale

Reasoning and options: see [rationale.md](rationale.md).

## Feature design

**Data model sketch**:
Reuses the existing PostgreSQL tables from spec `0002` with zero Alembic migrations needed:
- `organizations`: `id` (`UUID`, primary key, UUIDv7), `clerk_org_id` (`String(255)`, unique, not null, indexed), `name` (`String(255)`, not null), `slug` (`String(255)`, not null, partial unique index `uq_organizations_slug_active` where `deleted_at IS NULL`), `github_installation_id` (`BigInteger`, nullable), `settings` (`JSONB`, not null, default `{}`), `created_at` (`DateTime`, not null), `updated_at` (`DateTime`, not null), `deleted_at` (`DateTime`, nullable).
- `audit_logs`: `id` (`UUID`, primary key, UUIDv7), `org_id` (`UUID`, foreign key to `organizations.id` with `ON DELETE RESTRICT`, not null), `actor_type` (`String(50)`, not null), `actor_id` (`String(255)`, not null), `action` (`String(100)`, not null), `target_type` (`String(50)`, not null), `target_id` (`UUID`, not null), `payload_before` (`JSONB`, nullable), `payload_after` (`JSONB`, nullable), `ip_address` (`String(45)`, nullable), `created_at` (`DateTime`, not null).
- Relationships: `organizations` `1:N` `audit_logs`, plus existing `1:N` tenant relationships to `repositories`, `credentials`, `tasks`, `task_runs`, `sandbox_runs`, `task_interventions`, and `task_transcripts`.

**State transitions**:
- Organization record in PostgreSQL: `absent -> active` (on `organization.created` webhook or verified Clerk Backend API lazy sync) -> `active` (`organization.updated` updates active rows where `deleted_at IS NULL`, ignoring soft deleted rows) -> `soft_deleted` (`deleted_at` set on `organization.deleted`). Only `organization.created` or a live `200` response from Clerk Backend API can reactivate a soft deleted `clerk_org_id`.
- Web console session state: `unauthenticated` (HTTP `307` redirect to `/sign-in`) -> `authenticated_no_org` (`sessionStatus === "pending"` or missing `orgId`, routed to `(auth)/onboarding/organization`) -> `authenticated_active_org` (console access; `/settings` gated by `org:admin`) -> `org_inactive_or_missing` (global `ConsoleLayout` recovery modal/banner on FastAPI `403` `org_inactive` / `org_missing` to select another organization and call `session.reload()`).

**API surface**:
| Endpoint | Method | Key inputs | Key outputs | Auth | Key errors |
|---|---|---|---|---|---|
| `/api/v1/webhooks/clerk` | POST | Raw JSON body, `svix-id`, `svix-timestamp`, `svix-signature` | `{"status": "processed" \| "ignored", "org_id": "uuid \| null"}` | Svix signature (`CLERK_WEBHOOK_SIGNING_SECRET`) | `400` malformed payload, `401` invalid signature, `409` active slug conflict, `503` unconfigured secret |
| `/api/v1/organizations/sync` | POST | Verified Clerk session JWT (`Authorization` bearer or `__session` cookie) | `{"id", "clerk_org_id", "name", "slug"}` | Clerk JWT with active `clerk_org_id` | `401` invalid JWT, `403` `org_inactive` or missing `clerk_org_id`, `502` Clerk upstream failure |
| `/api/v1/organizations/settings` | PATCH | JSON `{sandbox_provider, timeout_minutes, ...}` | `{"id", "settings"}` | Clerk JWT + `require_org_admin` (`org:admin`) | `401` invalid JWT, `403` `org_admin_required` or `org_inactive`, `422` validation error |
| `/api/health` (Next.js) | GET | None | `{"status": "ok"}` | Public | None (`200` always, never reads Clerk config) |
| `/sign-in/[[...sign-in]]` | GET | Optional `redirect_url` query param | Rendered `<SignIn />` inside `(auth)` shell | Public | Handled by Clerk `<SignIn />` (`fallbackRedirectUrl="/tasks"`) |
| `/sign-up/[[...sign-up]]` | GET | Optional `redirect_url` query param | Rendered `<SignUp />` inside `(auth)` shell | Public | Handled by Clerk `<SignUp />` (`fallbackRedirectUrl="/tasks"`) |
| `/onboarding/organization` | GET | Clerk session cookie | `<TaskChooseOrganization />` (if pending) or `<OrganizationList hidePersonal />` | `await auth()` (`userId` required) | Redirects `!userId` to `/sign-in`, active `orgId` to `/tasks` |

**Value sourcing**:
| Action | Value produced / displayed | Source |
|---|---|---|
| Webhook org upsert (`organization.created`, `organization.updated`) | `clerk_org_id`, `name`, `slug` | Webhook JSON `data.id`, `data.name`, `data.slug` (fallback `f"org-{clerk_org_id.lower()}"` if `slug` is null) |
| Webhook audit log (`action`, `target_type`, `actor`, `payload`) | `action`, `target_type`, `actor_type`, `actor_id`, `payload_before`, `payload_after` | `"organization.created" \| "organization.updated" \| "organization.deleted"`, `"organization"`, `"clerk_webhook"`, `data.created_by` (fallback `"clerk_webhook"`), `{clerk_org_id, name, slug, deleted_at}` snapshots (skipped on no op duplicates) |
| Webhook org soft delete (`organization.deleted`) | `clerk_org_id`, `deleted_at`, response `org_id` | Webhook `data.id`; current UTC timestamp; internal `organizations.id` UUID (or `null` when `"ignored"`) |
| Lazy sync & `/api/v1/organizations/sync` | `clerk_org_id`, `name`, `slug` | `clerk_org_id` from verified Clerk JWT (`caller.clerk_org_id`); `name` and `slug` from Clerk Backend API `GET /v1/organizations/{clerk_org_id}` (`CLERK_SECRET_KEY`) |
| Lazy sync audit log | `action`, `actor_type`, `actor_id` | `"organization.synced"`, `"user"`, `caller.user_id` from verified Clerk JWT |
| Task and review endpoint tenant resolution | Internal `organizations.id` UUID | Resolved inside `authorize_task_org` from `caller.clerk_org_id` (web omits Clerk `org_...` from `?org_id=`) |
| Structured `403` error discrimination | `detail: {"code", "message"}` | FastAPI auth dependencies (`org_missing`, `org_inactive`, `org_mismatch`, `org_admin_required`) |
| Console `OrganizationSwitcher`, `UserButton`, and recovery UI | Active org name, avatar, role, user profile | `@clerk/nextjs` client hooks (`useOrganization`, `useUser`, `useClerk`) |
| Settings admin check | `isAdmin` / `orgRole` | Web: `auth().has({ role: 'org:admin' })`; FastAPI: `caller.org_role == 'org:admin'` |

**Key invariants**:
- Every active `organizations` row has a unique non empty `clerk_org_id` and a unique `slug` across rows where `deleted_at IS NULL`; upserts execute atomically via PostgreSQL `INSERT ... ON CONFLICT (clerk_org_id) DO UPDATE`.
- Webhook handlers and lazy sync never hard delete `organizations` rows so `audit_logs` foreign keys (`ON DELETE RESTRICT`) remain valid, and delayed `organization.updated` events never clear `deleted_at`.
- Lazy sync always runs inside its own short lived committed session (`async_session_factory()`) so SSE endpoints (`GET /api/v1/tasks/{task_id}/events`) never hold uncommitted `organizations` locks.
- `POST /api/v1/webhooks/clerk` verifies raw request body bytes against Svix headers before JSON parsing or DB writes, and never calls Clerk JWT auth.
- In `NODE_ENV=production`, missing or placeholder Clerk keys never throw during `next build` imports; instead `proxy.ts` and `requireConsoleOrg()` fail closed at request time with HTTP `500`.
- Every server `auth()` and `<Show>` call in `apps/web` runs inside a `<Suspense>` boundary, and gated `(console)` pages provide `loading.tsx` plus separable client view components (`TasksView`, `RepositoriesView`, `SettingsView`) for unit tests.

**Security model**:
- Unauthenticated visitors can reach only `/sign-in`, `/sign-up`, `/api/health`, and `POST /api/v1/webhooks/clerk`; all `(console)` pages enforce edge redirects in `proxy.ts` and per page `requireConsoleOrg()`.
- Every console session requires an active Clerk organization (`Membership required` plus `hidePersonal` on `<OrganizationSwitcher />` and `<OrganizationList />`), matching FastAPI tenant isolation on `organizations.id`.
- `org:member` and `org:admin` roles can view and operate `/tasks` and `/repositories`; `/settings` and `PATCH /api/v1/organizations/settings` enforce `org:admin` (`has({ role: 'org:admin' })` on Next.js and `require_org_admin` checking `caller.org_role == 'org:admin'` in FastAPI, never checking `org:sys_*` permissions directly on the server).
- Webhook authenticity uses `svix.webhooks.Webhook(CLERK_WEBHOOK_SIGNING_SECRET).verify(payload_bytes, headers)` with Svix's 5 minute timestamp replay window.

**Configuration required**:
- `NEXT_PUBLIC_CLERK_PUBLISHABLE_KEY`: Clerk frontend publishable key in `apps/web` (existing, required in production).
- `CLERK_SECRET_KEY`: Clerk Backend API secret key in both `apps/web` and `apps/agent` (for `GET /v1/organizations/{id}`).
- `NEXT_PUBLIC_CLERK_SIGN_IN_URL`: Set to `/sign-in` in `apps/web`.
- `NEXT_PUBLIC_CLERK_SIGN_UP_URL`: Set to `/sign-up` in `apps/web`.
- `NEXT_PUBLIC_CLERK_SIGN_IN_FALLBACK_REDIRECT_URL`: Set to `/tasks` in `apps/web`.
- `NEXT_PUBLIC_CLERK_SIGN_UP_FALLBACK_REDIRECT_URL`: Set to `/tasks` in `apps/web`.
- `CLERK_WEBHOOK_SIGNING_SECRET`: Svix webhook signing secret (`whsec_...`) in `apps/agent` for `POST /api/v1/webhooks/clerk`.

**Critical test scenarios**:
- Happy path: Unauthenticated request to `/tasks` receives `307` to `/sign-in`; signing in with pending `choose-organization` routes to `/onboarding/organization` without deadlocking; creating an org syncs atomically to PostgreSQL via webhook or isolated lazy Backend API sync and loads `/tasks`; switching orgs navigates to `/tasks` without passing `org_...` into `?org_id=`, verifies **AC-1**, **AC-2**, **AC-3**, **AC-5**, **AC-6**.
- Failure case: Replayed or tampered `svix-signature` on `POST /api/v1/webhooks/clerk` returns HTTP `401` (or `503` when secret unset); delayed `organization.updated` does not resurrect a soft deleted org; Clerk Backend API `404` maps to `403` `org_inactive` and triggers the `ConsoleLayout` recovery prompt with `<OrganizationList hidePersonal />` and `session.reload()`, verifies **AC-5**, **AC-6**, **AC-7**.
- Auth and permission: Member with `org:member` role receives an access denied view on `/settings` and HTTP `403` (`org_admin_required`) on `PATCH /api/v1/organizations/settings`; production request with placeholder Clerk keys fails closed with `500` while `/api/health` returns `200`, verifies **AC-1**, **AC-4**.

## Build plan

1. [x] Stand up the core auth structure across both workspaces: add `svix` and promote `httpx` to main dependencies in `apps/agent/pyproject.toml`, add `CLERK_WEBHOOK_SIGNING_SECRET` to `apps/agent/app/core/config.py`, add `apps/web/src/app/api/health/route.ts`, update `apps/web/src/lib/clerk-config.ts` with non throwing production fail closed request helpers, organize `apps/web/src/app/` into `(auth)` and `(console)` route groups with shared dark theme `clerkAppearance` and `taskUrls` in `apps/web/src/app/layout.tsx`, and wire edge unauthenticated redirects in `apps/web/src/proxy.ts`, satisfies **AC-1**, **AC-2**, **AC-3**.
2. [x] Build the backend atomic organization sync core and Clerk webhook endpoint: update `SqlAlchemyOrganizationRepository.create_or_update` to use PostgreSQL `INSERT ... ON CONFLICT (clerk_org_id) DO UPDATE` (preserving soft deletion against stale updates), add `soft_delete_by_clerk_id`, implement `ClerkOrganizationGateway` (`httpx` Backend API client with `5.0s` timeout and `404` mapping) and `SyncOrganizationUseCase` with `audit_logs` recording, and mount `POST /api/v1/webhooks/clerk` using `svix` verification, satisfies **AC-5**.
3. [x] Wire isolated lazy fallback sync, explicit sync, settings persistence, and role guards in FastAPI: run `SyncOrganizationUseCase` in an isolated short lived `async_session_factory()` transaction inside `authorize_task_org` and `POST /api/v1/organizations/sync`, return structured `403` error codes (`org_missing`, `org_inactive`, `org_mismatch`, `org_admin_required`), enforce `get_current_clerk_user` + `authorize_task_org` across task/review endpoints, and add `PATCH /api/v1/organizations/settings` protected by `require_org_admin`, satisfies **AC-4**, **AC-6**.
4. [x] Implement the console authentication pages, organization switcher, role gates, and `403` recovery UI: create `(auth)/sign-in/[[...sign-in]]`, `(auth)/sign-up/[[...sign-up]]`, and `(auth)/onboarding/organization` (`await auth()` guard + `<TaskChooseOrganization />` / `<OrganizationList hidePersonal />`) wrapped in `<Suspense>`, extract client view components (`TasksView`, `RepositoriesView`, `SettingsView`) behind Server Component wrappers using `requireConsoleOrg()` + `loading.tsx`, remove `org_...` `?org_id=` query passing in `tasks/[id]/`, add `<OrganizationSwitcher hidePersonal />` and `<UserButton />` to `Sidebar` with `/tasks` navigation on switch, gate `/settings` with `has({ role: 'org:admin' })`, and mount the `org_inactive` / `org_missing` recovery prompt inside `ConsoleLayout`, satisfies **AC-1**, **AC-2**, **AC-3**, **AC-4**, **AC-7**.
5. [x] Run verification and automated test suites across both apps: add pytest unit and integration tests for Svix signature validation, concurrent atomic upserts, out of order webhook non resurrection, isolated lazy sync, Clerk BAPI `404` -> `403` mapping, and `require_org_admin`; add Vitest tests for `requireConsoleOrg()`, `console-views.test.tsx` compatibility, `(auth)` vs `(console)` shells, and production fail closed guards; run `pnpm --filter web build` with `cacheComponents: true` and `partialPrefetching: true` to confirm zero prerender errors, satisfies **AC-1**, **AC-2**, **AC-3**, **AC-4**, **AC-5**, **AC-6**, **AC-7**.

## Consequences

**Positive**:
- Tenant isolation between Next.js and FastAPI aligns under one internal `organizations.id` UUID resolved from the verified Clerk JWT, eliminating `422` UUID mismatches and personal account leaks.
- Atomic `ON CONFLICT` upserts and isolated short lived lazy sync transactions eliminate onboarding race conditions and SSE lock contention while keeping PostgreSQL up to date on renames and deletions.
- Reusing existing `organizations` and `audit_logs` tables avoids any schema migration and preserves immutable compliance history.

**Negative / tradeoffs**:
- FastAPI (`apps/agent`) now requires `CLERK_SECRET_KEY` and outbound reachability to `api.clerk.com` on rare lazy sync cache misses.
- Protecting `GET /api/v1/tasks/{task_id}` and `POST /api/v1/tasks` with `get_current_clerk_user` requires updating existing unauthenticated FastAPI task tests to pass a test Clerk JWT fixture.

**Neutral**:
- Organizations must be enabled in Clerk Dashboard with `Membership required` mode, and the Clerk webhook endpoint must subscribe to `organization.*` events.
- Existing mock task and repository view components remain intact for Vitest and non production placeholder previews.

## Follow-up

- [ ] Capture `clerk-orgs` conventions in `apps/web/AGENTS.md` and `clerk-webhooks` conventions in `apps/agent/AGENTS.md` (area specific context rather than root `AGENTS.md`), and note the new `(auth)` and `(console)` route groups in `apps/web/AGENTS.md` once built.
- [ ] Optional MCP servers skipped for now: consider connecting the **Clerk MCP server** (for live project and org inspection) or the **Svix MCP server** (`svix-dashboard`, for inspecting webhook deliveries and test payloads) in your MCP settings when wiring live Clerk keys.
- [ ] Configure Clerk Dashboard before live testing: enable Organizations in `Membership required` mode, add `/api/v1/webhooks/clerk` subscribing to `organization.created`, `organization.updated`, and `organization.deleted`, and populate `.env` / `.env.local` values documented in Configuration required.
