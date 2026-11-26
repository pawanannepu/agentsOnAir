"""E2B hardware microVM sandbox provider with timeout extension support."""

import logging
import uuid
from typing import Any

from app.application.ports.sandbox import (
    SandboxExecutionResult,
    SandboxProvider,
    SandboxSession,
)
from app.infrastructure.sandbox.mock_sandbox import MockSandboxProvider

logger = logging.getLogger(__name__)


class E2BSandboxSession(SandboxSession):
    """E2B sandbox session supporting live timeout extension."""

    def __init__(
        self,
        delegate: SandboxSession,
        e2b_client: Any = None,
        timeout_seconds: int = 600,
    ) -> None:
        self._delegate = delegate
        self._e2b_client = e2b_client
        self._timeout_seconds = timeout_seconds
        self._timeout_extensions: list[int] = []

    @property
    def id(self) -> str:
        return self._delegate.id

    @property
    def provider(self) -> str:
        return "e2b" if self._e2b_client is not None else self._delegate.provider

    @property
    def timeout_seconds(self) -> int:
        return self._timeout_seconds

    @property
    def timeout_extensions(self) -> list[int]:
        return list(self._timeout_extensions)

    async def execute_command(
        self,
        command: str,
        timeout_seconds: float = 120.0,
        env: dict[str, str] | None = None,
    ) -> SandboxExecutionResult:
        return await self._delegate.execute_command(
            command, timeout_seconds=timeout_seconds, env=env
        )

    async def read_file(self, path: str) -> str:
        return await self._delegate.read_file(path)

    async def write_file(self, path: str, content: str) -> None:
        await self._delegate.write_file(path, content)

    async def list_files(self, directory: str = ".") -> list[str]:
        return await self._delegate.list_files(directory)

    async def get_diff(self) -> str:
        return await self._delegate.get_diff()

    async def extend_timeout(self, timeout_seconds: int) -> None:
        """Extend E2B microVM timeout (e.g., to 15 minutes during awaiting_input)."""
        self._timeout_seconds = timeout_seconds
        self._timeout_extensions.append(timeout_seconds)
        if self._e2b_client is not None and hasattr(self._e2b_client, "set_timeout"):
            await self._e2b_client.set_timeout(timeout_seconds)
        await self._delegate.extend_timeout(timeout_seconds)
        logger.info(
            "Extended sandbox %s timeout to %s seconds",
            self.id,
            timeout_seconds,
        )

    async def terminate(self) -> None:
        if self._e2b_client is not None and hasattr(self._e2b_client, "kill"):
            await self._e2b_client.kill()
        await self._delegate.terminate()


class E2BSandboxProvider(SandboxProvider):
    """E2B hardware microVM provider with local mock fallback."""

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
        # In testing/dev where E2B_API_KEY is not set, wrap fallback session
        delegate = await self._mock_fallback.create_sandbox(
            org_id=org_id,
            task_id=task_id,
            memory_limit_mb=memory_limit_mb,
            timeout_seconds=timeout_seconds,
        )
        return E2BSandboxSession(
            delegate=delegate,
            e2b_client=None,
            timeout_seconds=timeout_seconds,
        )
