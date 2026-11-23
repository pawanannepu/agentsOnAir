"""Integration tests for Tasks API endpoints (AC-1, AC-4).

Tests:
- POST /api/v1/tasks (happy path, repo not found, validation error)
- GET /api/v1/tasks/{task_id} (runs, review iterations, tenant mismatch)
"""

import uuid

import pytest
from httpx import AsyncClient
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

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
async def test_create_task_happy_path(client: AsyncClient, db_session: AsyncSession):
    """Verify POST /api/v1/tasks creates a task and returns status queued (AC-1)."""
    org_repo = SqlAlchemyOrganizationRepository(db_session)
    repo_repo = SqlAlchemyRepositoryRepository(db_session)

    org = await org_repo.create_or_update(
        clerk_org_id=f"org_{uuid.uuid4().hex[:12]}",
        name="Task API Test Org",
        slug=f"task-api-{uuid.uuid4().hex[:8]}",
    )
    repo = await repo_repo.create(
        org_id=org.id,
        github_repo_id=98765432,
        github_installation_id=12345,
        name="task-api-repo",
        full_name="task-org/task-api-repo",
        default_branch="main",
    )
    await db_session.commit()

    try:
        response = await client.post(
            "/api/v1/tasks",
            json={
                "org_id": str(org.id),
                "repo_id": str(repo.id),
                "title": "Build caching layer",
                "description": "Implement Redis caching in application layer",
                "base_branch": "main",
            },
        )
        assert response.status_code == 200
        data = response.json()
        assert "id" in data
        assert data["status"] == "queued"

        # Verify task exists in database
        task_id = uuid.UUID(data["id"])
        task_repo = SqlAlchemyTaskRepository(db_session)
        created_task = await task_repo.get_by_id(org.id, task_id)
        assert created_task.title == "Build caching layer"
        assert created_task.base_branch == "main"
        assert created_task.trigger_type == "manual_console"
    finally:
        await db_session.execute(
            text("DELETE FROM tasks WHERE repo_id = :rid"), {"rid": repo.id}
        )
        await db_session.execute(
            text("DELETE FROM repositories WHERE id = :rid"), {"rid": repo.id}
        )
        await db_session.execute(
            text("DELETE FROM organizations WHERE id = :oid"), {"oid": org.id}
        )
        await db_session.commit()


@pytest.mark.asyncio
async def test_create_task_repo_not_found(
    client: AsyncClient, db_session: AsyncSession
):
    """Verify POST /api/v1/tasks returns 404 when repository does not exist."""
    org_repo = SqlAlchemyOrganizationRepository(db_session)
    org = await org_repo.create_or_update(
        clerk_org_id=f"org_{uuid.uuid4().hex[:12]}",
        name="Missing Repo Org",
        slug=f"miss-repo-{uuid.uuid4().hex[:8]}",
    )
    await db_session.commit()

    missing_repo_id = uuid.uuid4()
    try:
        response = await client.post(
            "/api/v1/tasks",
            json={
                "org_id": str(org.id),
                "repo_id": str(missing_repo_id),
                "title": "Task with missing repo",
                "description": "Description",
                "base_branch": "main",
            },
        )
        assert response.status_code == 404
        assert "Repository not found" in response.json()["detail"]
    finally:
        await db_session.execute(
            text("DELETE FROM organizations WHERE id = :oid"), {"oid": org.id}
        )
        await db_session.commit()


@pytest.mark.asyncio
async def test_create_task_validation_error(client: AsyncClient):
    """Verify POST /api/v1/tasks returns 422 on invalid request body."""
    response = await client.post(
        "/api/v1/tasks",
        json={
            "org_id": "invalid-uuid",
            "repo_id": "invalid-uuid",
            "title": "",
            "description": "Description",
        },
    )
    assert response.status_code == 422


