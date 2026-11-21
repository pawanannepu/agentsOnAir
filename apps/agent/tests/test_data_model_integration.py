"""Integration tests for core data models, repositories, and invariants.

Covers:
- AC-1: Relational entities and UUIDv7 primary keys
- AC-2: Strict tenant isolation across repositories
- AC-3: Sequential task run lock and optimistic concurrency on checkpoints
- AC-4: SandboxRun binding to TaskRun
- AC-5: Encrypted credentials at rest
- AC-6: Append-only audit logs with PostgreSQL database trigger immutability
- AC-7: Soft delete and partial unique index re-linking
"""

import uuid

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.domain.exceptions import (
    ConcurrencyError,
    ConflictError,
    NotFoundError,
)
from app.infrastructure.db.base import uuid7
from app.infrastructure.db.repositories.audit_log_repository import (
    SqlAlchemyAuditLogRepository,
)
from app.infrastructure.db.repositories.credential_repository import (
    SqlAlchemyCredentialRepository,
)
from app.infrastructure.db.repositories.organization_repository import (
    SqlAlchemyOrganizationRepository,
)
from app.infrastructure.db.repositories.repository_repository import (
    SqlAlchemyRepositoryRepository,
)
from app.infrastructure.db.repositories.sandbox_run_repository import (
    SqlAlchemySandboxRunRepository,
)
from app.infrastructure.db.repositories.task_repository import (
    SqlAlchemyTaskRepository,
)
from app.infrastructure.db.repositories.task_run_repository import (
    SqlAlchemyTaskRunRepository,
)


@pytest.mark.asyncio
async def test_full_lifecycle_happy_path(db_session: AsyncSession):
    """Verify full lifecycle across all core entities (AC-1, AC-3, AC-4, AC-6)."""
    org_repo = SqlAlchemyOrganizationRepository(db_session)
    repo_repo = SqlAlchemyRepositoryRepository(db_session)
    task_repo = SqlAlchemyTaskRepository(db_session)
    run_repo = SqlAlchemyTaskRunRepository(db_session)
    sandbox_repo = SqlAlchemySandboxRunRepository(db_session)
    audit_repo = SqlAlchemyAuditLogRepository(db_session)

    # 1. Create Organization
    clerk_id = f"org_{uuid.uuid4().hex[:12]}"
    slug = f"acme-{uuid.uuid4().hex[:8]}"
    org = await org_repo.create_or_update(
        clerk_org_id=clerk_id,
        name="Acme Corp",
        slug=slug,
        github_installation_id=12345,
    )
    assert org.id is not None
    assert org.clerk_org_id == clerk_id

    # 2. Link Repository
    github_repo_id = int(uuid.uuid4().int % 10000000)
    repo = await repo_repo.create(
        org_id=org.id,
        github_repo_id=github_repo_id,
        github_installation_id=12345,
        name="backend-api",
        full_name="acme/backend-api",
        default_branch="main",
        is_private=True,
    )
    assert repo.org_id == org.id

    # 3. Create Task
    task = await task_repo.create_task(
        org_id=org.id,
        repo_id=repo.id,
        title="Refactor auth flow",
        description="Migrate session auth to Clerk JWT",
        trigger_type="manual_console",
    )
    assert task.status == "queued"

    # 4. Create TaskRun (run 1)
    run1 = await run_repo.create_run(org_id=org.id, task_id=task.id)
    assert run1.run_number == 1
    assert run1.version == 1

    # 5. Update Checkpoint
    checkpoint = {"node": "review_diff", "iteration": 1}
    run1_updated = await run_repo.update_checkpoint(
        org_id=org.id,
        task_run_id=run1.id,
        checkpoint_state=checkpoint,
        expected_version=1,
    )
    assert run1_updated.version == 2
    assert run1_updated.checkpoint_state == checkpoint

    # 6. Allocate SandboxRun
    sandbox = await sandbox_repo.record_allocation(
        org_id=org.id,
        task_run_id=run1.id,
        provider="e2b",
        sandbox_id="sbx-e2b-abc123xyz",
        memory_limit_mb=4096,
        timeout_seconds=900,
    )
    assert sandbox.status == "active"
    assert sandbox.memory_limit_mb == 4096

    # 7. Terminate Sandbox
    terminated = await sandbox_repo.record_termination(
        org_id=org.id,
        sandbox_run_id=sandbox.id,
        exit_code=0,
        logs_storage_key="logs/acme/task1/run1.log",
    )
    assert terminated.status == "terminated"
    assert terminated.exit_code == 0

    # 8. Complete Run
    completed = await run_repo.complete_run(
        org_id=org.id,
        task_run_id=run1.id,
        status="succeeded",
        prompt_tokens=1500,
        completion_tokens=400,
        estimated_cost_cents=12,
    )
    assert completed.status == "succeeded"
    assert completed.tokens_used == 1900

    # 9. Create Sequential TaskRun (run 2)
    run2 = await run_repo.create_run(org_id=org.id, task_id=task.id)
    assert run2.run_number == 2

    # 10. Record Audit Event
    audit = await audit_repo.record_event(
        org_id=org.id,
        actor_type="agent",
        actor_id="worker-01",
        action="task.completed",
        target_type="task",
        target_id=task.id,
        payload_after={"status": "completed"},
    )
    assert audit.action == "task.completed"

    events, total = await audit_repo.list_events(org_id=org.id)
    assert total >= 1
    assert any(e.id == audit.id for e in events)


