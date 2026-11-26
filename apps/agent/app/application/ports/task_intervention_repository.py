"""Task intervention repository port."""

import uuid
from typing import Protocol

from app.domain.entities.task_intervention import TaskIntervention


class TaskInterventionRepository(Protocol):
    """Persistence operations for task interventions."""

    async def create(
        self,
        org_id: uuid.UUID,
        task_id: uuid.UUID,
        clerk_user_id: str,
        intervention_type: str,
        payload: dict,
        task_run_id: uuid.UUID | None = None,
        prompt_snapshot: str | None = None,
    ) -> TaskIntervention:
        """Create a new human intervention record."""
        ...

    async def list_by_task(
        self, org_id: uuid.UUID, task_id: uuid.UUID
    ) -> list[TaskIntervention]:
        """List all interventions for a task in chronological order."""
        ...

    async def mark_applied(
        self, org_id: uuid.UUID, intervention_id: uuid.UUID
    ) -> TaskIntervention:
        """Mark an intervention as applied by the agent execution loop."""
        ...
