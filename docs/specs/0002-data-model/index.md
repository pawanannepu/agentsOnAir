# 0002. Data model for tenant isolation, task execution, and credentials

**Date**: 2026-11-22
**Status**: In Progress

## Summary

This decision defines the core PostgreSQL database schema for agentsOnAir, establishing data models for tenant organizations, repositories, agent tasks, execution runs, sandbox sessions, audit logs, and encrypted secrets. We use UUIDv7 identifiers across all entities to maintain index locality while avoiding sequential ID guessing, paired with application level tenant filtering tied to Clerk organization IDs. Sensitive repository tokens and provider keys are protected using AES 256 GCM authenticated encryption at rest, while an append only audit log with database triggers guarantees a permanent compliance history. This schema provides the foundation for autonomous agent workflows, sandbox isolation, and web console inspection.

## Requirements

**User stories**:
* As an organization administrator, I want my repositories, tasks, and credentials isolated to my workspace so that other organizations cannot inspect or access our code.
* As an autonomous agent worker, I want task attempts, LangGraph state checkpoints, and sandbox allocations stored reliably so that tasks can resume seamlessly after failures or user pauses.
* As a security engineer, I want repository access tokens encrypted at rest and all sensitive operations recorded in an immutable audit trail so that credentials stay secure and changes are fully traceable.

**Acceptance criteria**:
* **AC-1**: Database schema establishes core relational entities (`organizations`, `repositories`, `credentials`, `tasks`, `task_runs`, `sandbox_runs`, `audit_logs`) with UUIDv7 primary keys and explicit foreign key constraints in PostgreSQL.
* **AC-2**: Tenant isolation is guaranteed across all queries by scoping root entities, task runs, and sandbox runs to an organization identifier (`org_id`) corresponding to Clerk organization IDs.
* **AC-3**: Agent tasks support repeated execution attempts via a two tier `tasks` and `task_runs` relationship, storing serialized LangGraph checkpoint state in a dedicated JSONB column with optimistic concurrency control via a version counter.
* **AC-4**: Each `task_runs` record binds one to one with a `sandbox_runs` record tracking sandbox provider (`e2b` or `docker`), resource limits, timeout settings, and object storage keys for execution logs.
* **AC-5**: Sensitive credentials are stored in `credentials` using AES 256 GCM authenticated encryption with unique nonces, storing base64 ciphertext with 16 byte authentication tag and initialization vectors at rest.
* **AC-6**: Audit events are recorded in an append only `audit_logs` table capturing actor type, actor ID, action name, target entity, and JSONB before and after snapshots, with database triggers blocking any update or delete operations and foreign keys set to `ON DELETE RESTRICT`.
* **AC-7**: Soft deletion via `deleted_at` timestamps is supported for repositories, organizations, and tasks using partial unique indexes, while credentials are hard deleted upon revocation.
* **AC-8**: Single coherent Alembic migration applies all tables, indexes, database triggers, and constraints cleanly, and reverses cleanly in downgrade.

## Decision

**Chosen option**: Option 1: Multi tenant shared database with application level filtering and UUIDv7 keys. Details in [rationale.md](rationale.md).

We adopt a shared multi tenant database using UUIDv7 primary keys, application layer tenant filtering on all queries, AES 256 GCM authenticated encryption for credentials, and a two tier task and task run hierarchy with dedicated sandbox execution records.

**Implementation skills**: `fastapi-templates` (`wshobson/agents`, `.agents/skills/fastapi-templates/`)

## Feature design

### Data model sketch

#### Table: `organizations`
* `id`: UUID (v7, Primary Key)
* `clerk_org_id`: VARCHAR(255) (Unique, Not Null, external Clerk organization identifier)
* `name`: VARCHAR(255) (Not Null)
* `slug`: VARCHAR(255) (Not Null)
* `github_installation_id`: BIGINT (Nullable, default GitHub App installation identifier for organization)
* `settings`: JSONB (Not Null, Default `{}`) (quotas, sandbox timeouts, default branch patterns)
* `created_at`: TIMESTAMPTZ (Not Null, Default `CURRENT_TIMESTAMP`)
* `updated_at`: TIMESTAMPTZ (Not Null, Default `CURRENT_TIMESTAMP`)
* `deleted_at`: TIMESTAMPTZ (Nullable, for soft delete)
* Partial unique index: `CREATE UNIQUE INDEX uq_organizations_slug_active ON organizations (slug) WHERE deleted_at IS NULL`