@pytest.mark.asyncio
async def test_tenant_isolation(db_session: AsyncSession):
    """Verify cross-tenant data access is blocked by tenant scoping (covers: AC-2)."""
    org_repo = SqlAlchemyOrganizationRepository(db_session)
    repo_repo = SqlAlchemyRepositoryRepository(db_session)
    task_repo = SqlAlchemyTaskRepository(db_session)

    # Org A
    org_a = await org_repo.create_or_update(
        clerk_org_id=f"org_a_{uuid.uuid4().hex[:8]}",
        name="Org A",
        slug=f"org-a-{uuid.uuid4().hex[:8]}",
    )
    # Org B
    org_b = await org_repo.create_or_update(
        clerk_org_id=f"org_b_{uuid.uuid4().hex[:8]}",
        name="Org B",
        slug=f"org-b-{uuid.uuid4().hex[:8]}",
    )

    # Org A repo and task
    repo_a = await repo_repo.create(
        org_id=org_a.id,
        github_repo_id=int(uuid.uuid4().int % 10000000),
        github_installation_id=111,
        name="repo-a",
        full_name="org-a/repo-a",
    )
    task_a = await task_repo.create_task(
        org_id=org_a.id,
        repo_id=repo_a.id,
        title="Secret Task A",
        description="Confidential code",
        trigger_type="manual_console",
    )

    # Org B attempts to read Org A repo
    with pytest.raises(NotFoundError):
        await repo_repo.get_by_id(org_id=org_b.id, repo_id=repo_a.id)

    # Org B attempts to read Org A task
    with pytest.raises(NotFoundError):
        await task_repo.get_by_id(org_id=org_b.id, task_id=task_a.id)

    # Org B lists tasks for repo_a
    tasks_b, total_b = await task_repo.list_by_repo(org_id=org_b.id, repo_id=repo_a.id)
    assert total_b == 0
    assert len(tasks_b) == 0


@pytest.mark.asyncio
async def test_credentials_encryption_and_revocation(db_session: AsyncSession):
    """Verify AES-256-GCM encryption at rest and revocation (covers: AC-5)."""
    org_repo = SqlAlchemyOrganizationRepository(db_session)
    cred_repo = SqlAlchemyCredentialRepository(db_session)

    org = await org_repo.create_or_update(
        clerk_org_id=f"org_{uuid.uuid4().hex[:8]}",
        name="Security Corp",
        slug=f"sec-corp-{uuid.uuid4().hex[:8]}",
    )

    secret_value = "ghp_secure_github_personal_token_xyz987"
    cred_meta = await cred_repo.store_secret(
        org_id=org.id,
        name="GITHUB_TOKEN",
        credential_type="github_token",
        plaintext=secret_value,
    )
    assert cred_meta.name == "GITHUB_TOKEN"
    assert cred_meta.key_version == 1

    # Verify plain text is not stored in DB raw column
    raw_stmt = text("SELECT encrypted_data, nonce FROM credentials WHERE id = :cred_id")
    raw_row = (await db_session.execute(raw_stmt, {"cred_id": cred_meta.id})).fetchone()
    assert raw_row is not None
    assert raw_row[0] != secret_value
    assert secret_value not in raw_row[0]

    # Retrieve decrypted secret
    retrieved = await cred_repo.retrieve_secret(org_id=org.id, name="GITHUB_TOKEN")
    assert retrieved == secret_value

    # Revoke (hard delete)
    await cred_repo.revoke_secret(org_id=org.id, credential_id=cred_meta.id)

    with pytest.raises(NotFoundError):
        await cred_repo.retrieve_secret(org_id=org.id, name="GITHUB_TOKEN")


