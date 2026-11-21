"""Unit tests for domain entities and domain exceptions.

Covers:
AC 1: Relational domain entities and properties
AC 2: Tenant isolation domain fields
AC 3: Task and TaskRun state and version counters
AC 4: SandboxRun allocation fields
AC 5: Credential and CredentialMetadata entity separation
AC 6: AuditLog event structure
AC 7: Soft delete fields on entities
"""

import uuid

import pytest

from app.domain.entities.audit_log import AuditLog
from app.domain.entities.credential import Credential, CredentialMetadata
from app.domain.entities.organization import Organization
from app.domain.entities.repository import Repository
from app.domain.entities.sandbox_run import SandboxRun
from app.domain.entities.task import Task
from app.domain.entities.task_run import TaskRun
from app.domain.exceptions import (
    ConcurrencyError,
    ConflictError,
    DecryptionError,
    DomainError,
    InvalidStateTransitionError,
    NotFoundError,
    ValidationError,
)


def _assert_slots_enforced(entity: object) -> None:
    """Verify that slots block setting arbitrary dynamic attributes."""
    dynamic_attr = f"dynamic_field_{uuid.uuid4().hex[:6]}"
    with pytest.raises(AttributeError):
        setattr(entity, dynamic_attr, "disallowed")


def test_organization_entity_slots_and_defaults():
    """Verify Organization entity attributes and defaults (covers: AC 1)."""
    org_id = uuid.uuid4()
    org = Organization(
        id=org_id,
        clerk_org_id="org_test_123",
        name="Test Org",
        slug="test-org",
    )
    assert org.id == org_id
    assert org.clerk_org_id == "org_test_123"
    assert org.name == "Test Org"
    assert org.slug == "test-org"
    assert org.github_installation_id is None
    assert org.settings == {}
    assert org.deleted_at is None
    _assert_slots_enforced(org)


def test_repository_entity_slots_and_defaults():
    """Verify Repository entity attributes and defaults (covers: AC 1, AC 7)."""
    repo_id = uuid.uuid4()
    org_id = uuid.uuid4()
    repo = Repository(
        id=repo_id,
        org_id=org_id,
        github_repo_id=1234567,
        github_installation_id=890,
        name="my-service",
        full_name="org/my-service",
    )
    assert repo.id == repo_id
    assert repo.org_id == org_id
    assert repo.default_branch == "main"
    assert repo.is_private is True
    assert repo.config == {}
    assert repo.deleted_at is None
    _assert_slots_enforced(repo)


def test_credential_and_metadata_separation():
    """Verify Credential and CredentialMetadata distinction (covers: AC 5)."""
    cred_id = uuid.uuid4()
    org_id = uuid.uuid4()

    cred = Credential(
        id=cred_id,
        org_id=org_id,
        repo_id=None,
        name="GITHUB_TOKEN",
        credential_type="github_token",
        encrypted_data="base64ciphertext==",
        nonce="base64nonce==",
    )
    assert cred.key_version == 1
    assert cred.encrypted_data == "base64ciphertext=="
    assert cred.nonce == "base64nonce=="

    meta = CredentialMetadata(
        id=cred_id,
        org_id=org_id,
        repo_id=None,
        name="GITHUB_TOKEN",
        credential_type="github_token",
    )
    assert meta.key_version == 1
    assert not hasattr(meta, "encrypted_data")
    assert not hasattr(meta, "nonce")

    _assert_slots_enforced(cred)
    _assert_slots_enforced(meta)


def test_task_entity_slots_and_defaults():
    """Verify Task entity attributes and status defaults (covers: AC 3)."""
    task_id = uuid.uuid4()
    org_id = uuid.uuid4()
    repo_id = uuid.uuid4()

    task = Task(
        id=task_id,
        org_id=org_id,
        repo_id=repo_id,
        title="Fix issue 42",
        description="Fix the bug in login flow",
        trigger_type="webhook_issue",
    )
    assert task.status == "queued"
    assert task.trigger_metadata == {}
    assert task.branch_name is None
    assert task.pr_number is None
    assert task.deleted_at is None
    _assert_slots_enforced(task)


def test_task_run_entity_slots_and_defaults():
    """Verify TaskRun entity attributes and counter defaults (covers: AC 3)."""
    run_id = uuid.uuid4()
    org_id = uuid.uuid4()
    task_id = uuid.uuid4()

    run = TaskRun(
        id=run_id,
        org_id=org_id,
        task_id=task_id,
    )
    assert run.run_number == 1
    assert run.status == "pending"
    assert run.version == 1
    assert run.checkpoint_state == {}
    assert run.tokens_used == 0
    assert run.estimated_cost_cents == 0
    _assert_slots_enforced(run)


def test_sandbox_run_entity_slots_and_defaults():
    """Verify SandboxRun entity attributes and limits (covers: AC 4)."""
    sandbox_id = uuid.uuid4()
    org_id = uuid.uuid4()
    run_id = uuid.uuid4()

    sbx = SandboxRun(
        id=sandbox_id,
        org_id=org_id,
        task_run_id=run_id,
        provider="e2b",
        sandbox_id="sbx_123xyz",
    )
    assert sbx.status == "allocating"
    assert sbx.memory_limit_mb == 2048
    assert sbx.timeout_seconds == 600
    assert sbx.exit_code is None
    assert sbx.logs_storage_key is None
    _assert_slots_enforced(sbx)


def test_audit_log_entity_slots_and_defaults():
    """Verify AuditLog entity attributes and slots enforcement (covers: AC 6)."""
    log_id = uuid.uuid4()
    org_id = uuid.uuid4()
    target_id = uuid.uuid4()

    log = AuditLog(
        id=log_id,
        org_id=org_id,
        actor_type="user",
        actor_id="usr_clerk_123",
        action="repository.linked",
        target_type="repository",
        target_id=target_id,
    )
    assert log.payload_before is None
    assert log.payload_after is None
    assert log.ip_address is None
    _assert_slots_enforced(log)


def test_domain_exceptions_hierarchy():
    """Verify DomainError base class and specialized domain exception subclasses."""
    exceptions = [
        NotFoundError("Entity was not found"),
        ConflictError("Entity already exists"),
        ValidationError("Invalid entity field"),
        ConcurrencyError("Optimistic concurrency conflict"),
        DecryptionError("Authentication tag mismatch"),
        InvalidStateTransitionError("State transition disallowed"),
    ]

    for exc in exceptions:
        assert isinstance(exc, DomainError)
        assert isinstance(exc, Exception)
        assert len(exc.message) > 0
