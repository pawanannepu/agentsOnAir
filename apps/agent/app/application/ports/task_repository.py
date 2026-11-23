"""Task repository port protocol."""

import uuid
from typing import Protocol

from app.domain.entities.task import Task


class TaskRepository(Protocol):
    """Repository port for agent task management."""

    async def create_task(
        self,
        org_id: uuid.UUID,
        repo_id: uuid.UUID,
        title: str,
        description: str,
        trigger_type: str,
        trigger_metadata: dict | None = None,
        base_branch: str = "main",
        branch_name: str | None = None,
        created_by_clerk_user_id: str | None = None,
    ) -> Task:
        """Create a new task scoped to an organization and repository."""
        ...

    async def get_by_id(self, org_id: uuid.UUID, task_id: uuid.UUID) -> Task:
        """Retrieve a task scoped to an organization."""
        ...

    async def find_active_by_repo_and_issue(
        self, repo_id: uuid.UUID, issue_number: int
    ) -> Task | None:
        """Find an active task for an issue in a repository."""
        ...

    async def list_by_repo(
        self, org_id: uuid.UUID, repo_id: uuid.UUID, page: int = 1, page_size: int = 20
    ) -> tuple[list[Task], int]:
        """List active tasks for a repository with pagination."""
        ...

    async def update_status(
        self,
        org_id: uuid.UUID,
        task_id: uuid.UUID,
        status: str,
        branch_name: str | None = None,
        pr_number: int | None = None,
    ) -> Task:
        """Update the status and branch/PR coordinates of a task."""
        ...

    async def update_pr_details(
        self,
        org_id: uuid.UUID,
        task_id: uuid.UUID,
        pr_url: str,
        head_commit_sha: str,
        pr_review_status: str,
        pr_number: int | None = None,
        branch_name: str | None = None,
    ) -> Task:
        """Update the pull request coordinates and review status of a task."""
        ...

    async def soft_delete(self, org_id: uuid.UUID, task_id: uuid.UUID) -> None:
        """Soft delete a task by setting deleted_at."""
        ...
