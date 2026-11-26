"""Sandbox workspace coordinator for repo init and inner tool execution."""

import uuid

from app.application.ports.event_streamer import EventStreamer
from app.application.ports.sandbox import (
    SandboxExecutionResult,
    SandboxSession,
)
from app.domain.exceptions import BaselineTestFailedError


class SandboxWorkspace:
    """Manages workspace lifecycle, testing, and tool execution inside a sandbox."""

    def __init__(
        self,
        session: SandboxSession,
        task_id: uuid.UUID,
        event_streamer: EventStreamer | None = None,
    ) -> None:
        self.session = session
        self.task_id = task_id
        self.event_streamer = event_streamer
        self.channel = f"task:{task_id}:stream"

    async def _stream(self, event_type: str, data: dict) -> None:
        if self.event_streamer:
            await self.event_streamer.stream_event(self.channel, event_type, data)

    async def _emit_log(self, chunk: str, stream: str = "stdout") -> None:
        if self.event_streamer and chunk:
            await self.event_streamer.append_event(
                self.task_id,
                "task.log",
                {"stream": stream, "chunk": chunk},
            )

    async def init_workspace(
        self,
        repo_url_with_read_token: str | None,
        base_branch: str = "main",
        work_branch: str = "agentsonair/work",
    ) -> None:
        """Initialize workspace with read-only clone and create work branch (AC-3)."""
        await self._stream(
            "workspace_init_started",
            {"base_branch": base_branch, "work_branch": work_branch},
        )
        await self._emit_log(
            f"\u001b[34m[workspace:init]\u001b[0m Initializing workspace "
            f"(base: {base_branch}, work: {work_branch})...\n"
        )

        if repo_url_with_read_token:
            # Clone repo using read-only token
            clone_cmd = (
                f"git clone --branch {base_branch} --depth 50 "
                f"{repo_url_with_read_token} ."
            )
            clone_res = await self.session.execute_command(clone_cmd)
            if clone_res.exit_code != 0:
                await self.session.execute_command(
                    f"git clone --depth 50 {repo_url_with_read_token} ."
                )

        # Configure commit identity for agentsonair[bot]
        await self.session.execute_command("git config user.name 'agentsonair[bot]'")
        await self.session.execute_command(
            "git config user.email 'bot@agentsonair.dev'"
        )

        # Checkout work branch
        await self.session.execute_command(f"git checkout -b {work_branch}")

        await self._stream(
            "workspace_init_completed",
            {"work_branch": work_branch, "status": "ready"},
        )
        await self._emit_log(
            f"\u001b[32m[workspace:ready]\u001b[0m Branch {work_branch} "
            f"checked out and ready.\n"
        )

    async def run_baseline_tests(
        self, test_command: str, timeout_seconds: int = 120
    ) -> SandboxExecutionResult:
        """Run repository test suite on base branch before edits (AC-3)."""
        await self._stream(
            "baseline_test_started",
            {"command": test_command, "timeout": timeout_seconds},
        )
        await self._emit_log(
            f"\u001b[33m[baseline:test]\u001b[0m Running baseline tests: "
            f"{test_command}\n"
        )

        result = await self.session.execute_command(
            test_command, timeout_seconds=timeout_seconds
        )

        if result.stdout:
            await self._emit_log(result.stdout, "stdout")
        if result.stderr:
            await self._emit_log(result.stderr, "stderr")

        await self._stream(
            "baseline_test_completed",
            {
                "exit_code": result.exit_code,
                "stdout": result.stdout,
                "stderr": result.stderr,
                "duration_seconds": result.duration_seconds,
            },
        )

        if result.exit_code != 0:
            error_msg = (
                f"Baseline tests failed with code {result.exit_code}.\n"
                f"Stdout: {result.stdout}\nStderr: {result.stderr}"
            )
            raise BaselineTestFailedError(error_msg)

        return result

    async def read_file(self, path: str) -> str:
        """Tool: read file from workspace."""
        await self._stream("tool_read_file", {"path": path})
        return await self.session.read_file(path)

    async def write_file(self, path: str, content: str) -> str:
        """Tool: write file to workspace."""
        await self.session.write_file(path, content)
        await self._stream("tool_write_file", {"path": path, "bytes": len(content)})
        await self._emit_log(
            f"\u001b[35m[tool:edit]\u001b[0m Modified {path} ({len(content)} bytes)\n"
        )
        return f"Successfully wrote {len(content)} bytes to {path}"

    async def run_test(
        self, command: str, timeout_seconds: int = 120
    ) -> SandboxExecutionResult:
        """Tool: run test command inside workspace."""
        await self._stream(
            "tool_run_test_started",
            {"command": command, "timeout": timeout_seconds},
        )
        await self._emit_log(f"\u001b[33m[tool:test]\u001b[0m $ {command}\n")

        result = await self.session.execute_command(
            command, timeout_seconds=timeout_seconds
        )

        if result.stdout:
            await self._emit_log(result.stdout, "stdout")
        if result.stderr:
            await self._emit_log(result.stderr, "stderr")

        await self._stream(
            "tool_run_test_completed",
            {
                "command": command,
                "exit_code": result.exit_code,
                "stdout": result.stdout,
                "stderr": result.stderr,
            },
        )
        return result

    async def run_command(
        self, command: str, timeout_seconds: int = 120
    ) -> SandboxExecutionResult:
        """Tool: execute shell command inside workspace."""
        await self._stream(
            "tool_run_command_started",
            {"command": command, "timeout": timeout_seconds},
        )
        await self._emit_log(f"\u001b[36m[tool:bash]\u001b[0m $ {command}\n")

        result = await self.session.execute_command(
            command, timeout_seconds=timeout_seconds
        )

        if result.stdout:
            await self._emit_log(result.stdout, "stdout")
        if result.stderr:
            await self._emit_log(result.stderr, "stderr")

        await self._stream(
            "tool_run_command_completed",
            {
                "command": command,
                "exit_code": result.exit_code,
                "stdout": result.stdout,
                "stderr": result.stderr,
            },
        )
        return result

    async def get_diff(self) -> str:
        """Tool: get git unified diff of modifications."""
        diff = await self.session.get_diff()
        await self._stream("tool_get_diff", {"diff_length": len(diff)})
        return diff
