"""TaskRun repository port protocol."""

import uuid
from typing import Protocol

from app.domain.entities.task_run import TaskRun


class TaskRunRepository(Protocol):
    """Repository port for task execution attempts and LangGraph state checkpoints."""

    async def create_run(self, org_id: uuid.UUID, task_id: uuid.UUID) -> TaskRun:
        """Create a new execution run with sequential run_number under row lock."""
        ...

    async def get_by_id(self, org_id: uuid.UUID, task_run_id: uuid.UUID) -> TaskRun:
        """Retrieve an execution run by ID scoped to tenant."""
        ...

    async def get_latest_by_task(
        self, org_id: uuid.UUID, task_id: uuid.UUID
    ) -> TaskRun:
        """Retrieve the most recent execution run for a task."""
        ...

    async def set_status(
        self, org_id: uuid.UUID, task_run_id: uuid.UUID, status: str
    ) -> TaskRun:
        """Update execution run status without completing the run."""
        ...

    async def update_checkpoint(
        self,
        org_id: uuid.UUID,
        task_run_id: uuid.UUID,
        checkpoint_state: dict,
        expected_version: int,
    ) -> TaskRun:
        """Update checkpoint state using optimistic concurrency control."""
        ...

    async def complete_run(
        self,
        org_id: uuid.UUID,
        task_run_id: uuid.UUID,
        status: str,
        prompt_tokens: int = 0,
        completion_tokens: int = 0,
        estimated_cost_cents: int = 0,
        failure_reason: str | None = None,
    ) -> TaskRun:
        """Mark an execution run completed with token consumption metrics."""
        ...
