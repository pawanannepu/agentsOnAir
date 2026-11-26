# Verify: clerk sign in & organization switcher · spec 0007 · updated 2026-11-26
_Steps derived from spec 0007 acceptance criteria and value sourcing table. `/check verify` runs these; `/test` locks the durable ones._

## UI / manual
- [ ] Visit `/tasks`, `/`, `/repositories`, `/settings`, and `/tasks/018f6c38-8921-7000-8000-000000000001` while signed out -> expect HTTP `307` redirect to `/sign-in` with `redirect_url` preserved → AC-1
- [ ] Visit `/sign-in` and `/sign-up` -> expect centered `(auth)` dark zinc shell without `Sidebar` or `Header`, rendering Clerk `<SignIn />` and `<SignUp />` inside `<Suspense>` with `fallbackRedirectUrl="/tasks"` → AC-2
- [ ] Sign in as a user with `sessionStatus === "pending"` or without an active `orgId` -> expect redirect to `/onboarding/organization` rendering `<TaskChooseOrganization />` (when pending) or `<OrganizationList hidePersonal />` (when no active org) without looping to `/sign-in` → AC-3
- [ ] Create or select an organization from `/onboarding/organization` or `Sidebar` `<OrganizationSwitcher hidePersonal />` -> expect navigation to `/tasks` with active org name, avatar, and `<UserButton />` rendered in `Sidebar` footer → AC-3
- [ ] Visit `/settings` as an `org:member` user vs an `org:admin` user -> expect `org:member` to see the access denied screen (`Admin Access Required`) and `org:admin` to load and save settings via `PATCH /api/v1/organizations/settings` → AC-4
- [ ] Open `/tasks/[id]` with live Clerk keys and inspect network requests -> expect `GET /api/v1/tasks/{id}`, `/events`, `/transcript`, `/intervene`, `/respond`, and `/abort` to omit Clerk `org_...` from `?org_id=` while resolving the internal PostgreSQL UUID from the verified JWT → AC-4
- [ ] Trigger a FastAPI `403` response with `{"code": "org_inactive"}` or `{"code": "org_missing"}` from `/tasks/[id]` or `/settings` -> expect the global recovery modal in `ConsoleLayout` to render `<OrganizationList hidePersonal />` and a `Reload session` button calling `session.reload()` → AC-7
- [ ] Start `apps/web` in `NODE_ENV=production` with placeholder Clerk keys (`pk_test_placeholder` / `sk_test_placeholder`): request `GET /api/health` -> expect HTTP `200` `{"status": "ok"}`; request `/tasks` -> expect HTTP `500` fail closed response → AC-1

## Commands
- [ ] `POST /api/v1/webhooks/clerk` with `organization.created` (`data.slug = null`), `organization.updated`, duplicate delivery, and `organization.deleted` signed via Svix -> expect fallback slug `org-<lower>`, atomic `ON CONFLICT` upsert, `audit_logs` rows only on actual state changes (`actor_type = "clerk_webhook"`), `401` on invalid signature, `503` when secret unset, and non resurrection when stale `organization.updated` arrives after `organization.deleted` → AC-5
- [ ] `POST /api/v1/organizations/sync` and `GET /api/v1/tasks/{task_id}` for an org present in Clerk Backend API (`200`) but absent or soft deleted in PostgreSQL -> expect isolated `async_session_factory()` commit, `audit_logs` (`action = "organization.synced"`, `actor_type = "user"`, `actor_id = caller.user_id`), and `403` `{"code": "org_inactive"}` when Clerk returns `404` or `CLERK_SECRET_KEY` is unconfigured → AC-6
- [ ] `PATCH /api/v1/organizations/settings` with `org:member` JWT vs `org:admin` JWT -> expect `403` `{"code": "org_admin_required"}` for `org:member` and `200` with persisted JSONB `settings` + `audit_logs` for `org:admin` → AC-4
- [ ] `uv run --directory apps/agent pytest tests/test_clerk_org_sync.py tests/test_tasks_api.py tests/test_webhooks.py tests/test_task_streaming.py -v` -> expect all tests passing → AC-4, AC-5, AC-6
- [ ] `pnpm --filter web test && pnpm --filter web typecheck && pnpm --filter web lint && pnpm --filter web build` -> expect all Vitest suites (`console-views.test.tsx`, `clerk-auth.test.tsx`, `page.test.tsx`, `task-stream.test.tsx`) passing and Next.js build succeeding with `cacheComponents: true` and `partialPrefetching: true` → AC-1, AC-7

## Acceptance-criteria coverage
- AC-1: edge redirects (`proxy.ts`), `requireConsoleOrg()` inside `<Suspense>` + `loading.tsx`, public `/sign-in`, `/sign-up`, `/api/health`, and production fail closed `500` covered by UI steps 1, 8 and Command step 5.
- AC-2: `(auth)` centered dark shell without `Sidebar`/`Header` and Clerk `<SignIn />` / `<SignUp />` covered by UI step 2.
- AC-3: `/onboarding/organization` with `await auth()`, `<TaskChooseOrganization />` vs `<OrganizationList hidePersonal />`, `Sidebar` `<OrganizationSwitcher hidePersonal />` and `<UserButton />` covered by UI steps 3, 4.
- AC-4: `org:member` vs `org:admin` on `/settings` and `PATCH /api/v1/organizations/settings`, plus JWT tenant resolution without `?org_id=org_...` covered by UI steps 5, 6 and Command steps 3, 4.
- AC-5: Svix webhook signature validation, atomic upserts, non resurrection on stale updates, idempotent soft delete, and `audit_logs` snapshots covered by Command steps 1, 4.
- AC-6: Isolated short lived `async_session_factory()` lazy and explicit Clerk Backend API sync (`5.0s` timeout), `audit_logs`, and `403` `org_inactive` mapping covered by Command steps 2, 4.
- AC-7: Global `403` recovery modal with `<OrganizationList hidePersonal />` + `session.reload()`, `console-views.test.tsx` compatibility, and `next build` with `cacheComponents: true` covered by UI step 7 and Command step 5.
