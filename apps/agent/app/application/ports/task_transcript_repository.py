"""Task transcript repository port."""

import uuid
from typing import Protocol

from app.domain.entities.task_transcript import TaskTranscript


class TaskTranscriptRepository(Protocol):
    """Persistence operations for completed task transcripts."""

    async def create_or_update(
        self,
        org_id: uuid.UUID,
        task_id: uuid.UUID,
        task_run_id: uuid.UUID,
        terminal_log: bytes,
        events_json: list[dict],
        total_lines: int,
    ) -> TaskTranscript:
        """Store or update archived task transcript with compressed terminal log."""
        ...

    async def get_by_task(
        self,
        org_id: uuid.UUID,
        task_id: uuid.UUID,
        task_run_id: uuid.UUID | None = None,
    ) -> TaskTranscript | None:
        """Retrieve task transcript for a task and optional run."""
        ...
