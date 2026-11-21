"""SandboxRun repository port protocol."""

import uuid
from typing import Protocol

from app.domain.entities.sandbox_run import SandboxRun


class SandboxRunRepository(Protocol):
    """Repository port for microVM and container sandbox sessions."""

    async def record_allocation(
        self,
        org_id: uuid.UUID,
        task_run_id: uuid.UUID,
        provider: str,
        sandbox_id: str,
        memory_limit_mb: int = 2048,
        timeout_seconds: int = 600,
    ) -> SandboxRun:
        """Record the allocation of an isolated sandbox session."""
        ...

    async def get_by_task_run_id(
        self, org_id: uuid.UUID, task_run_id: uuid.UUID
    ) -> SandboxRun:
        """Retrieve sandbox session details for an execution run."""
        ...

    async def record_termination(
        self,
        org_id: uuid.UUID,
        sandbox_run_id: uuid.UUID,
        exit_code: int | None = None,
        logs_storage_key: str | None = None,
    ) -> SandboxRun:
        """Record sandbox termination and logs storage location."""
        ...