#### Table: `repositories`
* `id`: UUID (v7, Primary Key)
* `org_id`: UUID (Not Null, Foreign Key -> `organizations.id` ON DELETE CASCADE)
* `github_repo_id`: BIGINT (Not Null, external GitHub repository identifier)
* `github_installation_id`: BIGINT (Not Null, GitHub App installation identifier required for access tokens)
* `name`: VARCHAR(255) (Not Null)
* `full_name`: VARCHAR(255) (Not Null, e.g. `octocat/hello-world`)
* `default_branch`: VARCHAR(100) (Not Null, Default `main`)
* `is_private`: BOOLEAN (Not Null, Default `TRUE`)
* `config`: JSONB (Not Null, Default `{}`) (custom review instructions, spending limits, branch rules)
* `created_at`: TIMESTAMPTZ (Not Null, Default `CURRENT_TIMESTAMP`)
* `updated_at`: TIMESTAMPTZ (Not Null, Default `CURRENT_TIMESTAMP`)
* `deleted_at`: TIMESTAMPTZ (Nullable, for soft delete)
* Partial unique index: `CREATE UNIQUE INDEX uq_repositories_active ON repositories (org_id, github_repo_id) WHERE deleted_at IS NULL`
* Indexes: `(org_id, name)`, `(github_repo_id)`

#### Table: `credentials`
* `id`: UUID (v7, Primary Key)
* `org_id`: UUID (Not Null, Foreign Key -> `organizations.id` ON DELETE CASCADE)
* `repo_id`: UUID (Nullable, Foreign Key -> `repositories.id` ON DELETE CASCADE, NULL for org wide credentials)
* `name`: VARCHAR(100) (Not Null, e.g. `GITHUB_APP_TOKEN`, `ANTHROPIC_API_KEY`)
* `credential_type`: VARCHAR(50) (Not Null, e.g. `github_token`, `api_key`, `ssh_key`)
* `encrypted_data`: TEXT (Not Null, base64 encoded AES 256 GCM ciphertext concatenated with 16 byte authentication tag)
* `nonce`: TEXT (Not Null, base64 encoded 96 bit initialization vector)
* `key_version`: INTEGER (Not Null, Default 1, for key rotation support)
* `created_at`: TIMESTAMPTZ (Not Null, Default `CURRENT_TIMESTAMP`)
* `updated_at`: TIMESTAMPTZ (Not Null, Default `CURRENT_TIMESTAMP`)
* Partial unique index: `CREATE UNIQUE INDEX uq_credentials_active ON credentials (org_id, COALESCE(repo_id, '00000000-0000-0000-0000-000000000000'::uuid), name)`
* Invariant: Hard delete on revocation, no soft delete

#### Table: `tasks`
* `id`: UUID (v7, Primary Key)
* `org_id`: UUID (Not Null, Foreign Key -> `organizations.id` ON DELETE CASCADE)
* `repo_id`: UUID (Not Null, Foreign Key -> `repositories.id` ON DELETE CASCADE)
* `title`: VARCHAR(255) (Not Null)
* `description`: TEXT (Not Null)
* `status`: VARCHAR(50) (Not Null, Default `queued`) (Values: `queued`, `in_progress`, `awaiting_approval`, `completed`, `failed`, `cancelled`)
* `trigger_type`: VARCHAR(50) (Not Null) (Values: `webhook_issue`, `webhook_pr`, `manual_console`, `scheduled`)
* `trigger_metadata`: JSONB (Not Null, Default `{}`) (issue number, PR URL, requester details)
* `branch_name`: VARCHAR(255) (Nullable, work branch created by agent)
* `pr_number`: INTEGER (Nullable, pull request opened by agent)
* `created_by_clerk_user_id`: VARCHAR(255) (Nullable)
* `created_at`: TIMESTAMPTZ (Not Null, Default `CURRENT_TIMESTAMP`)
* `updated_at`: TIMESTAMPTZ (Not Null, Default `CURRENT_TIMESTAMP`)
* `deleted_at`: TIMESTAMPTZ (Nullable, for soft delete)
* Indexes: `(org_id, status, created_at DESC)`, `(repo_id, created_at DESC)`

