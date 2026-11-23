"""Integration tests for review iterations and task pull request fields (AC-1, AC-4)."""

import uuid

import pytest
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.domain.entities.review_iteration import ReviewIteration
from app.infrastructure.db.repositories.organization_repository import (
    SqlAlchemyOrganizationRepository,
)
from app.infrastructure.db.repositories.repository_repository import (
    SqlAlchemyRepositoryRepository,
)
from app.infrastructure.db.repositories.review_iteration_repository import (
    SqlAlchemyReviewIterationRepository,
)
from app.infrastructure.db.repositories.task_repository import (
    SqlAlchemyTaskRepository,
)
from app.infrastructure.db.repositories.task_run_repository import (
    SqlAlchemyTaskRunRepository,
)


@pytest.mark.asyncio
async def test_review_iterations_crud(db_session: AsyncSession):
    """Verify ReviewIteration creation and retrieval by task run."""
    org_repo = SqlAlchemyOrganizationRepository(db_session)
    repo_repo = SqlAlchemyRepositoryRepository(db_session)
    task_repo = SqlAlchemyTaskRepository(db_session)
    task_run_repo = SqlAlchemyTaskRunRepository(db_session)
    review_repo = SqlAlchemyReviewIterationRepository(db_session)

    org = await org_repo.create_or_update(
        clerk_org_id=f"org_{uuid.uuid4().hex[:12]}",
        name="Review Test Org",
        slug=f"rev-org-{uuid.uuid4().hex[:8]}",
    )
    repo = await repo_repo.create(
        org_id=org.id,
        github_repo_id=987654321,
        github_installation_id=12345,
        name="test-repo",
        full_name="test-org/test-repo",
    )
    task = await task_repo.create_task(
        org_id=org.id,
        repo_id=repo.id,
        title="Test Task",
        description="Test Description",
        trigger_type="webhook_issue",
        trigger_metadata={"issue_number": 42},
        base_branch="main",
    )
    assert task.base_branch == "main"
    assert task.pr_url is None

    run = await task_run_repo.create_run(
        org_id=org.id,
        task_id=task.id,
    )

    iteration1 = await review_repo.create(
        org_id=org.id,
        task_run_id=run.id,
        cycle_number=1,
        verdict="changes_requested",
        summary="Missing null check in handler",
        findings=[
            {
                "file_path": "src/handler.py",
                "line_number": 25,
                "severity": "critical",
                "message": "Potential null dereference",
                "suggested_fix": "Add if data is None check",
            }
        ],
        blocking_count=1,
        non_blocking_count=0,
        diff_snapshot="--- a/src/handler.py\n+++ b/src/handler.py\n",
    )
    assert isinstance(iteration1, ReviewIteration)
    assert iteration1.cycle_number == 1
    assert iteration1.blocking_count == 1
    assert iteration1.verdict == "changes_requested"

    iteration2 = await review_repo.create(
        org_id=org.id,
        task_run_id=run.id,
        cycle_number=2,
        verdict="approved",
        summary="All findings resolved and tests pass",
        findings=[],
        blocking_count=0,
        non_blocking_count=0,
        diff_snapshot="--- a/src/handler.py\n+++ b/src/handler.py\n+ check",
    )
    assert iteration2.verdict == "approved"
    assert iteration2.blocking_count == 0

    iterations = await review_repo.list_by_task_run_id(org.id, run.id)
    assert len(iterations) == 2
    assert iterations[0].cycle_number == 1
    assert iterations[1].cycle_number == 2

    # Verify update_pr_details on task
    updated_task = await task_repo.update_pr_details(
        org_id=org.id,
        task_id=task.id,
        pr_url="https://github.com/test-org/test-repo/pull/10",
        head_commit_sha="abcd1234ef567890",
        pr_review_status="approved",
        pr_number=10,
        branch_name="agentsonair/task-test-issue-42",
    )
    assert updated_task.pr_url == "https://github.com/test-org/test-repo/pull/10"
    assert updated_task.head_commit_sha == "abcd1234ef567890"
    assert updated_task.pr_review_status == "approved"
    assert updated_task.pr_number == 10
    assert updated_task.branch_name == "agentsonair/task-test-issue-42"


@pytest.mark.asyncio
async def test_active_task_partial_unique_index(db_session: AsyncSession):
    """Verify unique index prevents concurrent active tasks for same issue (AC-1)."""
    org_repo = SqlAlchemyOrganizationRepository(db_session)
    repo_repo = SqlAlchemyRepositoryRepository(db_session)
    task_repo = SqlAlchemyTaskRepository(db_session)

    org = await org_repo.create_or_update(
        clerk_org_id=f"org_{uuid.uuid4().hex[:12]}",
        name="Dup Test Org",
        slug=f"dup-org-{uuid.uuid4().hex[:8]}",
    )
    repo = await repo_repo.create(
        org_id=org.id,
        github_repo_id=555666777,
        github_installation_id=9999,
        name="dup-repo",
        full_name="dup-org/dup-repo",
    )

    # First task for issue 99
    task1 = await task_repo.create_task(
        org_id=org.id,
        repo_id=repo.id,
        title="Issue 99 Task 1",
        description="First attempt",
        trigger_type="webhook_issue",
        trigger_metadata={"issue_number": 99},
    )
    assert task1.status == "queued"

    # Find active by repo and issue
    active = await task_repo.find_active_by_repo_and_issue(repo.id, 99)
    assert active is not None
    assert active.id == task1.id

    # Creating a second active task for issue 99 should fail unique constraint
    with pytest.raises(IntegrityError):
        await task_repo.create_task(
            org_id=org.id,
            repo_id=repo.id,
            title="Issue 99 Task 2",
            description="Duplicate attempt",
            trigger_type="webhook_issue",
            trigger_metadata={"issue_number": 99},
        )
