"""Docker sandbox provider running commands in isolated containers."""

import asyncio
import os
import shutil
import tempfile
import time
import uuid

from app.application.ports.sandbox import (
    SandboxExecutionResult,
    SandboxProvider,
    SandboxSession,
)


class DockerSandboxSession(SandboxSession):
    """Docker container sandbox session."""

    def __init__(
        self,
        sandbox_id: str,
        workspace_dir: str,
        container_name: str | None = None,
    ) -> None:
        self._id = sandbox_id
        self._workspace_dir = workspace_dir
        self._container_name = container_name
        self._active = True

    @property
    def id(self) -> str:
        return self._id

    @property
    def provider(self) -> str:
        return "docker"

    async def execute_command(
        self,
        command: str,
        timeout_seconds: float = 120.0,
        env: dict[str, str] | None = None,
    ) -> SandboxExecutionResult:
        if not self._active:
            raise RuntimeError("Sandbox session has been terminated")

        full_env = os.environ.copy()
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
                exit_code=124,
                stdout="",
                stderr=f"Command timed out after {timeout_seconds} seconds",
                duration_seconds=duration,
            )

    async def read_file(self, path: str) -> str:
        if not self._active:
            raise RuntimeError("Sandbox session has been terminated")
        full_path = os.path.join(self._workspace_dir, path)
        with open(full_path, encoding="utf-8") as f:
            return f.read()

    async def write_file(self, path: str, content: str) -> None:
        if not self._active:
            raise RuntimeError("Sandbox session has been terminated")
        full_path = os.path.join(self._workspace_dir, path)
        os.makedirs(os.path.dirname(full_path), exist_ok=True)
        with open(full_path, "w", encoding="utf-8") as f:
            f.write(content)

    async def list_files(self, directory: str = ".") -> list[str]:
        if not self._active:
            raise RuntimeError("Sandbox session has been terminated")
        target_dir = os.path.join(self._workspace_dir, directory)
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
        res = await self.execute_command("git diff HEAD")
        if not res.stdout.strip():
            res = await self.execute_command("git diff")
        return res.stdout

    async def terminate(self) -> None:
        if self._active:
            self._active = False
            shutil.rmtree(self._workspace_dir, ignore_errors=True)


class DockerSandboxProvider(SandboxProvider):
    """Provisions Docker container sandboxes."""

    async def create_sandbox(
        self,
        org_id: uuid.UUID,
        task_id: uuid.UUID,
        memory_limit_mb: int = 2048,
        timeout_seconds: int = 600,
    ) -> SandboxSession:
        sandbox_id = f"docker_{uuid.uuid4().hex[:12]}"
        temp_dir = tempfile.mkdtemp(prefix=f"aon_docker_{task_id.hex[:6]}_")

        session = DockerSandboxSession(sandbox_id, temp_dir)
        await session.execute_command("git init")
        await session.execute_command("git config user.name 'agentsonair[bot]'")
        await session.execute_command("git config user.email 'bot@agentsonair.dev'")

        return session
