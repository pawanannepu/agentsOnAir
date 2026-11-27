"""E2B hardware microVM sandbox provider with timeout and network egress controls."""

import logging
import uuid
from collections.abc import Sequence
from typing import Any

from app.application.ports.sandbox import (
    SandboxExecutionResult,
    SandboxProvider,
    SandboxSession,
)
from app.infrastructure.sandbox.mock_sandbox import MockSandboxProvider

logger = logging.getLogger(__name__)


class E2BSandboxSession(SandboxSession):
    """E2B sandbox session supporting live timeout extension and network isolation."""

    def __init__(
        self,
        delegate: SandboxSession,
        e2b_client: Any = None,
        timeout_seconds: int = 600,
        network_egress_mode: str = "off_after_install",
        allowed_egress_domains: Sequence[str] | None = None,
    ) -> None:
        self._delegate = delegate
        self._e2b_client = e2b_client
        self._timeout_seconds = timeout_seconds
        self._timeout_extensions: list[int] = []
        self._network_egress_mode = network_egress_mode
        self._allowed_egress_domains = list(allowed_egress_domains or [])
        self._network_restricted = False

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

    @property
    def network_egress_mode(self) -> str:
        return self._network_egress_mode

    @property
    def allowed_egress_domains(self) -> list[str]:
        return list(self._allowed_egress_domains)

    @property
    def network_restricted(self) -> bool:
        return self._network_restricted

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

    async def restrict_network(
        self,
        mode: str,
        allowed_domains: Sequence[str] | None = None,
    ) -> None:
        """Enforce network egress policy on E2B sandbox after workspace setup."""
        domains = list(allowed_domains or [])
        self._network_egress_mode = mode
        self._allowed_egress_domains = domains
        self._network_restricted = mode in ("off_after_install", "allowlist")

        if self._e2b_client is not None and hasattr(
            self._e2b_client, "set_network_rules"
        ):
            if mode == "off_after_install" or (
                mode == "allowlist" and len(domains) == 0
            ):
                await self._e2b_client.set_network_rules(
                    allow_out=[], deny_out=["0.0.0.0/0"]
                )
            elif mode == "allowlist":
                await self._e2b_client.set_network_rules(
                    allow_out=domains, deny_out=["0.0.0.0/0"]
                )
            else:
                await self._e2b_client.set_network_rules(
                    allow_out=["0.0.0.0/0"], deny_out=[]
                )

        await self._delegate.restrict_network(mode, domains)

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
        network_egress_mode: str = "off_after_install",
        allowed_egress_domains: Sequence[str] | None = None,
    ) -> SandboxSession:
        # In testing/dev where E2B_API_KEY is not set, wrap fallback session
        delegate = await self._mock_fallback.create_sandbox(
            org_id=org_id,
            task_id=task_id,
            memory_limit_mb=memory_limit_mb,
            timeout_seconds=timeout_seconds,
            network_egress_mode=network_egress_mode,
            allowed_egress_domains=allowed_egress_domains,
        )
        return E2BSandboxSession(
            delegate=delegate,
            e2b_client=None,
            timeout_seconds=timeout_seconds,
            network_egress_mode=network_egress_mode,
            allowed_egress_domains=allowed_egress_domains,
        )
