# 0008. Guardrails, branch protection, and budget limits

**Date**: 2026-11-26
**Status**: In Progress

## Summary

This specification defines how agentsOnAir keeps autonomous engineering tasks safe, bounded, and within budget. It enforces least privilege GitHub tokens so write credentials never enter untrusted sandboxes, blocks direct pushes to protected branches at both the sandbox and host layers, and pauses risky actions for `org:admin` approval. It also tracks token usage and integer cent costs per model call, halting tasks immediately when per task cost, monthly organization spend, cycle count, or active runtime limits are reached.

## Requirements

**User stories**:
- As an organization administrator, I want to configure protected branch patterns, risky action rules, sandbox network egress, and spending or runtime limits with repository level overrides so that autonomous tasks operate within safe boundaries.
- As a security engineer, I want write GitHub credentials kept off untrusted sandboxes and direct pushes to protected branches blocked at both sandbox and host layers so that compromised code cannot alter protected branches.
- As a developer or operator, I want tasks to pause for explicit admin approval before executing risky commands or workflow edits, and to halt immediately with preserved logs and partial diffs when cost or time limits are hit.

**Acceptance criteria**:
- **AC-1**: Organizations store typed guardrail and budget defaults in `organizations.settings` (`protected_branches`: `["main", "master", "release/*"]`, `require_approval_for`: `["destructive_shell", "external_network", "sensitive_path_edit", "force_git_op", "large_diff"]`, `max_task_cost_cents`: `500`, `max_monthly_org_cost_cents`: `10000`, `timeout_minutes`: `10`, `max_cycles`: `3`, `network_egress_mode`: `"off_after_install"`, `allowed_egress_domains`: `[]`, `large_diff_lines_threshold`: `500`), validated via Pydantic with explicit bounds (`max_task_cost_cents >= 1`, `max_monthly_org_cost_cents >= 1`, `timeout_minutes` `1..60`, `max_cycles` `1..10`, `large_diff_lines_threshold >= 1`, non empty `protected_branches`). Repositories optionally override fields under `repositories.config["guardrails"]` (preserving existing keys such as `test_command` and optional `install_command`; sending `null` deletes the override key), inheriting unset fields from organization defaults. Any authenticated organization member can read effective guardrails (`GET /api/v1/organizations/guardrails`, `GET /api/v1/repositories`, `GET /api/v1/repositories/{repo_id}/guardrails`), while only `org:admin` can modify policies (`PATCH /api/v1/organizations/settings`, `PATCH /api/v1/repositories/{repo_id}/guardrails`), recording an immutable `audit_logs` entry on every update. Setting `protected_branch_guard: false` is disallowed when non empty `protected_branches` exist.
- **AC-2**: Sandbox initialization receives at most a short lived `contents:read` installation token for cloning and immediately strips credentials from `.git/config` remote URLs after clone, never exposing write credentials inside the sandbox. Pushing branches and opening pull requests execute exclusively inside a `host_publish_node` in `task_graph.py` via `GitHubGateway` after review approval using a freshly minted `contents:write` and `pull_requests:write` token. Both a system configured sandbox `pre-push` hook (`git config --system core.hooksPath`) and host `GitHubGateway` strip `refs/heads/` and match target branch names (`head_branch` on PRs) against effective `protected_branches` globs using `fnmatch.fnmatchcase`, rejecting direct pushes to protected branches with a `protected_branch_blocked` failure and an immutable `audit_logs` record.
- **AC-3**: Before executing risky sandbox commands (`SandboxWorkspace.execute_command`, excluding repository configured `test_command` in `run_test`), sensitive file writes (`SandboxWorkspace.write_file` and shell file mutations), or host publish mutations (`large_diff` or force git operations), `PolicyEvaluator` classifies the action against explicit rules: `shlex` command token matching for `destructive_shell` (`rm -rf`, `mkfs`, `dd`, `chmod 777`, `git reset --hard`, `git push --force`) and `external_network` (`curl`, `wget`, `nc`, `ssh`, `scp`; blocked immediately without prompting when `network_egress_mode == "off_after_install"`), `force_git_op` (`git push -f`, `git reset --hard`, `git rebase`, or host `force=True`), path normalization plus `fnmatchcase` matching for `sensitive_path_edit` (`.github/workflows/**`, `.gitlab-ci.yml`, `**/.env*`, `**/auth/**`), and `large_diff` (counting added plus removed `+` and `-` diff lines excluding file/hunk headers against `large_diff_lines_threshold` inside `host_publish_node`). When approval is required and no unconsumed `approved` `task_approvals` record matches the deterministic `action_hash`, `PolicyEvaluator` inserts a `task_approvals` row in `pending` state in an isolated short lived transaction (enforcing at most one pending approval per task via `uq_task_approvals_pending_task`), pauses via LangGraph `interrupt()`, extends sandbox timeout, schedules the interruption watchdog, and emits a `task.approval_requested` Server Sent Event.
- **AC-4**: Only `org:admin` members in the task's organization can submit `approved` or `rejected` decisions via `POST /api/v1/tasks/{task_id}/approvals/{approval_id}/decision` (non admins receive HTTP `403`). Existing `POST /api/v1/tasks/{task_id}/respond` rejects tasks whose `interruption_type == "approval"` with HTTP `409 Conflict`. Decisions and watchdog expiry (`handle_interruption_timeout`) run an atomic conditional SQL `UPDATE` (`WHERE id = :id AND status = 'pending'`) paired with `task_runs.version` optimistic concurrency, returning HTTP `409` to any losing concurrent caller. Approving enqueues a structured resume payload (`{"approval_id", "decision"}`) to `resume_task_job`, marks the matching `action_hash` approved so LangGraph replay does not duplicate prior writes or re-trigger the interrupt, and rehydrates uncommitted `checkpoint_state["partial_diff"]` if resumed on a different worker without `SandboxRegistry`. Rejecting or hitting `expires_at` finalizes the task as `failed` (`approval_rejected` or `approval_expired`), terminates the sandbox, emits `task.status` with `failure_reason`, and records an `audit_logs` entry.
- **AC-5**: Every Forge, Reviewer, and PR review model call returns typed token telemetry (`provider`, `model`, `prompt_tokens`, `completion_tokens`) and, in an isolated short lived DB transaction per call, appends an immutable row to `usage_events` (with nullable `task_id`, `task_run_id`, and `pr_review_id` foreign keys), atomically increments `task_runs` counters, and performs an atomic PostgreSQL UPSERT on `org_monthly_usage` keyed by `(org_id, billing_month)` in UTC (`YYYY-MM`). Estimated costs use ceiling integer cent math (`math.ceil`, minimum `1` cent per non zero token call) from a versioned built in table in `app/core/pricing.py` with optional `MODEL_PRICING_OVERRIDES_JSON` overrides and a conservative fallback rate for unknown models, emitting a `task.budget_updated` Server Sent Event for task calls.
- **AC-6**: Before each inner LLM call (preflight) and immediately after usage accounting (postflight), `UsageTracker` checks cumulative `task_runs.estimated_cost_cents` against `max_task_cost_cents`, `org_monthly_usage.total_cost_cents` against `max_monthly_org_cost_cents` (also enforced in `RunPRReviewUseCase`), active execution seconds (excluding `task_runs.paused_seconds` accumulated during `awaiting_input`) against `timeout_minutes`, and cycle count against `max_cycles`. LLM and sandbox calls run inside `asyncio.wait_for` bounded by the remaining active deadline, and `timeout_minutes * 60` is passed to `create_sandbox()`. Reaching or exceeding any cap halts execution immediately without another model call or PR push, archives `partial_diff` into `task_runs.checkpoint_state` and transcript logs, transitions task and run to `failed` with explicit `failure_reason` (`budget_exceeded`, `timeout_exceeded`, or `review_cycle_limit_exhausted`), terminates the sandbox, emits `task.status`, and records an `audit_logs` entry.
- **AC-7**: Sandbox creation and post install setup enforce `network_egress_mode` (`off_after_install`, `allowlist`, or `unrestricted`) via `SandboxProvider.create_sandbox(..., network_egress_mode, allowed_egress_domains)` and `SandboxSession.restrict_network()` triggered right after `init_workspace` and optional `install_command` (using E2B network rules and Docker container network isolation, treating `allowlist` with `[]` as blocking all outbound traffic, validating domains as lowercase hostnames with optional leading `*.` wildcard). In `apps/web`, `/settings` renders the Guardrails & Budgets form for `org:admin` plus the monthly spend bar (`GET /api/v1/organizations/usage`), `/repositories` loads real repositories (`GET /api/v1/repositories`) with a Guardrail Overrides drawer (viewable by all members, editable by `org:admin`), and the task inspector displays a live dollar formatted cost meter and an Approval Gate card showing risk category, action payload, and `org:admin` Approve or Reject controls.

