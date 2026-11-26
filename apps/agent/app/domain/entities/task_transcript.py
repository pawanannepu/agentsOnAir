"""Task transcript domain entity."""

import uuid
from dataclasses import dataclass, field
from datetime import datetime


@dataclass(slots=True)
class TaskTranscript:
    """Archived terminal logs and stream events for completed task runs."""

    id: uuid.UUID
    org_id: uuid.UUID
    task_id: uuid.UUID
    task_run_id: uuid.UUID
    terminal_log: bytes
    events_json: list[dict] = field(default_factory=list)
    total_lines: int = 0
    created_at: datetime | None = None
