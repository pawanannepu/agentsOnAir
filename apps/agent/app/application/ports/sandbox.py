"""Sandbox port interfaces and data transfer objects."""

import uuid
from dataclasses import dataclass
from typing import Protocol


@dataclass(slots=True)
class SandboxExecutionResult:
    """Execution telemetry for a command run inside a sandbox."""

    exit_code: int
    stdout: str
    stderr: str
    duration_seconds: float = 0.0


class SandboxSession(Protocol):
    """Active sandbox session interface providing isolated execution."""

    @property
    def id(self) -> str:
        """Unique sandbox identifier."""
        ...

    @property
    def provider(self) -> str:
        """Provider name ('docker', 'e2b', or 'mock')."""
        ...

    async def execute_command(
        self,
        command: str,
        timeout_seconds: float = 120.0,
        env: dict[str, str] | None = None,
    ) -> SandboxExecutionResult:
        """Execute a shell command inside the sandbox."""
        ...

    async def read_file(self, path: str) -> str:
        """Read text content from a file inside the sandbox."""
        ...

    async def write_file(self, path: str, content: str) -> None:
        """Write text content to a file inside the sandbox."""
        ...

    async def list_files(self, directory: str = ".") -> list[str]:
        """List files in a directory within the sandbox."""
        ...

    async def get_diff(self) -> str:
        """Extract the git unified diff of changes made inside the sandbox."""
        ...

    async def extend_timeout(self, timeout_seconds: int) -> None:
        """Extend the active sandbox session lifetime timeout."""
        ...

    async def terminate(self) -> None:
        """Terminate and clean up sandbox resources."""
        ...


class SandboxProvider(Protocol):
    """Provider for provisioning isolated sandbox microVMs or containers."""

    async def create_sandbox(
        self,
        org_id: uuid.UUID,
        task_id: uuid.UUID,
        memory_limit_mb: int = 2048,
        timeout_seconds: int = 600,
    ) -> SandboxSession:
        """Provision a new isolated sandbox session."""
        ...
