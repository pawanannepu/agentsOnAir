# Verify: data model · spec 0002 · updated 2026-11-22
_Steps derived from spec 0002 acceptance criteria. `/check verify` runs these; `/test` locks the durable ones._

## UI / manual
- [x] Connect with database viewer tool → verify seven tables exist with UUIDv7 primary keys and foreign keys → AC-1
- [x] Direct SQL update on audit_logs table → fails with immutability trigger exception → AC-6
- [x] Direct SQL delete on audit_logs table → fails with immutability trigger exception → AC-6
- [x] Inspect raw database records in credentials table → encrypted_data and nonce are base64 strings with zero plaintext secrets → AC-5

## Commands
- [x] `cd apps/agent && uv run alembic upgrade head` → applies initial migration cleanly → AC-1, AC-8
- [x] `cd apps/agent && uv run alembic downgrade base && uv run alembic upgrade head` → verifies full migration cycle reversibility → AC-8
- [x] `cd apps/agent && uv run pytest` → runs 16 integration tests verifying tenant isolation, run locking, optimistic concurrency, and soft delete → AC-1, AC-2, AC-3, AC-4, AC-5, AC-6, AC-7
- [x] `pnpm --filter web typecheck` → verifies Drizzle ORM read schemas match the database schema → AC-1, AC-2

## Value sourcing
- [x] Organization creation stores Clerk organization ID from Clerk claims → AC-1, AC-2
- [x] Storing credential creates unique nonce and authenticated ciphertext with AES 256 GCM → AC-5
- [x] Task run creation locks parent task row and increments run number sequentially → AC-3
- [x] Checkpoint update checks version equality and increments version counter → AC-3
- [x] Terminating sandbox persists log storage key and exit code → AC-4
- [x] Audit log appends before and after JSONB payloads with restrict foreign key → AC-6

## Acceptance-criteria coverage
- AC-1 core relational entities with UUIDv7 covered by migration and Drizzle schema
- AC-2 tenant isolation covered by repository tenant queries and pytest isolation tests
- AC-3 task runs with LangGraph checkpoints and versioning covered by task_run repository
- AC-4 sandbox runs bound to task runs covered by sandbox_run repository
- AC-5 AES 256 GCM encrypted credentials covered by security service and credential repository
- AC-6 immutable audit logs with trigger covered by database trigger and pytest
- AC-7 soft deletion and re-linking covered by partial unique indexes and repository tests
- AC-8 single clean Alembic migration covered by migration upgrade and downgrade tests