#### Table: `task_runs`
* `id`: UUID (v7, Primary Key)
* `org_id`: UUID (Not Null, Foreign Key -> `organizations.id` ON DELETE CASCADE)
* `task_id`: UUID (Not Null, Foreign Key -> `tasks.id` ON DELETE CASCADE)
* `run_number`: INTEGER (Not Null, Default 1)
* `status`: VARCHAR(50) (Not Null, Default `pending`) (Values: `pending`, `running`, `succeeded`, `failed`, `cancelled`)
* `version`: INTEGER (Not Null, Default 1) (optimistic locking counter)
* `failure_reason`: TEXT (Nullable)
* `checkpoint_state`: JSONB (Not Null, Default `{}`) (serialized LangGraph state and memory)
* `prompt_tokens`: INTEGER (Not Null, Default 0)
* `completion_tokens`: INTEGER (Not Null, Default 0)
* `tokens_used`: INTEGER (Not Null, Default 0)
* `estimated_cost_cents`: INTEGER (Not Null, Default 0)
* `started_at`: TIMESTAMPTZ (Nullable)
* `completed_at`: TIMESTAMPTZ (Nullable)
* `created_at`: TIMESTAMPTZ (Not Null, Default `CURRENT_TIMESTAMP`)
* `updated_at`: TIMESTAMPTZ (Not Null, Default `CURRENT_TIMESTAMP`)
* Unique constraint: `(task_id, run_number)`
* Indexes: `(org_id, status, created_at DESC)`, `(task_id, status)`

#### Table: `sandbox_runs`
* `id`: UUID (v7, Primary Key)
* `org_id`: UUID (Not Null, Foreign Key -> `organizations.id` ON DELETE CASCADE)
* `task_run_id`: UUID (Not Null, Unique, Foreign Key -> `task_runs.id` ON DELETE CASCADE)
* `provider`: VARCHAR(50) (Not Null) (Values: `e2b`, `docker`)
* `sandbox_id`: VARCHAR(255) (Not Null, external E2B microVM ID or Docker container ID)
* `status`: VARCHAR(50) (Not Null, Default `allocating`) (Values: `allocating`, `active`, `terminated`, `timed_out`, `error`)
* `exit_code`: INTEGER (Nullable)
* `logs_storage_key`: VARCHAR(512) (Nullable, object storage key in S3 or Cloudflare R2)
* `memory_limit_mb`: INTEGER (Not Null, Default 2048)
* `timeout_seconds`: INTEGER (Not Null, Default 600)
* `allocated_at`: TIMESTAMPTZ (Nullable)
* `terminated_at`: TIMESTAMPTZ (Nullable)
* `created_at`: TIMESTAMPTZ (Not Null, Default `CURRENT_TIMESTAMP`)
* `updated_at`: TIMESTAMPTZ (Not Null, Default `CURRENT_TIMESTAMP`)
* Indexes: `(org_id, status)`, `(sandbox_id)`, `(status, created_at)`

