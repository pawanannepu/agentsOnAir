"""Task intervention domain entity."""

import uuid
from dataclasses import dataclass, field
from datetime import datetime


@dataclass(slots=True)
class TaskIntervention:
    """Human developer steering, clarification response, or abort action."""

    id: uuid.UUID
    org_id: uuid.UUID
    task_id: uuid.UUID
    clerk_user_id: str
    intervention_type: str
    task_run_id: uuid.UUID | None = None
    prompt_snapshot: str | None = None
    payload: dict = field(default_factory=dict)
    applied_at: datetime | None = None
    created_at: datetime | None = None