## Decision

**Chosen option**: Option 1: Defense in depth host and sandbox guardrails backed by typed JSONB policies, dedicated approval and usage tables, and LangGraph checkpoint interrupts.

We enforce branch protection and least privilege token boundaries on the host `GitHubGateway` backed by a system sandbox hook, reuse LangGraph `interrupt()` and `awaiting_input` inside `task_graph.py` with a dedicated `task_approvals` table and `action_hash` idempotency, and track ceiling integer cent spend across `usage_events` and `org_monthly_usage` in short lived transactions.

**Implementation skills**: `fastapi-templates` (`wshobson/agents`, `.agents/skills/fastapi-templates/`) · `nextjs-app-router-patterns` (`wshobson/agents`, `.agents/skills/nextjs-app-router-patterns/`) · `clerk-nextjs-patterns` (`clerk/skills`, `.agents/skills/clerk-nextjs-patterns/`) · `tailwind-design-system` (`wshobson/agents`, `.agents/skills/tailwind-design-system/`)

## Rationale

Reasoning and options: see [rationale.md](rationale.md).

## Feature design

**Data model sketch**:
- `organizations` (existing): `settings` (`JSONB`, non nullable) stores typed `GuardrailPolicy` defaults (`protected_branches`, `require_approval_for`, `max_task_cost_cents`, `max_monthly_org_cost_cents`, `timeout_minutes`, `max_cycles`, `network_egress_mode`, `allowed_egress_domains`, `large_diff_lines_threshold`) alongside existing `sandbox_provider`.
- `repositories` (existing): `config` (`JSONB`, non nullable) stores optional `install_command` (`str | None`), existing `test_command`, and nested `guardrails` (`GuardrailPolicyOverride` dict where absent keys inherit from organization defaults).
- `task_runs` (existing): retains `prompt_tokens`, `completion_tokens`, `tokens_used`, `estimated_cost_cents` (`INTEGER`, default `0`), `version` (`INTEGER`), and adds `paused_seconds` (`INTEGER`, default `0`, non nullable) plus `failure_reason` values (`budget_exceeded`, `timeout_exceeded`, `approval_rejected`, `approval_expired`, `protected_branch_blocked`, `review_cycle_limit_exhausted`). `checkpoint_state` stores `partial_diff` and `approved_action_hashes`.
- `task_approvals` (new): `id` (`UUID`, PK), `org_id` (`UUID`, FK `organizations.id` CASCADE), `task_id` (`UUID`, FK `tasks.id` CASCADE), `task_run_id` (`UUID`, FK `task_runs.id` CASCADE), `status` (`VARCHAR(32)`, `pending` | `approved` | `rejected` | `expired`), `risk_category` (`VARCHAR(64)`), `action_type` (`VARCHAR(64)`), `action_hash` (`VARCHAR(64)`), `action_summary` (`TEXT`), `action_payload` (`JSONB`), `consumed_at` (`TIMESTAMPTZ`, nullable), `decided_by_clerk_user_id` (`VARCHAR(255)`, nullable), `decision_note` (`TEXT`, nullable), `expires_at` (`TIMESTAMPTZ`), `decided_at` (`TIMESTAMPTZ`, nullable), `created_at` (`TIMESTAMPTZ`). Partial unique index `uq_task_approvals_pending_task` on `(task_id) WHERE status = 'pending'`.
- `usage_events` (new, append only): `id` (`UUID`, PK), `org_id` (`UUID`, FK `organizations.id` CASCADE), `task_id` (`UUID`, FK `tasks.id` CASCADE, nullable), `task_run_id` (`UUID`, FK `task_runs.id` CASCADE, nullable), `pr_review_id` (`UUID`, FK `pull_request_reviews.id` CASCADE, nullable), `provider` (`VARCHAR(64)`), `model` (`VARCHAR(128)`), `operation_type` (`VARCHAR(32)`, `forge` | `reviewer` | `pr_review`), `prompt_tokens` (`INTEGER`), `completion_tokens` (`INTEGER`), `estimated_cost_cents` (`INTEGER`), `created_at` (`TIMESTAMPTZ`). Check constraint requires either `task_run_id IS NOT NULL` or `pr_review_id IS NOT NULL`. Indexed on `(org_id, created_at DESC)` and `(task_run_id, created_at ASC)`.
- `org_monthly_usage` (new): `id` (`UUID`, PK), `org_id` (`UUID`, FK `organizations.id` CASCADE), `billing_month` (`VARCHAR(7)`, UTC `YYYY-MM`), `total_tokens` (`BIGINT`, default `0`), `total_cost_cents` (`INTEGER`, default `0`), `updated_at` (`TIMESTAMPTZ`). Unique index `uq_org_monthly_usage_org_month` on `(org_id, billing_month)`.

