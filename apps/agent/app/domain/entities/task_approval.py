"""TaskApproval domain entity."""

import uuid
from dataclasses import dataclass, field
from datetime import datetime


@dataclass(slots=True)
class TaskApproval:
    """Approval gate record for a risky autonomous agent action."""

    id: uuid.UUID
    org_id: uuid.UUID
    task_id: uuid.UUID
    task_run_id: uuid.UUID
    status: str
    risk_category: str
    action_type: str
    action_hash: str
    action_summary: str
    expires_at: datetime
    action_payload: dict = field(default_factory=dict)
    consumed_at: datetime | None = None
    decided_by_clerk_user_id: str | None = None
    decision_note: str | None = None
    decided_at: datetime | None = None
    created_at: datetime | None = None
