"""TaskApproval repository port protocol."""

import uuid
from datetime import datetime
from typing import Protocol

from app.domain.entities.task_approval import TaskApproval


class TaskApprovalRepository(Protocol):
    """Repository port for durable risky-action approval records."""

    async def create_pending(
        self,
        org_id: uuid.UUID,
        task_id: uuid.UUID,
        task_run_id: uuid.UUID,
        risk_category: str,
        action_type: str,
        action_hash: str,
        action_summary: str,
        action_payload: dict,
        expires_at: datetime,
    ) -> TaskApproval:
        """Persist a new pending approval request (unique per active pending task)."""
        ...

    async def get_by_id(
        self, org_id: uuid.UUID, approval_id: uuid.UUID
    ) -> TaskApproval:
        """Retrieve an approval record scoped to tenant organization."""
        ...

    async def get_pending_for_task(
        self, org_id: uuid.UUID, task_id: uuid.UUID
    ) -> TaskApproval | None:
        """Return the currently pending approval for a task, if any."""
        ...

    async def find_approved_unconsumed(
        self, org_id: uuid.UUID, task_id: uuid.UUID, action_hash: str
    ) -> TaskApproval | None:
        """Return an approved, unconsumed approval matching action_hash for replay."""
        ...

    async def mark_consumed(
        self, org_id: uuid.UUID, approval_id: uuid.UUID
    ) -> TaskApproval:
        """Mark an approved record consumed once the action proceeds."""
        ...

    async def decide_atomic(
        self,
        org_id: uuid.UUID,
        task_id: uuid.UUID,
        approval_id: uuid.UUID,
        decision: str,
        decided_by_clerk_user_id: str,
        decision_note: str | None = None,
    ) -> TaskApproval | None:
        """Atomically transition a pending approval to approved or rejected."""
        ...

    async def expire_atomic(
        self,
        org_id: uuid.UUID,
        task_id: uuid.UUID,
        approval_id: uuid.UUID,
    ) -> TaskApproval | None:
        """Atomically transition a pending approval to expired."""
        ...