**State transitions**:
- `task_approvals.status`: `pending` -> `approved` (by `org:admin`), `pending` -> `rejected` (by `org:admin`), `pending` -> `expired` (by watchdog after `expires_at`). All transitions are terminal and guarded by `WHERE status = 'pending'`; `approved` records are marked `consumed_at` once executed.
- `tasks.status` on guardrail events: `in_progress` -> `awaiting_input` (`interruption_type = 'approval'`, accumulating `paused_seconds` until resumed) -> `in_progress` (on `approved`) or `failed` (on `rejected` or `expired`); `in_progress` -> `failed` directly on `budget_exceeded`, `timeout_exceeded`, or `protected_branch_blocked`.

**API surface**:

| Endpoint | Method | Key inputs | Key outputs | Auth | Key errors |
|---|---|---|---|---|---|
| `/api/v1/organizations/guardrails` | GET | none (org from token) | effective `GuardrailPolicy` defaults | Clerk bearer (any org member) | 401, 403 `org_missing` |
| `/api/v1/organizations/settings` | PATCH | `sandbox_provider`, `timeout_minutes`, `protected_branch_guard`, `GuardrailPolicy` fields (opt) | `id`, `settings` | Clerk bearer (`org:admin`) | 403 `org_admin_required`, 422 validation |
| `/api/v1/organizations/usage` | GET | `month` (`YYYY-MM`, opt, default current UTC month) | `billing_month`, `total_tokens`, `total_cost_cents`, `max_monthly_org_cost_cents`, `remaining_cents` (clamped `>= 0`) | Clerk bearer (any org member) | 401, 403 `org_missing`, 422 invalid month |
| `/api/v1/repositories` | GET | `limit` (default 50), `offset` (default 0) | paginated list of connected repos with `effective_policy` summary | Clerk bearer (any org member) | 401, 403 `org_missing` |
| `/api/v1/repositories/{repo_id}/guardrails` | GET | `repo_id` path UUID | `org_defaults`, `repo_overrides`, `effective_policy` | Clerk bearer (any org member) | 404 repo not found, 403 |
| `/api/v1/repositories/{repo_id}/guardrails` | PATCH | partial `GuardrailPolicyOverride` fields (`null` deletes key) | `repo_id`, `repo_overrides`, `effective_policy` | Clerk bearer (`org:admin`) | 403 `org_admin_required`, 404, 422 |
| `/api/v1/tasks/{task_id}/approvals/{approval_id}/decision` | POST | `decision` (`approved` \| `rejected`, req), `note` (str, opt) | `approval_id`, `status`, `task_status` | Clerk bearer (`org:admin`) | 403 `org_admin_required`, 404, 409 already decided or expired |
| `/api/v1/tasks/{task_id}` | GET | `task_id` path UUID | existing detail plus `pending_approval` (`approval_id`, `risk_category`, `action_type`, `action_summary`, `action_payload`, `expires_at`), `budget_summary` (`task_cost_cents`, `max_task_cost_cents`, `tokens_used`, `partial_diff`) | Clerk bearer (org member) | 403, 404 |