@pytest.mark.asyncio
async def test_optimistic_concurrency_conflict(db_session: AsyncSession):
    """Verify optimistic concurrency raises ConcurrencyError (covers: AC-3)."""
    org_repo = SqlAlchemyOrganizationRepository(db_session)
    repo_repo = SqlAlchemyRepositoryRepository(db_session)
    task_repo = SqlAlchemyTaskRepository(db_session)
    run_repo = SqlAlchemyTaskRunRepository(db_session)

    org = await org_repo.create_or_update(
        clerk_org_id=f"org_{uuid.uuid4().hex[:8]}",
        name="Concurrency Corp",
        slug=f"concurrent-{uuid.uuid4().hex[:8]}",
    )
    repo = await repo_repo.create(
        org_id=org.id,
        github_repo_id=int(uuid.uuid4().int % 10000000),
        github_installation_id=555,
        name="test-repo",
        full_name="concurrent/test-repo",
    )
    task = await task_repo.create_task(
        org_id=org.id,
        repo_id=repo.id,
        title="Concurrent task",
        description="Testing concurrency",
        trigger_type="manual_console",
    )

    run = await run_repo.create_run(org_id=org.id, task_id=task.id)
    assert run.version == 1

    # First update succeeds (expected_version=1 -> version becomes 2)
    await run_repo.update_checkpoint(
        org_id=org.id,
        task_run_id=run.id,
        checkpoint_state={"step": 1},
        expected_version=1,
    )

    # Stale second worker using expected_version=1 must fail
    with pytest.raises(ConcurrencyError, match="conflict"):
        await run_repo.update_checkpoint(
            org_id=org.id,
            task_run_id=run.id,
            checkpoint_state={"step": 2},
            expected_version=1,
        )


@pytest.mark.asyncio
async def test_audit_logs_immutability_trigger(db_session: AsyncSession):
    """Verify database trigger rejects UPDATE and DELETE on audit_logs (AC-6)."""
    org_repo = SqlAlchemyOrganizationRepository(db_session)
    audit_repo = SqlAlchemyAuditLogRepository(db_session)

    org = await org_repo.create_or_update(
        clerk_org_id=f"org_{uuid.uuid4().hex[:8]}",
        name="Audit Compliance Org",
        slug=f"audit-org-{uuid.uuid4().hex[:8]}",
    )
    # Commit organization so it survives transaction rollback
    await db_session.commit()

    audit_entry = await audit_repo.record_event(
        org_id=org.id,
        actor_type="user",
        actor_id="user_clerk_123",
        action="repository.linked",
        target_type="repository",
        target_id=uuid7(),
    )
    await db_session.flush()

    # Attempt direct UPDATE via SQL
    update_stmt = text("UPDATE audit_logs SET action = 'tampered' WHERE id = :id")
    with pytest.raises(Exception, match="immutable and append-only"):
        await db_session.execute(update_stmt, {"id": audit_entry.id})

    # Rollback aborted transaction to test DELETE separately
    await db_session.rollback()

    # Create fresh entry for DELETE test
    audit_entry2 = await audit_repo.record_event(
        org_id=org.id,
        actor_type="user",
        actor_id="user_clerk_123",
        action="repository.deleted",
        target_type="repository",
        target_id=uuid7(),
    )
    await db_session.flush()

    # Attempt direct DELETE via SQL
    delete_stmt = text("DELETE FROM audit_logs WHERE id = :id")
    with pytest.raises(Exception, match="immutable and append-only"):
        await db_session.execute(delete_stmt, {"id": audit_entry2.id})


@pytest.mark.asyncio
async def test_soft_delete_and_relink_repository(db_session: AsyncSession):
    """Verify soft deleting allows re-linking same github_repo_id (covers: AC-7)."""
    org_repo = SqlAlchemyOrganizationRepository(db_session)
    repo_repo = SqlAlchemyRepositoryRepository(db_session)

    org = await org_repo.create_or_update(
        clerk_org_id=f"org_{uuid.uuid4().hex[:8]}",
        name="Soft Delete Org",
        slug=f"soft-org-{uuid.uuid4().hex[:8]}",
    )

    github_repo_id = 987654321

    # First link
    repo1 = await repo_repo.create(
        org_id=org.id,
        github_repo_id=github_repo_id,
        github_installation_id=123,
        name="my-service",
        full_name="soft-org/my-service",
    )

    # Duplicate link while active should fail with ConflictError
    with pytest.raises(ConflictError):
        await repo_repo.create(
            org_id=org.id,
            github_repo_id=github_repo_id,
            github_installation_id=123,
            name="my-service-dup",
            full_name="soft-org/my-service-dup",
        )

    # Soft delete repo1
    await repo_repo.soft_delete(org_id=org.id, repo_id=repo1.id)

    # Re-link same github_repo_id should succeed because repo1 is soft-deleted
    repo2 = await repo_repo.create(
        org_id=org.id,
        github_repo_id=github_repo_id,
        github_installation_id=123,
        name="my-service",
        full_name="soft-org/my-service",
    )
    assert repo2.id != repo1.id
    assert repo2.deleted_at is None


