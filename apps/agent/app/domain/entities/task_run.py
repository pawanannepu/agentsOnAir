"""TaskRun domain entity."""

import uuid
from dataclasses import dataclass, field
from datetime import datetime


@dataclass(slots=True)
class TaskRun:
    """Execution attempt of a task with LangGraph state checkpoint."""

    id: uuid.UUID
    org_id: uuid.UUID
    task_id: uuid.UUID
    run_number: int = 1
    status: str = "pending"
    version: int = 1
    failure_reason: str | None = None
    checkpoint_state: dict = field(default_factory=dict)
    prompt_tokens: int = 0
    completion_tokens: int = 0
    tokens_used: int = 0
    estimated_cost_cents: int = 0
    started_at: datetime | None = None
    completed_at: datetime | None = None
    created_at: datetime | None = None
    updated_at: datetime | None = None