**SSE event payloads**:
- `task.approval_requested`: `{"approval_id": "<uuid>", "risk_category": "<str>", "action_type": "<str>", "action_summary": "<str>", "action_payload": {...}, "expires_at": "<iso8601>"}`
- `task.budget_updated`: `{"task_cost_cents": <int>, "max_task_cost_cents": <int>, "tokens_used": <int>, "org_month_cost_cents": <int>, "max_monthly_org_cost_cents": <int>}`
- `task.status` (failure): standardizes `{"status": "failed", "failure_reason": "<str>"}` alongside optional `"reason"` for backward compatibility.

**Value sourcing**:

| Action | Value produced or displayed | Source |
|---|---|---|
| Policy evaluation (`PolicyEvaluator`) | Effective `protected_branches`, `require_approval_for`, `max_task_cost_cents`, `max_monthly_org_cost_cents`, `timeout_minutes`, `max_cycles`, `network_egress_mode`, `allowed_egress_domains`, `large_diff_lines_threshold` | Merged from `repositories.config["guardrails"]` over `organizations.settings`, falling back to Pydantic defaults (`main`, `master`, `release/*`; all 5 risky categories; `500` cents; `10000` cents; `10` min; `3` cycles; `off_after_install`; `[]`; `500` lines) |
| Risky action classification (`PolicyEvaluator`) | `risk_category`, `action_type`, `action_hash`, `action_summary` | `shlex` command parsing for `destructive_shell`/`external_network`/`force_git_op`; normalized path `fnmatchcase` against default sensitive globs for `sensitive_path_edit`; unified diff `+`/`-` line count vs `large_diff_lines_threshold`; SHA-256 of `(cycle_number, action_type, canonical_payload)` |
| Usage accounting (`UsageTracker`) | `estimated_cost_cents` per model call | `math.ceil` (min `1` cent if tokens > 0) using `prompt_tokens`, `completion_tokens`, and `model` rates from `app/core/pricing.py` plus `MODEL_PRICING_OVERRIDES_JSON` |
| Monthly spend check and `/usage` | `billing_month`, `total_cost_cents`, `remaining_cents` | Current UTC `YYYY-MM` (`datetime.now(UTC).strftime("%Y-%m")`) queried from `org_monthly_usage` for `(org_id, billing_month)` (returns `0` when absent; `remaining_cents = max(0, cap - total)`) |
| Active runtime deadline | Remaining active execution seconds | `timeout_minutes * 60 - (now - task_runs.started_at - task_runs.paused_seconds)` |
| Task detail & live meter | `pending_approval`, `budget_summary`, `partial_diff` | Latest `task_runs` row + `task_approvals` row where `status = 'pending'`, hydrated by `GET /api/v1/tasks/{task_id}` and updated live via SSE |