@pytest.mark.asyncio
async def test_credential_rotation_and_repo_scoping(db_session: AsyncSession):
    """Verify secret update increments key version and repo scoping (AC 5)."""
    org_repo = SqlAlchemyOrganizationRepository(db_session)
    repo_repo = SqlAlchemyRepositoryRepository(db_session)
    cred_repo = SqlAlchemyCredentialRepository(db_session)

    org = await org_repo.create_or_update(
        clerk_org_id=f"org_rot_{uuid.uuid4().hex[:8]}",
        name="Rotation Org",
        slug=f"rot-org-{uuid.uuid4().hex[:8]}",
    )
    repo = await repo_repo.create(
        org_id=org.id,
        github_repo_id=int(uuid.uuid4().int % 10000000),
        github_installation_id=777,
        name="rot-repo",
        full_name="rot-org/rot-repo",
    )

    # 1. Store initial org wide secret (key version 1)
    cred1 = await cred_repo.store_secret(
        org_id=org.id,
        name="DEPLOY_KEY",
        credential_type="ssh_key",
        plaintext="initial_ssh_key_payload",
    )
    assert cred1.key_version == 1
    val1 = await cred_repo.retrieve_secret(org_id=org.id, name="DEPLOY_KEY")
    assert val1 == "initial_ssh_key_payload"

    # 2. Update same secret name (key version rotates to 2)
    cred2 = await cred_repo.store_secret(
        org_id=org.id,
        name="DEPLOY_KEY",
        credential_type="ssh_key",
        plaintext="rotated_ssh_key_payload",
    )
    assert cred2.id == cred1.id
    assert cred2.key_version == 2
    val2 = await cred_repo.retrieve_secret(org_id=org.id, name="DEPLOY_KEY")
    assert val2 == "rotated_ssh_key_payload"

    # 3. Store repo scoped secret with identical name (coexists)
    cred_repo_scoped = await cred_repo.store_secret(
        org_id=org.id,
        name="DEPLOY_KEY",
        credential_type="ssh_key",
        plaintext="repo_specific_ssh_key",
        repo_id=repo.id,
    )
    assert cred_repo_scoped.id != cred1.id
    assert cred_repo_scoped.repo_id == repo.id
    val_repo = await cred_repo.retrieve_secret(
        org_id=org.id, name="DEPLOY_KEY", repo_id=repo.id
    )
    assert val_repo == "repo_specific_ssh_key"
    # Org wide credential remains unaffected
    val_org = await cred_repo.retrieve_secret(org_id=org.id, name="DEPLOY_KEY")
    assert val_org == "rotated_ssh_key_payload"


@pytest.mark.asyncio
async def test_task_soft_delete(db_session: AsyncSession):
    """Verify soft deleting a task excludes it from active queries (covers: AC 7)."""
    org_repo = SqlAlchemyOrganizationRepository(db_session)
    repo_repo = SqlAlchemyRepositoryRepository(db_session)
    task_repo = SqlAlchemyTaskRepository(db_session)

    org = await org_repo.create_or_update(
        clerk_org_id=f"org_task_del_{uuid.uuid4().hex[:8]}",
        name="Task Delete Org",
        slug=f"task-del-{uuid.uuid4().hex[:8]}",
    )
    repo = await repo_repo.create(
        org_id=org.id,
        github_repo_id=int(uuid.uuid4().int % 10000000),
        github_installation_id=888,
        name="task-repo",
        full_name="task-del/task-repo",
    )

    task = await task_repo.create_task(
        org_id=org.id,
        repo_id=repo.id,
        title="Temporary task",
        description="To be deleted",
        trigger_type="manual_console",
    )

    # Verify task exists
    fetched = await task_repo.get_by_id(org_id=org.id, task_id=task.id)
    assert fetched.id == task.id

    # Soft delete task
    await task_repo.soft_delete(org_id=org.id, task_id=task.id)

    # Active lookup must raise NotFoundError
    with pytest.raises(NotFoundError):
        await task_repo.get_by_id(org_id=org.id, task_id=task.id)

    # List tasks for repo returns zero active tasks
    tasks, total = await task_repo.list_by_repo(org_id=org.id, repo_id=repo.id)
    assert total == 0
    assert len(tasks) == 0
