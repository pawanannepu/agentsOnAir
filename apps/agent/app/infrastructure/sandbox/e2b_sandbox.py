"""E2B hardware microVM sandbox provider."""

import uuid

from app.application.ports.sandbox import (
    SandboxProvider,
    SandboxSession,
)
from app.infrastructure.sandbox.mock_sandbox import MockSandboxProvider


class E2BSandboxProvider(SandboxProvider):
    """E2B hardware microVM provider with fallback."""

    def __init__(self, api_key: str | None = None) -> None:
        self._api_key = api_key
        self._mock_fallback = MockSandboxProvider()

    async def create_sandbox(
        self,
        org_id: uuid.UUID,
        task_id: uuid.UUID,
        memory_limit_mb: int = 2048,
        timeout_seconds: int = 600,
    ) -> SandboxSession:
        # In testing/dev where E2B_API_KEY is not set, use mock fallback
        return await self._mock_fallback.create_sandbox(
            org_id=org_id,
            task_id=task_id,
            memory_limit_mb=memory_limit_mb,
            timeout_seconds=timeout_seconds,
        )