**Key invariants**:
- At most one `task_approvals` row may exist with `status = 'pending'` per `task_id`, enforced by `uq_task_approvals_pending_task`.
- Write GitHub tokens never enter sandbox memory, disk, or `.git/config`; host `GitHubGateway` inside `host_publish_node` is the sole push/PR actor and enforces `fnmatchcase` branch protection after stripping `refs/heads/`.
- Every LLM call commits `usage_events`, `task_runs`, and `org_monthly_usage` in an isolated short lived transaction immediately on completion so live `/usage` and concurrent preflight checks stay consistent.
- Approval decision endpoints and watchdog expiry atomically claim `pending` rows via `WHERE id = :id AND status = 'pending'` and verify `task_runs.version`, returning `409 Conflict` on races.
- Every guardrail policy update, approval request, approval decision, blocked protected branch push, and budget or timeout halt appends an immutable row to `audit_logs`.

**Security model**:
- `org:admin` Clerk role (`require_org_admin`) is required to update organization settings, update repository guardrail overrides, and approve or reject risky action requests.
- `POST /api/v1/tasks/{task_id}/respond` rejects approval pauses (`409 Conflict`) so non admins cannot bypass `org:admin` approval gates.
- Any authenticated organization member (`resolve_caller_org`) can read effective policies, list connected repositories, view monthly usage, and inspect task cost meters and pending approval details; `/settings` write controls remain restricted to `org:admin`.
- Tenant isolation scopes every query by `org_id`. Compliance audit logging relies on the append only `audit_logs` database trigger from Spec `0002`.