#### Table: `audit_logs`
* `id`: UUID (v7, Primary Key)
* `org_id`: UUID (Not Null, Foreign Key -> `organizations.id` ON DELETE RESTRICT)
* `actor_type`: VARCHAR(50) (Not Null) (Values: `user`, `agent`, `webhook`, `system`)
* `actor_id`: VARCHAR(255) (Not Null, Clerk user ID or system worker name)
* `action`: VARCHAR(100) (Not Null, e.g. `task.created`, `task.cancelled`, `credential.rotated`, `repo.linked`)
* `target_type`: VARCHAR(50) (Not Null, e.g. `task`, `task_run`, `repository`, `credential`, `organization`)
* `target_id`: UUID (Not Null)
* `payload_before`: JSONB (Nullable)
* `payload_after`: JSONB (Nullable)
* `ip_address`: VARCHAR(45) (Nullable)
* `created_at`: TIMESTAMPTZ (Not Null, Default `CURRENT_TIMESTAMP`)
* Indexes: `(org_id, created_at DESC)`, `(target_type, target_id)`
* Invariant: Immutable append only. A PostgreSQL database trigger blocks any `UPDATE` or `DELETE` statements on this table.

### State transitions

#### Task state machine
* `queued` -> `in_progress` (worker picks up task and initializes sandbox)
* `in_progress` -> `awaiting_approval` (agent needs human confirmation for high risk action or budget cap)
* `awaiting_approval` -> `in_progress` (user approves in web console)
* `in_progress` -> `completed` (verified code and pull request created)
* `in_progress` -> `failed` (tests fail or unrecoverable error occurs)
* Any active state -> `cancelled` (user cancels task from web console)

#### TaskRun state machine
* `pending` -> `running` (LangGraph graph invocation starts)
* `running` -> `succeeded` (graph reaches end node successfully)
* `running` -> `failed` (graph throws unhandled exception or hits iteration ceiling)
* `running` -> `cancelled` (cancellation flag received from Redis bus)

#### SandboxRun state machine
* `allocating` -> `active` (microVM provisioned and SSH or API ready)
* `active` -> `terminated` (run finished, sandbox destroyed cleanly)
* `active` -> `timed_out` (execution duration exceeded timeout limit)
* `allocating` or `active` -> `error` (VM creation failure or hardware fault)

### API surface

The database layer interfaces with application use cases via repository protocols in `apps/agent` and read schemas in `apps/web`:

