# 0008. Rationale: Guardrails, branch protection, and budget limits

## Context

`agentsOnAir` executes autonomous LLM coding loops (`ForgeCoderAgent` and `ReviewerCriticAgent`) inside isolated E2B microVMs or Docker containers and opens GitHub pull requests against tenant repositories. Earlier slices established the PostgreSQL data model with append only `audit_logs` (`0002`), the cyclical LangGraph workflow (`0004`), human in the loop `awaiting_input` pause and resume with SSE streaming (`0006`), and Clerk `org:admin` role enforcement (`0007`).

Without active guardrails, branch protection, and budget enforcement, a runaway loop or prompt injection inside an untrusted repository could rack up unbounded LLM bills, run past sandbox timeouts, exfiltrate secrets over outbound network calls, modify CI/CD workflows, or push directly to production branches like `main`. Currently `organizations.settings` only persists `sandbox_provider`, `timeout_minutes`, and a `protected_branch_guard` flag without real enforcement, `task_runs` lacks per step usage ledgering or cap enforcement, and `GitHubService` has no branch pattern validation or strict read/write token boundary.

Because this feature controls repository write access, credential scoping, and financial spending caps across multi tenant workspaces, strict tenant isolation (`org_id`), role based approval (`org:admin`), and immutable audit logging are mandatory constraints.

## Options considered

### Option 1: Defense in depth host and sandbox guardrails backed by typed JSONB policies, dedicated approval and usage tables, and LangGraph checkpoint interrupts

Store organization defaults and repository overrides in existing `organizations.settings` and `repositories.config` JSONB columns validated by Pydantic, enforce GitHub branch protection and write token isolation on the host `GitHubGateway` paired with a sandbox `pre-push` hook, persist risky action approvals in `task_approvals` using the existing LangGraph `interrupt()` state machine, and track integer cent spend via `usage_events` plus `org_monthly_usage` against a built in `app/core/pricing.py` map.

**Pros**:
- Keeps GitHub write tokens completely outside untrusted sandbox microVMs, preventing credential theft or hook tampering from bypassing branch protection.
- Reuses existing LangGraph checkpointing, Redis Streams SSE delivery, and watchdog infrastructure from Spec `0006` without building a second pause engine.
- Gives strong transactional guarantees and fast monthly cap lookups via `org_monthly_usage` while keeping policy schema extensions lightweight on existing JSONB columns.

**Cons**:
- Adds two new tables (`task_approvals`, `usage_events`) plus `org_monthly_usage`, requiring a schema migration and Drizzle schema sync in `apps/web`.
- Built in `pricing.py` requires manual updates or `MODEL_PRICING_OVERRIDES_JSON` configuration when LLM providers change token pricing.

### Option 2: Normalized policy tables with an external OPA policy engine and Redis spend counters

Create separate SQL tables for every policy rule (`guardrail_policies`, `branch_protection_rules`, `budget_limits`), delegate rule evaluation to an Open Policy Agent (OPA) sidecar running Rego bundles, pull model pricing via `litellm`, and track real time spending exclusively in Redis counters flushed on task completion.

**Pros**:
- Separates policy authoring into a dedicated declarative policy language (Rego) that security teams can update independently of Python code.
- Sub millisecond budget increments in Redis avoid PostgreSQL write overhead during tight LLM tool loops.

**Cons**:
- Introduces an additional OPA runtime service and `litellm` dependency, violating operational simplicity for a small engineering team.
- Redis spend counters risk drift or undercounting across worker crashes or Redis restarts before PostgreSQL reconciliation.

### Option 3: Host only static branch checks and `task_interventions` reuse without a usage ledger

Validate only the repository `default_branch` on the host before opening a PR, reuse `task_interventions` as plain text messages for approvals without a dedicated `task_approvals` table, and compute monthly spend dynamically by summing `task_runs.estimated_cost_cents`.

**Pros**:
- Zero new database tables and minimal migration work.
- Fastest initial implementation path with the fewest moving parts.

**Cons**:
- Cannot cleanly enforce single active pending approval uniqueness, structured risk payloads, or atomic race prevention on approval timeout.
- Summing `task_runs` across the month for every LLM preflight check degrades under load and lacks per operation (`forge` vs `reviewer` vs `pr_review`) cost attribution.
- Protecting only `default_branch` leaves release branches (`release/*`) exposed and provides no sandbox network or sensitive path gates.

## Rationale

Option 1 fits `agentsOnAir`'s Clean Architecture and operational constraints best. Because sandbox code is untrusted by definition, enforcing branch protection solely inside the sandbox via git hooks can be bypassed by an agent editing `.git/hooks`, so keeping write tokens strictly on the host `GitHubGateway` while pairing them with a sandbox hook gives defense in depth with zero extra infrastructure.

Similarly, extending `organizations.settings` and `repositories.config` with typed Pydantic schemas avoids unnecessary 1:1 policy tables while giving every repository clean override inheritance. Meanwhile, adding `task_approvals`, `usage_events`, and `org_monthly_usage` provides exact relational invariants (partial unique index on pending approvals, atomic conditional `UPDATE` on concurrent approval vs expiry, and `O(1)` monthly org cap checks) without introducing OPA sidecars, Redis counter drift, or `litellm` dependency bloat.
