"""AuditLog domain entity."""

import uuid
from dataclasses import dataclass
from datetime import datetime


@dataclass(slots=True)
class AuditLog:
    """Immutable audit event log."""

    id: uuid.UUID
    org_id: uuid.UUID
    actor_type: str
    actor_id: str
    action: str
    target_type: str
    target_id: uuid.UUID
    payload_before: dict | None = None
    payload_after: dict | None = None
    ip_address: str | None = None
    created_at: datetime | None = None