**Configuration required**:
- `MODEL_PRICING_OVERRIDES_JSON`: optional JSON string overriding per million token input and output prices in cents for `app/core/pricing.py`.
- `DEFAULT_APPROVAL_TIMEOUT_SECONDS`: optional integer overriding how long a `pending` approval waits before watchdog expiry (defaults to `INTERRUPTION_TIMEOUT_SECONDS`).

**Critical test scenarios**:
- Happy path: task clones with `contents:read`, strips clone token, pauses when Forge attempts `.github/workflows/ci.yml`, `org:admin` approves via `/approvals/{id}/decision`, task resumes without duplicating prior edits, passes review, passes `host_publish_node` branch check, and opens PR, verifies **AC-1**, **AC-2**, **AC-3**, **AC-4**.
- Protected branch rejection: direct push to `main` or `release/v1` is rejected by both sandbox `core.hooksPath` `pre-push` hook and host `GitHubGateway`, failing with `protected_branch_blocked` and writing `audit_logs`, verifies **AC-2**.
- Budget and active runtime enforcement: cumulative ceiling cost hitting `max_task_cost_cents` or `max_monthly_org_cost_cents` (or active runtime exceeding `timeout_minutes` while excluding `paused_seconds`) halts immediately, saves `partial_diff`, terminates sandbox, and writes `audit_logs`, verifies **AC-5**, **AC-6**.
- Auth and concurrency: non admin calling `/approvals/{id}/decision`, non admin calling `PATCH /repositories/{id}/guardrails`, or any caller calling `/respond` on an approval pause is rejected (`403` / `409`); simultaneous approve and watchdog expire returns `409 Conflict` to the loser, verifies **AC-1**, **AC-4**.
- Egress and console UI: sandbox runs `restrict_network()` after install/clone, `/settings` and `/repositories` drawer persist overrides, and task inspector renders live dollar meter and `org:admin` Approval Gate card, verifies **AC-7**.

## Build plan

Following the project's **Tracer Bullet** approach, Slice 1 establishes the core schema, policy evaluator, host branch guard, and LangGraph approval/budget gates end to end before broadening to repository overrides, sandbox egress controls, and the full console UI.

