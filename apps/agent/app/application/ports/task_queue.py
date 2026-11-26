"""Task queue port for dispatching background resumes and delayed watchdogs."""

import uuid
from datetime import datetime
from typing import Protocol


class TaskQueue(Protocol):
    """Port for background job dispatch and delayed timeout watchdogs."""

    async def enqueue_resume_task(
        self,
        org_id: uuid.UUID,
        task_id: uuid.UUID,
        task_run_id: uuid.UUID | None = None,
        intervention_id: uuid.UUID | None = None,
        response: str | None = None,
    ) -> str | None:
        """Enqueue a task resume job after human clarification is submitted."""
        ...

    async def schedule_interruption_watchdog(
        self,
        org_id: uuid.UUID,
        task_id: uuid.UUID,
        expires_at: datetime,
        delay_seconds: int = 900,
    ) -> str | None:
        """Schedule a delayed watchdog job to expire unanswered interruptions."""
        ...