| Port / Interface | Method / Query | Key inputs | Key outputs | Auth / Context | Key errors |
|---|---|---|---|---|---|
| `OrganizationRepository` | `get_by_clerk_id` | `clerk_org_id: str` | `Organization` entity | Internal service | `NotFoundError` |
| `OrganizationRepository` | `create_or_update` | `clerk_org_id: str`, `name: str`, `slug: str`, `installation_id: int?` | `Organization` entity | Internal service | `ConflictError`, `ValidationError` |
| `RepositoryRepository` | `create` | `org_id: UUID`, `github_repo_id: int`, `installation_id: int`, `name: str`, `full_name: str` | `Repository` entity | Authenticated org | `ConflictError`, `ValidationError` |
| `RepositoryRepository` | `get_by_id` | `org_id: UUID`, `repo_id: UUID` | `Repository` entity | Authenticated org | `NotFoundError` |
| `RepositoryRepository` | `get_by_github_id` | `org_id: UUID`, `github_repo_id: int` | `Repository` entity | Authenticated org | `NotFoundError` |
| `RepositoryRepository` | `list_by_org` | `org_id: UUID`, `page: int`, `page_size: int` | `list[Repository]`, `total: int` | Authenticated org | `ValidationError` |
| `RepositoryRepository` | `soft_delete` | `org_id: UUID`, `repo_id: UUID` | `None` | Authenticated admin | `NotFoundError` |
| `TaskRepository` | `create_task` | `org_id: UUID`, `repo_id: UUID`, `title: str`, `desc: str`, `trigger: str`, `meta: dict`, `user_id: str?` | `Task` entity | Authenticated org | `NotFoundError`, `ValidationError` |
| `TaskRepository` | `get_by_id` | `org_id: UUID`, `task_id: UUID` | `Task` entity | Authenticated org | `NotFoundError` |
| `TaskRepository` | `list_by_repo` | `org_id: UUID`, `repo_id: UUID`, `page: int`, `page_size: int` | `list[Task]`, `total: int` | Authenticated org | `ValidationError` |
| `TaskRepository` | `update_status` | `org_id: UUID`, `task_id: UUID`, `status: str`, `branch: str?`, `pr: int?` | `Task` entity | Authenticated org | `NotFoundError`, `InvalidStateTransitionError` |
| `TaskRepository` | `soft_delete` | `org_id: UUID`, `task_id: UUID` | `None` | Authenticated admin | `NotFoundError` |
| `TaskRunRepository` | `create_run` | `org_id: UUID`, `task_id: UUID` (with row lock on task) | `TaskRun` entity | Worker engine | `ConflictError`, `NotFoundError` |
| `TaskRunRepository` | `get_by_id` | `org_id: UUID`, `task_run_id: UUID` | `TaskRun` entity | Worker engine | `NotFoundError` |
| `TaskRunRepository` | `update_checkpoint` | `org_id: UUID`, `task_run_id: UUID`, `state: dict`, `expected_version: int` | `TaskRun` entity | Worker engine | `ConcurrencyError`, `NotFoundError` |
| `TaskRunRepository` | `complete_run` | `org_id: UUID`, `task_run_id: UUID`, `status: str`, `prompt_tokens: int`, `completion_tokens: int`, `cost_cents: int`, `failure: str?` | `TaskRun` entity | Worker engine | `NotFoundError` |
| `SandboxRunRepository` | `record_allocation` | `org_id: UUID`, `task_run_id: UUID`, `provider: str`, `sandbox_id: str`, `mem_mb: int`, `timeout: int` | `SandboxRun` entity | Worker engine | `ConflictError` |
| `SandboxRunRepository` | `get_by_task_run_id` | `org_id: UUID`, `task_run_id: UUID` | `SandboxRun` entity | Worker engine | `NotFoundError` |
| `SandboxRunRepository` | `record_termination` | `org_id: UUID`, `sandbox_run_id: UUID`, `exit_code: int`, `logs_key: str` | `SandboxRun` entity | Worker engine | `NotFoundError` |
| `CredentialRepository` | `store_secret` | `org_id: UUID`, `name: str`, `cred_type: str`, `plaintext: str`, `repo_id: UUID?` | `Credential` metadata | Authenticated admin | `ValidationError` |
| `CredentialRepository` | `retrieve_secret` | `org_id: UUID`, `name: str`, `repo_id: UUID?` | `str` (decrypted plaintext) | Worker engine | `NotFoundError`, `DecryptionError` |
| `CredentialRepository` | `list_by_org` | `org_id: UUID` | `list[CredentialMetadata]` | Authenticated admin | `ValidationError` |
| `CredentialRepository` | `revoke_secret` | `org_id: UUID`, `credential_id: UUID` | `None` | Authenticated admin | `NotFoundError` |
| `AuditLogRepository` | `record_event` | `org_id: UUID`, `actor_type: str`, `actor_id: str`, `action: str`, `target_type: str`, `target_id: UUID`, `before: dict?`, `after: dict?` | `AuditLog` entity | Internal service | `ValidationError` |
| `AuditLogRepository` | `list_events` | `org_id: UUID`, `page: int`, `page_size: int`, `target_type: str?` | `list[AuditLog]`, `total: int` | Authenticated admin | `ValidationError` |

### Value sourcing

| Action | Value produced or displayed | Source |
|---|---|---|
| Create organization | `clerk_org_id` | Clerk webhook payload or Clerk session claims |
| Create organization | `id` | Client generated UUIDv7 via `uuid-utils` |
| Link repository | `github_repo_id`, `full_name`, `github_installation_id` | GitHub App API or webhook repository payload |
| Link repository | `org_id` | Active tenant context resolved from Clerk claims |
| Store credential | `encrypted_data`, `nonce` | In memory AES 256 GCM encryption using `CREDENTIALS_ENCRYPTION_KEY`, appending 16 byte tag |
| Create task | `id`, `org_id`, `repo_id` | Client generated UUIDv7, active tenant context, target repository ID |
| Create task run | `run_number` | Derived inside transaction after `SELECT id FROM tasks WHERE id = :task_id FOR UPDATE` |
| Update checkpoint | `checkpoint_state` | Serialized LangGraph state dictionary from ARQ worker |
| Complete run | `prompt_tokens`, `completion_tokens`, `estimated_cost_cents` | Aggregated from LLM invocation callback metrics and model pricing table |
| Allocate sandbox | `sandbox_id` | ID returned by E2B SDK or Docker container runtime |
| Terminate sandbox | `logs_storage_key` | Computed S3 key pattern `logs/{org_id}/{task_id}/{task_run_id}.log` |
| Record audit log | `payload_before`, `payload_after` | Entity state snapshot before and after mutation |

