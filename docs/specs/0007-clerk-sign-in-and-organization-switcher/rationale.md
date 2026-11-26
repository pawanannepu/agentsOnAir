# 0007. Rationale: Clerk sign in, route protection, and PostgreSQL organization sync

## Context

`agentsOnAir` is a multi tenant platform where every repository, credential, task, and audit log in PostgreSQL belongs to an organization keyed by `clerk_org_id`. In earlier foundations, we installed `@clerk/nextjs` in `apps/web`, added bare `clerkMiddleware()` in `apps/web/src/proxy.ts`, added JWT verification (`verify_clerk_jwt`) and tenant authorization (`authorize_task_org`) in `apps/agent`, and created the `organizations` and `audit_logs` tables in PostgreSQL.

However, the console currently leaves every route open without redirecting unauthenticated visitors, has no sign in or sign up pages, has no workspace switcher in `Sidebar`, and passes Clerk's `org_...` string into FastAPI query parameters that expect an internal PostgreSQL `UUID`. Meanwhile, `apps/agent` has no endpoint syncing Clerk organizations into PostgreSQL, and `authorize_task_org` rejects requests that lack a matching active row in `organizations`.

Three technical constraints shape this design. First, `apps/web` runs Next.js 16.4.6 with `cacheComponents: true` and `partialPrefetching: true`, which fail production builds when uncached auth reads occur outside `<Suspense>` and leak outer layout shells if guards sit only in `layout.tsx`. Second, in `@clerk/nextjs` v7 with `Membership required` mode enabled, users without an organization have `sessionStatus === "pending"`, causing `auth.protect()` to redirect back to `/sign-in` if applied to the organization onboarding route. Third, Clerk webhooks are eventually consistent and out of order, while FastAPI Server Sent Events endpoints hold `get_db()` open across the entire stream lifetime.

## Options considered

### Option 1: Edge plus per page server guards with atomic dual webhook and isolated lazy Backend API sync

Protect `(console)` pages using edge redirects in `apps/web/src/proxy.ts` paired with per page `requireConsoleOrg()` server guards wrapped in `<Suspense>` and `loading.tsx`, keeping `ConsoleLayout` inside `(console)/layout.tsx` and keeping existing client view components separable for unit tests. On `apps/agent`, verify Clerk webhooks at `POST /api/v1/webhooks/clerk` with the `svix` Python SDK using atomic `ON CONFLICT` upserts, and run lazy Clerk Backend API fallback sync inside an isolated short lived database transaction.

**Pros**:
- Works cleanly with Next.js 16 `cacheComponents: true` and `partialPrefetching: true` without leaking console chrome or stalling on soft navigations.
- Eliminates race conditions between organization creation and immediate API usage without holding uncommitted locks during SSE streams.
- Resolves the Clerk `org_...` string vs PostgreSQL `UUID` mismatch cleanly by letting FastAPI resolve `organizations.id` from the verified JWT.

**Cons**:
- Adds `svix` and promotes `httpx` to main runtime dependencies of `apps/agent`, and requires `CLERK_SECRET_KEY` on FastAPI for fallback lookups.
- Requires splitting existing `"use client"` page files into Server Component wrappers and client view components.

### Option 2: Edge route protection only with webhook only sync

Use `createRouteMatcher` inside `apps/web/src/proxy.ts` for all route protection, and rely exclusively on `POST /api/v1/webhooks/clerk` in `apps/agent` without any Backend API fallback sync.

**Pros**:
- Centralizes route redirect rules in one middleware file and keeps `CLERK_SECRET_KEY` calls out of FastAPI request paths.
- Simpler backend code with no Clerk Backend API gateway port needed.

**Cons**:
- Relies on `createRouteMatcher`, which is deprecated in `@clerk/nextjs` v7, and leaves Server Components unprotected if invoked directly.
- Exposes newly created organizations to HTTP `403` errors whenever a user reaches `/tasks` before Svix delivers the webhook.

### Option 3: Next.js Route Handler webhook proxy and custom sign in UI

Receive Clerk webhooks in a Next.js Route Handler (`/api/webhooks/clerk`) using `@clerk/nextjs/webhooks`, forward validated payloads to an internal FastAPI endpoint, and build custom sign in and organization forms using Clerk hooks.

**Pros**:
- Uses Clerk's built in Next.js `verifyWebhook` helper directly and allows custom UI layouts for sign in forms.

**Cons**:
- Introduces an unnecessary network hop, extra internal secret management between Next.js and FastAPI, and higher UI maintenance cost for MFA, OAuth, and SSO flows.

## Rationale

This design addresses all three constraints identified in Context together. Running edge redirects in `proxy.ts` alongside per page `requireConsoleOrg()` guards inside `<Suspense>` and `loading.tsx` keeps Next.js 16 `cacheComponents: true` builds passing and protects client soft navigations between `(console)` pages without leaking `Sidebar` or `Header` chrome on auth routes. Guarding `(auth)/onboarding/organization` with `await auth()` instead of `auth.protect()` prevents the `@clerk/nextjs` v7 `sessionStatus === "pending"` redirect loop in `Membership required` mode.

On the backend, running `SyncOrganizationUseCase` inside an isolated short lived committed session with atomic PostgreSQL `INSERT ... ON CONFLICT (clerk_org_id) DO UPDATE` prevents SSE streams from holding uncommitted `organizations` locks and eliminates concurrent `IntegrityError` races. Removing Clerk's `org_...` string from `?org_id=` query parameters fixes the existing `422` UUID parsing mismatch cleanly because `authorize_task_org` already extracts `clerk_org_id` from the signed Clerk JWT.
