"""SandboxRun domain entity."""

import uuid
from dataclasses import dataclass
from datetime import datetime


@dataclass(slots=True)
class SandboxRun:
    """Isolated microVM or container execution record."""

    id: uuid.UUID
    org_id: uuid.UUID
    task_run_id: uuid.UUID
    provider: str
    sandbox_id: str
    status: str = "allocating"
    exit_code: int | None = None
    logs_storage_key: str | None = None
    memory_limit_mb: int = 2048
    timeout_seconds: int = 600
    allocated_at: datetime | None = None
    terminated_at: datetime | None = None
    created_at: datetime | None = None
    updated_at: datetime | None = None
