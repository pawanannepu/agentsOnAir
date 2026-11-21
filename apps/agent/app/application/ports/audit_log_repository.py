"""AuditLog repository port protocol."""

import uuid
from typing import Protocol

from app.domain.entities.audit_log import AuditLog


class AuditLogRepository(Protocol):
    """Repository port for append-only audit logs."""

    async def record_event(
        self,
        org_id: uuid.UUID,
        actor_type: str,
        actor_id: str,
        action: str,
        target_type: str,
        target_id: uuid.UUID,
        payload_before: dict | None = None,
        payload_after: dict | None = None,
        ip_address: str | None = None,
    ) -> AuditLog:
        """Append an immutable audit log entry."""
        ...

    async def list_events(
        self,
        org_id: uuid.UUID,
        page: int = 1,
        page_size: int = 20,
        target_type: str | None = None,
    ) -> tuple[list[AuditLog], int]:
        """List audit events scoped to an organization with pagination."""
        ...