### Key invariants

* **Tenant confinement**: Every user query and agent worker mutation must filter by `org_id`. Cross tenant updates are impossible without explicitly supplying a mismatched foreign key.
* **Audit immutability**: Records in `audit_logs` are write once and append only. A PostgreSQL database trigger raises an exception on any `UPDATE` or `DELETE` attempt. Foreign keys to organizations use `ON DELETE RESTRICT` to prevent accidental history pruning.
* **Safe soft deletion**: Unique constraints on repositories, organizations, and credentials use partial indexes filtered with `WHERE deleted_at IS NULL`, allowing deleted entities to be re linked cleanly.
* **Sequential run lock**: Task run creation executes `SELECT id FROM tasks WHERE id = :task_id FOR UPDATE` before incrementing run number, preventing race conditions under concurrent triggers.
* **One sandbox per run**: Each `task_runs` record binds to at most one `sandbox_runs` record via an explicit unique constraint on `task_run_id`.
* **Zero plaintext at rest**: Plaintext credentials are never written to database tables, logs, or telemetry buses. Decryption occurs only in memory immediately before consumption.
* **Optimistic concurrency**: Task run updates verify `version = expected_version` to prevent split brain state writes when workers experience network partitioning.

### Security model

* **Tenant separation**: Authentication is validated via Clerk JWKS tokens. The verified `org_id` claim is injected into database queries via FastAPI dependencies.
* **Encryption standard**: Sensitive credentials are encrypted using AES 256 GCM with 96 bit initialization vectors and 128 bit authentication tags. Ciphertext and tag are stored together as base64 in `encrypted_data`. Master keys are supplied via environment variables and never stored in the database.
* **Authorization scoping**: Organization members can view tasks, repositories, and audit logs. Only organization admins can store, view metadata for, or revoke credentials. Agent workers execute with service level database permissions to write checkpoints and sandbox records.

### Configuration required

* `DATABASE_URL`: PostgreSQL connection string with asyncpg driver (e.g. `postgresql+asyncpg://user:pass@localhost:5432/agentsonair`).
* `CREDENTIALS_ENCRYPTION_KEY`: 32 byte base64 encoded cryptographic key used for AES 256 GCM credential encryption.

### Critical test scenarios

* **Happy path**: Organization links repository, creates task, executes two sequential task runs with checkpoint persistence, binds sandbox records, and logs audit events, verifies **AC-1**, **AC-3**, **AC-4**, **AC-6**.
* **Tenant isolation**: Attempting to query or update tasks belonging to Organization A using Organization B tenant context returns not found and alters zero rows, verifies **AC-2**.
* **Credential encryption and tampering**: Storing a repository token writes encrypted ciphertext and nonce, decodes successfully with the correct master key, and raises decryption error if ciphertext or authentication tag is tampered with, verifies **AC-5**.
* **Optimistic concurrency**: Concurrent workers attempting to update `task_runs.checkpoint_state` with the same version counter results in one successful commit and one rejected write, verifies **AC-3**.
* **Run number lock**: Concurrent workers creating runs for the same task acquire row locks and receive sequential `run_number`s 1 and 2 without constraint collision, verifies **AC-3**.
* **Audit immutability**: Direct SQL update or delete statements executed against `audit_logs` fail due to database trigger enforcement, verifies **AC-6**.
* **Soft delete and re link**: Soft deleting a repository allows a new repository with the same `github_repo_id` to be linked without partial index collision, verifies **AC-7**.
* **Migration consistency**: Executing Alembic `upgrade head` on an empty database followed by `downgrade base` and another `upgrade head` leaves the database schema intact without errors, verifies **AC-8**.

