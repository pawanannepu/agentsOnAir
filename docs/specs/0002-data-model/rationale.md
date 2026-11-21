# 0002. Data model for tenant isolation, task execution, and credentials: rationale

**Date**: 2026-11-22
**Status**: In Progress

## Context

agentsOnAir orchestrates autonomous software engineering workflows where agents write code, execute tests inside hardware isolated sandboxes, and submit pull requests. To deliver this safely, the persistence layer must balance several competing demands.

First, multi tenancy is fundamental. Codebases, tasks, secrets, and audit events belonging to one organization must never leak to another. Organization identity originates in Clerk, which handles authentication, user memberships, and organization metadata. The database needs a consistent way to tie every repository, task, execution run, and credential to a verified organization without introducing the connection pool exhaustion and migration overhead of running separate schemas for every tenant.

Second, agent execution is iterative and failure prone. A single user request or GitHub issue trigger can spark multiple attempts, retries, and human interventions. LangGraph agent graphs produce rich state checkpoints, token usage figures, and tool outputs that must survive worker crashes or worker restarts. Furthermore, each execution attempt binds directly to an isolated microVM sandbox session whose allocation status, provider details, and container logs must be tracked for cost accounting and debugging.

Third, security and compliance are non negotiable. Agents require access to GitHub App installation tokens, repository deploy keys, and model API keys. Storing these secrets in plaintext in the database is unacceptable. At the same time, enterprise users require an immutable audit trail capturing every privileged action, credential rotation, and task creation event.

Deciding this schema early prevents costly table refactoring and breaking migrations once background workers and web console interfaces are implemented.

## Options considered

### Option 1: Multi tenant shared database with application level filtering and UUIDv7 keys

A single PostgreSQL database where every table carries an `org_id` column linking back to the root organization. The application layer in `apps/agent` enforces tenant filtering across all repository queries. Primary keys use UUIDv7 (timestamp ordered 128 bit identifiers) generated before insertion. Credentials live in a dedicated table encrypted with AES 256 GCM.

**Pros**:
* Simple connection pooling through standard PgBouncer setups with no transaction overhead from session variable configuration.
* UUIDv7 provides natural time ordering, preserving B tree index locality and preventing sequential enumeration vulnerabilities.
* Streamlined migration workflow where Alembic updates one schema rather than running hundreds of tenant migrations.

**Cons**:
* Relies on application layer discipline to append `WHERE org_id = :org_id` filters, requiring strict repository patterns to avoid accidental data leakage.

### Option 2: PostgreSQL Row Level Security (RLS) with transaction session variables

A shared database schema where PostgreSQL Row Level Security policies restrict read and write access based on a session variable (such as `SET LOCAL app.current_org_id = '...'`) executed on every database transaction.

**Pros**:
* Defense in depth at the database engine level, blocking cross tenant data access even if an application query omits an organization filter.

**Cons**:
* Adds latency to every database transaction by requiring a setup query before executing application SQL.
* Complicates connection poolers operating in transaction mode, creating risks of session state leaking between pooled connections if not reset cleanly.

### Option 3: Schema per tenant isolation

Each organization receives its own dedicated PostgreSQL schema inside a shared database cluster, isolating tables and data completely at the namespace level.

**Pros**:
* Strong physical namespace isolation between tenants, simplifying regulatory audits and custom schema adaptations.

**Cons**:
* Massive operational complexity when running schema migrations across hundreds of tenant schemas.
* Substantial memory consumption in PostgreSQL catalog caches and connection pooling pools.

## Rationale

Option 1 provides the highest developer velocity, cleanest operational footprint, and lowest latency for our async Python backend. PostgreSQL 16 easily handles multi tenant shared tables when appropriate composite indexes are in place. Using UUIDv7 generated on the client in `apps/agent` allows workers to create related entity IDs in memory before executing database inserts, which is critical when assembling complex LangGraph checkpoint structures and sandbox sessions.

While Row Level Security (Option 2) provides defense in depth, running `SET LOCAL` commands on pooled asyncpg connections introduces connection pool edge cases and transaction friction. Schema per tenant (Option 3) creates a maintenance nightmare when deploying Alembic migrations in continuous integration. By combining strict Clean Architecture repository protocols in `apps/agent` with required `org_id` parameters on all repository methods, we achieve robust tenant isolation with minimal operational overhead.
