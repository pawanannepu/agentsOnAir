"""ReviewIteration repository port protocol."""

import uuid
from typing import Protocol

from app.domain.entities.review_iteration import ReviewIteration


class ReviewIterationRepository(Protocol):
    """Repository port for review iteration persistence."""

    async def create(
        self,
        org_id: uuid.UUID,
        task_run_id: uuid.UUID,
        cycle_number: int,
        verdict: str,
        summary: str,
        findings: list[dict],
        blocking_count: int,
        non_blocking_count: int,
        diff_snapshot: str | None = None,
    ) -> ReviewIteration:
        """Create and persist a review iteration record."""
        ...

    async def get_by_id(
        self, org_id: uuid.UUID, iteration_id: uuid.UUID
    ) -> ReviewIteration | None:
        """Retrieve a review iteration by its UUID."""
        ...

    async def list_by_task_run_id(
        self, org_id: uuid.UUID, task_run_id: uuid.UUID
    ) -> list[ReviewIteration]:
        """List all review iterations for a given task run ordered by cycle number."""
        ...