@pytest.mark.asyncio
async def test_get_task_details_with_runs_and_review_iterations(
    client: AsyncClient, db_session: AsyncSession
):
    """Verify GET /api/v1/tasks/{id} returns runs and review iterations (AC-1, AC-4)."""
    org_repo = SqlAlchemyOrganizationRepository(db_session)
    repo_repo = SqlAlchemyRepositoryRepository(db_session)
    task_repo = SqlAlchemyTaskRepository(db_session)
    task_run_repo = SqlAlchemyTaskRunRepository(db_session)
    review_repo = SqlAlchemyReviewIterationRepository(db_session)

    org = await org_repo.create_or_update(
        clerk_org_id=f"org_{uuid.uuid4().hex[:12]}",
        name="Detail Test Org",
        slug=f"detail-org-{uuid.uuid4().hex[:8]}",
    )
    repo = await repo_repo.create(
        org_id=org.id,
        github_repo_id=98712345,
        github_installation_id=54321,
        name="detail-repo",
        full_name="detail-org/detail-repo",
    )
    task = await task_repo.create_task(
        org_id=org.id,
        repo_id=repo.id,
        title="Implement OAuth flow",
        description="Add OAuth2 authorization code flow",
        trigger_type="github_issue",
        base_branch="main",
        branch_name="agentsonair/task-detail01-issue-99",
    )
    await task_repo.update_pr_details(
        org_id=org.id,
        task_id=task.id,
        pr_url="https://github.com/detail-org/detail-repo/pull/99",
        head_commit_sha="b" * 40,
        pr_review_status="approved",
        pr_number=99,
        branch_name="agentsonair/task-detail01-issue-99",
    )

    run = await task_run_repo.create_run(org.id, task.id)
    await review_repo.create(
        org_id=org.id,
        task_run_id=run.id,
        cycle_number=1,
        verdict="approved",
        summary="Verified clean implementation",
        findings=[
            {
                "file_path": "src/oauth.py",
                "line_number": 25,
                "severity": "info",
                "message": "Looks great",
                "suggested_fix": None,
            }
        ],
        blocking_count=0,
        non_blocking_count=1,
        diff_snapshot="--- a/src/oauth.py\n+++ b/src/oauth.py",
    )
    await db_session.commit()

    try:
        response = await client.get(f"/api/v1/tasks/{task.id}?org_id={org.id}")
        assert response.status_code == 200
        data = response.json()

        assert data["id"] == str(task.id)
        assert data["org_id"] == str(org.id)
        assert data["repo_id"] == str(repo.id)
        assert data["title"] == "Implement OAuth flow"
        assert data["description"] == "Add OAuth2 authorization code flow"
        assert data["status"] == "queued"
        assert data["trigger_type"] == "github_issue"
        assert data["base_branch"] == "main"
        assert data["branch_name"] == "agentsonair/task-detail01-issue-99"
        assert data["pr_number"] == 99
        assert data["pr_url"] == "https://github.com/detail-org/detail-repo/pull/99"
        assert data["head_commit_sha"] == "b" * 40
        assert data["pr_review_status"] == "approved"

        # Check runs and review iterations
        assert len(data["runs"]) == 1
        run_data = data["runs"][0]
        assert run_data["id"] == str(run.id)
        assert run_data["run_number"] == 1
        assert len(run_data["review_iterations"]) == 1
        it_data = run_data["review_iterations"][0]
        assert it_data["cycle_number"] == 1
        assert it_data["verdict"] == "approved"
        assert it_data["summary"] == "Verified clean implementation"
        assert it_data["blocking_count"] == 0
        assert it_data["non_blocking_count"] == 1
        assert len(it_data["findings"]) == 1
        assert it_data["findings"][0]["severity"] == "info"
    finally:
        await db_session.execute(
            text("DELETE FROM review_iterations WHERE org_id = :oid"), {"oid": org.id}
        )
        await db_session.execute(
            text("DELETE FROM task_runs WHERE org_id = :oid"), {"oid": org.id}
        )
        await db_session.execute(
            text("DELETE FROM tasks WHERE repo_id = :rid"), {"rid": repo.id}
        )
        await db_session.execute(
            text("DELETE FROM repositories WHERE id = :rid"), {"rid": repo.id}
        )
        await db_session.execute(
            text("DELETE FROM organizations WHERE id = :oid"), {"oid": org.id}
        )
        await db_session.commit()


@pytest.mark.asyncio
async def test_get_task_not_found(client: AsyncClient):
    """Verify GET /api/v1/tasks/{id} returns 404 for non-existent task."""
    random_task_id = uuid.uuid4()
    random_org_id = uuid.uuid4()
    response = await client.get(
        f"/api/v1/tasks/{random_task_id}?org_id={random_org_id}"
    )
    assert response.status_code == 404


@pytest.mark.asyncio
async def test_get_task_wrong_org_returns_404(
    client: AsyncClient, db_session: AsyncSession
):
    """Verify GET /api/v1/tasks/{id} enforces tenant org scoping (AC-1)."""
    org_repo = SqlAlchemyOrganizationRepository(db_session)
    repo_repo = SqlAlchemyRepositoryRepository(db_session)
    task_repo = SqlAlchemyTaskRepository(db_session)

    org_a = await org_repo.create_or_update(
        clerk_org_id=f"org_{uuid.uuid4().hex[:12]}",
        name="Org A",
        slug=f"org-a-{uuid.uuid4().hex[:8]}",
    )
    org_b = await org_repo.create_or_update(
        clerk_org_id=f"org_{uuid.uuid4().hex[:12]}",
        name="Org B",
        slug=f"org-b-{uuid.uuid4().hex[:8]}",
    )
    repo = await repo_repo.create(
        org_id=org_a.id,
        github_repo_id=77889900,
        github_installation_id=11111,
        name="repo-a",
        full_name="org-a/repo-a",
    )
    task = await task_repo.create_task(
        org_id=org_a.id,
        repo_id=repo.id,
        title="Org A Task",
        description="Description",
        trigger_type="manual_console",
    )
    await db_session.commit()

    try:
        # Querying task belonging to Org A using Org B must fail with 404
        response = await client.get(f"/api/v1/tasks/{task.id}?org_id={org_b.id}")
        assert response.status_code == 404
    finally:
        await db_session.execute(
            text("DELETE FROM tasks WHERE repo_id = :rid"), {"rid": repo.id}
        )
        await db_session.execute(
            text("DELETE FROM repositories WHERE id = :rid"), {"rid": repo.id}
        )
        await db_session.execute(
            text("DELETE FROM organizations WHERE id IN (:oa, :ob)"),
            {"oa": org_a.id, "ob": org_b.id},
        )
        await db_session.commit()