1. [x] Create Alembic migration and SQLAlchemy models for `task_approvals`, `usage_events` (nullable `task_id`, `task_run_id`, `pr_review_id`), `org_monthly_usage`, `task_runs.paused_seconds`, partial unique index `uq_task_approvals_pending_task`, and Drizzle schema updates in `apps/web/src/db/schema.ts`, satisfies **AC-1**, **AC-3**, **AC-4**, **AC-5**, **AC-6**.
2. [x] Implement Pydantic `GuardrailPolicy` and `GuardrailPolicyOverride` schemas, `PolicyEvaluator` domain service (`repositories.config["guardrails"]` merge, `fnmatchcase` branch matching, `shlex` and sensitive glob risky action classification, `action_hash`), and `app/core/pricing.py` (`math.ceil` integer cent pricing) plus `UsageTracker` isolated transaction repositories, satisfies **AC-1**, **AC-2**, **AC-3**, **AC-5**.
3. [x] Wire host `GitHubGateway` protected branch validation, tokenless/read only clone cleanup in `.git/config`, and sandbox system `core.hooksPath` `pre-push` hook in `SandboxWorkspace`, satisfies **AC-2**.
4. [x] Refactor `task_graph.py` and `RunAutonomousLoopUseCase` (`RunPRReviewUseCase` for monthly cap) to move host push/PR into `host_publish_node`, attach token telemetry to model gateways, enforce preflight/postflight budget and active `timeout_minutes` (`asyncio.wait_for` + `paused_seconds`), wire `action_hash` idempotent `interrupt()` approval resume (including `partial_diff` replay), and update `handle_interruption_timeout` for atomic `approval_expired`, satisfies **AC-2**, **AC-3**, **AC-4**, **AC-5**, **AC-6**.
5. [x] Build and update FastAPI endpoints (`GET /api/v1/organizations/guardrails`, `PATCH /api/v1/organizations/settings`, `GET /api/v1/organizations/usage`, `GET /api/v1/repositories`, `GET/PATCH /api/v1/repositories/{repo_id}/guardrails`, `POST /api/v1/tasks/{task_id}/approvals/{approval_id}/decision`, `/respond` approval guard, and `GET /api/v1/tasks/{task_id}` extensions) with `org:admin` RBAC and `audit_logs` events, satisfies **AC-1**, **AC-4**, **AC-5**.
6. [x] Add `network_egress_mode` and `allowed_egress_domains` support to `SandboxProvider.create_sandbox()` and `SandboxSession.restrict_network()` in E2B and Docker sandbox providers triggered after `init_workspace` / `install_command`, satisfies **AC-7**.
7. [x] Build Console UI surfaces: expand `/settings` with Guardrails & Budgets form and monthly usage bar, wire `/repositories` to `GET /api/v1/repositories` with a Guardrail Overrides drawer, and extend `use-task-stream.ts` plus the task inspector with a live dollar cost meter and `org:admin` Approval Gate card, satisfies **AC-7**.
8. [x] Write unit and integration tests (Pytest and Vitest) covering protected branch rejection, `/respond` bypass rejection, approval `409` concurrency, `403` RBAC, ceiling cost/runtime halts with `paused_seconds`, egress lifecycle, and console UI views, satisfies **AC-1**, **AC-2**, **AC-3**, **AC-4**, **AC-5**, **AC-6**, **AC-7**.

## Consequences

**Positive**:
- Untrusted code inside sandboxes cannot access GitHub write credentials, bypass host branch protection, or slip through `/respond` to waive admin approvals.
- Reusing LangGraph `interrupt()` inside `task_graph.py` with `action_hash` tracking unifies clarifications, risky tool approvals, and host large diff gates cleanly across worker restarts.
- Isolated short lived transactions for `usage_events` and `org_monthly_usage` ensure real time `/usage` visibility and concurrent monthly spend caps.

**Negative / tradeoffs**:
- Per LLM call isolated DB commits add small transaction overhead inside the agent loop.
- Built in `pricing.py` rates require periodic updates or `MODEL_PRICING_OVERRIDES_JSON` updates as providers revise pricing.
- Soft preflight plus hard postflight accounting can allow a single expensive LLM call to overshoot the exact cent cap slightly before halting.

**Neutral**:
- Existing `organizations.settings` and `repositories.config` JSONB columns gain typed Pydantic validation while preserving existing keys (`sandbox_provider`, `test_command`) and backward compatibility.
- `apps/web/src/db/schema.ts` must stay synchronized with the new PostgreSQL tables and `task_runs.paused_seconds`.

## Follow-up

- [ ] Keep `apps/web/src/db/schema.ts` synchronized with `task_approvals`, `usage_events`, `org_monthly_usage`, and `task_runs.paused_seconds` when executing task 1 of the build plan.
- [ ] Review and refresh model pricing rates in `app/core/pricing.py` before onboarding new LLM providers or model families.