## Build plan

- [x] 1. Add `uuid-utils` and `cryptography` dependencies to `apps/agent/pyproject.toml`, and implement UUIDv7 utility and declarative base with timestamp mixins in `apps/agent/app/infrastructure/db/base.py`, satisfies **AC-1**
- [x] 2. Implement cryptographic utility service providing AES 256 GCM authenticated encryption and decryption with nonce generation and tag verification in `apps/agent/app/core/security.py`, satisfies **AC-5**
- [x] 3. Define SQLAlchemy 2.0 declarative models for `organizations`, `repositories`, `credentials`, `tasks`, `task_runs`, `sandbox_runs`, and `audit_logs` with partial unique indexes and tenant foreign keys in `apps/agent/app/infrastructure/db/models/`, satisfies **AC-1**, **AC-2**, **AC-3**, **AC-4**, **AC-5**, **AC-6**, **AC-7**
- [x] 4. Generate initial Alembic migration script in `apps/agent/alembic/versions/` creating tables, partial indexes, and immutability triggers on `audit_logs`, verifying both upgrade and downgrade cycles, satisfies **AC-1**, **AC-6**, **AC-7**, **AC-8**
- [x] 5. Define Clean Architecture domain entities and repository abstract protocols in `apps/agent/app/domain/` and `apps/agent/app/application/ports/`, satisfies **AC-2**, **AC-3**, **AC-6**
- [x] 6. Implement async SQLAlchemy repository adapters with row locking, tenant isolation filtering, and optimistic locking in `apps/agent/app/infrastructure/db/repositories/`, satisfies **AC-2**, **AC-3**, **AC-6**, **AC-7**
- [x] 7. Configure Drizzle ORM read schema definitions in `apps/web/src/db/schema.ts` matching the generated PostgreSQL tables and partial indexes, satisfies **AC-1**, **AC-2**
- [x] 8. Create comprehensive pytest integration test suite verifying migration cycles, tenant isolation boundaries, secret encryption, run locks, and immutability triggers, satisfies **AC-1**, **AC-2**, **AC-3**, **AC-5**, **AC-6**, **AC-7**, **AC-8**

## Consequences

**Positive**:
* Shared schema with UUIDv7 delivers high write performance, natural chronological sorting, and predictable B tree index behavior.
* Explicit `org_id` on all execution tables guarantees airtight tenant filtering and allows high throughput composite indexing without multi table joins.
* Clear two tier task and run model isolates high level user intent from granular agent graph execution cycles and microVM lifecycles.
* Client generated UUIDs allow workers to construct complete graph checkpoint graphs and sandbox records in memory before round trips.
* Hardware credentials are protected with authenticated AES 256 GCM encryption at rest, preventing credential leakage during database snapshot exports.
* Append only audit log with database trigger enforcement establishes immediate SOC2 and security compliance readiness.
* Partial unique indexes support clean soft deletion without permanently burning repository IDs or organization slugs.

**Negative / tradeoffs**:
* Application layer tenant filtering requires strict discipline across all queries; omitting an `org_id` filter could lead to cross tenant data access.
* Storing LangGraph checkpoint state in PostgreSQL JSONB requires careful monitoring to ensure state payloads do not exceed reasonable row sizes over hundreds of graph iterations.

**Neutral**:
* Web console reads require keeping Drizzle ORM schemas in sync with Alembic database migrations.
* Key rotation for encrypted credentials requires a future background re encryption task when master keys are updated.

## Follow-up

* [ ] Add automated continuous integration check running `drizzle-kit introspect` to verify `apps/web` Drizzle schemas match `apps/agent` Alembic migrations.
* [ ] Configure PostgreSQL backup retention policies and point in time recovery in staging and production environments.
