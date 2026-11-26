"""Task repository port protocol."""

import uuid
from datetime import datetime
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

    async def get_by_id_unscoped(self, task_id: uuid.UUID) -> Task:
        """Retrieve a task by ID without organization filtering (403 vs 404)."""
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

    async def set_interruption(
        self,
        org_id: uuid.UUID,
        task_id: uuid.UUID,
        prompt: str,
        interruption_type: str = "clarification",
        options: list | dict | None = None,
        expires_at: datetime | None = None,
    ) -> Task:
        """Transition a task to awaiting_input and store interruption metadata."""
        ...

    async def clear_interruption(
        self,
        org_id: uuid.UUID,
        task_id: uuid.UUID,
        new_status: str = "in_progress",
    ) -> Task:
        """Clear interruption metadata and update status."""
        ...

    async def claim_interruption(
        self,
        org_id: uuid.UUID,
        task_id: uuid.UUID,
        new_status: str = "in_progress",
    ) -> tuple[Task, str | None]:
        """Atomically claim an awaiting_input interruption and return (task, prompt)."""
        ...

    async def claim_abort(
        self,
        org_id: uuid.UUID,
        task_id: uuid.UUID,
    ) -> Task:
        """Atomically transition a non-terminal task to cancelled."""
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
