"""Isolated mock sandbox provider running in a temporary local workspace."""

import asyncio
import os
import shutil
import tempfile
import time
import uuid
from collections.abc import Awaitable, Callable, Sequence

from app.application.ports.sandbox import (
    SandboxExecutionResult,
    SandboxProvider,
    SandboxSession,
)
from app.domain.exceptions import GuardrailBlockedError


async def collect_workspace_diff(
    execute_command: Callable[[str], Awaitable[SandboxExecutionResult]],
) -> str:
    """Collect unified diff including untracked files across tracked or unborn repos."""
    await execute_command("git add -N .")
    res = await execute_command("git diff HEAD")
    if res.exit_code != 0 or not res.stdout.strip():
        res = await execute_command("git diff")
    return res.stdout


class MockSandboxSession(SandboxSession):
    """Local filesystem sandbox session with real command execution."""

    def __init__(
        self,
        sandbox_id: str,
        workspace_dir: str,
        timeout_seconds: int = 600,
        network_egress_mode: str = "off_after_install",
        allowed_egress_domains: Sequence[str] | None = None,
    ) -> None:
        self._id = sandbox_id
        self._workspace_dir = workspace_dir
        self._meta_dir = tempfile.mkdtemp(prefix=f"aon_meta_{sandbox_id}_")
        self._system_gitconfig = os.path.join(self._meta_dir, "gitconfig")
        with open(self._system_gitconfig, "a", encoding="utf-8"):
            pass
        self._active = True
        self._timeout_seconds = timeout_seconds
        self._timeout_extensions: list[int] = []
        self._network_egress_mode = network_egress_mode
        self._allowed_egress_domains = list(allowed_egress_domains or [])
        self._network_restricted = False
        self._network_restriction_history: list[tuple[str, list[str]]] = []

    @property
    def id(self) -> str:
        return self._id

    @property
    def provider(self) -> str:
        return "mock"

    @property
    def workspace_dir(self) -> str:
        return self._workspace_dir

    @property
    def meta_dir(self) -> str:
        return self._meta_dir

    @property
    def network_egress_mode(self) -> str:
        return self._network_egress_mode

    @property
    def allowed_egress_domains(self) -> list[str]:
        return list(self._allowed_egress_domains)

    @property
    def network_restricted(self) -> bool:
        return self._network_restricted

    def _resolve_workspace_path(self, path: str) -> str:
        root = os.path.realpath(self._workspace_dir)
        candidate = os.path.realpath(os.path.join(root, path))
        if candidate != root and not candidate.startswith(root + os.sep):
            raise GuardrailBlockedError(
                f"Path '{path}' escapes sandbox workspace",
                reason="path_traversal_blocked",
            )
        return candidate

    async def execute_command(
        self,
        command: str,
        timeout_seconds: float = 120.0,
        env: dict[str, str] | None = None,
    ) -> SandboxExecutionResult:
        if not self._active:
            raise RuntimeError("Sandbox session has been terminated")

        full_env = os.environ.copy()
        full_env["GIT_CONFIG_SYSTEM"] = self._system_gitconfig
        if env:
            full_env.update(env)

        start = time.monotonic()
        try:
            process = await asyncio.create_subprocess_shell(
                command,
                cwd=self._workspace_dir,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                env=full_env,
            )
            stdout_bytes, stderr_bytes = await asyncio.wait_for(
                process.communicate(), timeout=float(timeout_seconds)
            )
            duration = time.monotonic() - start
            return SandboxExecutionResult(
                exit_code=process.returncode or 0,
                stdout=stdout_bytes.decode("utf-8", errors="replace"),
                stderr=stderr_bytes.decode("utf-8", errors="replace"),
                duration_seconds=duration,
            )
        except TimeoutError:
            duration = time.monotonic() - start
            return SandboxExecutionResult(
                exit_code=124,  # standard timeout exit code
                stdout="",
                stderr=f"Command timed out after {timeout_seconds} seconds",
                duration_seconds=duration,
            )

    async def read_file(self, path: str) -> str:
        if not self._active:
            raise RuntimeError("Sandbox session has been terminated")
        full_path = self._resolve_workspace_path(path)
        with open(full_path, encoding="utf-8") as f:
            return f.read()

    async def write_file(self, path: str, content: str) -> None:
        if not self._active:
            raise RuntimeError("Sandbox session has been terminated")
        full_path = self._resolve_workspace_path(path)
        os.makedirs(os.path.dirname(full_path), exist_ok=True)
        with open(full_path, "w", encoding="utf-8") as f:
            f.write(content)

    async def list_files(self, directory: str = ".") -> list[str]:
        if not self._active:
            raise RuntimeError("Sandbox session has been terminated")
        target_dir = self._resolve_workspace_path(directory)
        file_list: list[str] = []
        for root, _, files in os.walk(target_dir):
            if ".git" in root:
                continue
            for name in files:
                rel = os.path.relpath(os.path.join(root, name), self._workspace_dir)
                file_list.append(rel)
        return sorted(file_list)

    async def get_diff(self) -> str:
        if not self._active:
            raise RuntimeError("Sandbox session has been terminated")
        return await collect_workspace_diff(self.execute_command)

    @property
    def timeout_seconds(self) -> int:
        return self._timeout_seconds

    @property
    def timeout_extensions(self) -> list[int]:
        return list(self._timeout_extensions)

    async def extend_timeout(self, timeout_seconds: int) -> None:
        if not self._active:
            raise RuntimeError("Sandbox session has been terminated")
        self._timeout_seconds = timeout_seconds
        self._timeout_extensions.append(timeout_seconds)

    async def restrict_network(
        self,
        mode: str,
        allowed_domains: Sequence[str] | None = None,
    ) -> None:
        if not self._active:
            raise RuntimeError("Sandbox session has been terminated")
        domains = list(allowed_domains or [])
        self._network_egress_mode = mode
        self._allowed_egress_domains = domains
        # allowlist with empty domain list blocks all outbound traffic
        self._network_restricted = mode in ("off_after_install", "allowlist")
        self._network_restriction_history.append((mode, domains))

    async def terminate(self) -> None:
        if self._active:
            self._active = False
            shutil.rmtree(self._workspace_dir, ignore_errors=True)
            shutil.rmtree(self._meta_dir, ignore_errors=True)


class MockSandboxProvider(SandboxProvider):
    """Provisions local mock sandbox sessions."""

    async def create_sandbox(
        self,
        org_id: uuid.UUID,
        task_id: uuid.UUID,
        memory_limit_mb: int = 2048,
        timeout_seconds: int = 600,
        network_egress_mode: str = "off_after_install",
        allowed_egress_domains: Sequence[str] | None = None,
    ) -> SandboxSession:
        sandbox_id = f"sbx_{uuid.uuid4().hex[:12]}"
        temp_dir = tempfile.mkdtemp(prefix=f"aon_sbx_{task_id.hex[:6]}_")

        # Initialize bare-minimum git workspace
        session = MockSandboxSession(
            sandbox_id,
            temp_dir,
            timeout_seconds=timeout_seconds,
            network_egress_mode=network_egress_mode,
            allowed_egress_domains=allowed_egress_domains,
        )
        await session.execute_command("git init")
        await session.execute_command("git config user.name 'agentsonair[bot]'")
        await session.execute_command("git config user.email 'bot@agentsonair.dev'")

        return session
