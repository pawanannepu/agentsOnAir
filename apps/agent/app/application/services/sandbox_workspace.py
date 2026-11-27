"""Sandbox workspace coordinator for repo init, guardrails, and inner tool execution."""

import json
import os
import re
import shlex
import uuid
from collections.abc import Awaitable, Callable, Sequence

from app.application.ports.event_streamer import EventStreamer
from app.application.ports.sandbox import (
    SandboxExecutionResult,
    SandboxSession,
)
from app.domain.exceptions import (
    ApprovalRequiredError,
    BaselineTestFailedError,
    GuardrailBlockedError,
    ValidationError,
)
from app.domain.services.policy_evaluator import (
    DEFAULT_PROTECTED_BRANCHES,
    EffectiveGuardrailPolicy,
    PolicyEvaluator,
    RiskClassification,
)

ApprovalChecker = Callable[[RiskClassification], Awaitable[bool]]


def _strip_url_credentials(repo_url: str) -> str:
    """Remove embedded username/token credentials from HTTPS git remote URLs."""
    return re.sub(r"(https?://)[^/@]+@", r"\1", repo_url)


def _build_pre_push_hook_script(protected_branches: Sequence[str]) -> str:
    """Build executable pre-push hook script blocking pushes to protected branches."""
    patterns_json = json.dumps(list(protected_branches))
    return (
        "#!/usr/bin/env sh\n"
        f"PATTERNS_JSON={shlex.quote(patterns_json)}\n"
        "while IFS=' ' read -r local_ref local_sha remote_ref remote_sha; do\n"
        '  [ -z "$remote_ref" ] && continue\n'
        '  branch="${remote_ref#refs/heads/}"\n'
        "  if command -v python3 >/dev/null 2>&1; then\n"
        '    python3 -c "import fnmatch, json, sys; branch=sys.argv[1]; '
        "pats=json.loads(sys.argv[2]); "
        'sys.exit(1 if any(fnmatch.fnmatchcase(branch, p) for p in pats) else 0)" '
        '"$branch" "$PATTERNS_JSON"\n'
        "    if [ $? -ne 0 ]; then\n"
        '      echo "protected_branch_blocked: direct push to '
        "protected branch '$branch' is prohibited\" >&2\n"
        "      exit 1\n"
        "    fi\n"
        "  else\n"
        '    case "$branch" in\n'
        "      main|master|release/*)\n"
        '        echo "protected_branch_blocked: direct push to '
        "protected branch '$branch' is prohibited\" >&2\n"
        "        exit 1\n"
        "        ;;\n"
        "    esac\n"
        "  fi\n"
        "done\n"
        "exit 0\n"
    )


class SandboxWorkspace:
    """Manages workspace lifecycle, testing, guardrails, and tool calls."""

    def __init__(
        self,
        session: SandboxSession,
        task_id: uuid.UUID,
        event_streamer: EventStreamer | None = None,
        policy: EffectiveGuardrailPolicy | None = None,
        policy_evaluator: PolicyEvaluator | None = None,
        cycle_number: int = 1,
        approval_checker: ApprovalChecker | None = None,
    ) -> None:
        self.session = session
        self.task_id = task_id
        self.event_streamer = event_streamer
        self.channel = f"task:{task_id}:stream"
        self.policy = policy or EffectiveGuardrailPolicy()
        self.policy_evaluator = policy_evaluator or PolicyEvaluator()
        self.cycle_number = cycle_number
        self.approval_checker = approval_checker

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

    async def _enforce_classification(self, classification: RiskClassification) -> None:
        if classification.decision == "allow":
            return
        if classification.decision == "block":
            raise GuardrailBlockedError(
                classification.action_summary or "Action blocked by guardrail policy",
                reason=classification.reason or "guardrail_blocked",
            )
        if classification.decision == "require_approval":
            if self.approval_checker is not None:
                approved = await self.approval_checker(classification)
                if approved:
                    return
            raise ApprovalRequiredError(classification)

    async def install_branch_protection_hook(
        self, protected_branches: Sequence[str] | None = None
    ) -> str:
        """Install pre-push hook via git config --system core.hooksPath."""
        patterns = tuple(
            protected_branches
            if protected_branches is not None
            else self.policy.protected_branches or DEFAULT_PROTECTED_BRANCHES
        )
        script = _build_pre_push_hook_script(patterns)
        hooks_dir = getattr(self.session, "meta_dir", None)
        if hooks_dir:
            hook_dir = os.path.join(hooks_dir, "hooks")
            os.makedirs(hook_dir, exist_ok=True)
            hook_path = os.path.join(hook_dir, "pre-push")
            with open(hook_path, "w", encoding="utf-8") as handle:
                handle.write(script)
            os.chmod(hook_path, 0o755)
        else:
            hook_dir = "/tmp/aoa-hooks"
            await self.session.execute_command(
                f"mkdir -p {shlex.quote(hook_dir)} && "
                f"cat << 'EOF' > {shlex.quote(hook_dir + '/pre-push')}\n"
                f"{script}"
                f"EOF\n"
                f"chmod +x {shlex.quote(hook_dir + '/pre-push')}"
            )

        res = await self.session.execute_command(
            f"git config --system core.hooksPath {shlex.quote(hook_dir)}"
        )
        if res.exit_code != 0:
            await self.session.execute_command(
                f"git config core.hooksPath {shlex.quote(hook_dir)}"
            )
        return hook_dir

    async def strip_remote_credentials(self) -> None:
        """Remove any embedded credentials from .git/config remote URLs."""
        remote_res = await self.session.execute_command("git remote get-url origin")
        if remote_res.exit_code == 0 and remote_res.stdout.strip():
            raw_url = remote_res.stdout.strip()
            sanitized = _strip_url_credentials(raw_url)
            if sanitized != raw_url:
                await self.session.execute_command(
                    f"git remote set-url origin {shlex.quote(sanitized)}"
                )
        await self.session.execute_command(
            "git config --local --unset-all http.extraheader || true"
        )

    async def init_workspace(
        self,
        repo_url_with_read_token: str | None,
        base_branch: str = "main",
        work_branch: str = "agentsonair/work",
        protected_branches: Sequence[str] | None = None,
        install_command: str | None = None,
    ) -> None:
        """Initialize workspace, strip creds, add branch hook, lock egress."""
        if repo_url_with_read_token and "ghs_write_" in repo_url_with_read_token:
            raise ValidationError(
                "Write credentials must never be passed into sandbox workspace"
            )

        await self._stream(
            "workspace_init_started",
            {"base_branch": base_branch, "work_branch": work_branch},
        )
        await self._emit_log(
            f"\u001b[34m[workspace:init]\u001b[0m Initializing workspace "
            f"(base: {base_branch}, work: {work_branch})...\n"
        )

        if repo_url_with_read_token:
            # Providers may pre-initialize an empty .git dir; remove before clone.
            await self.session.execute_command(
                "if [ -d .git ] && ! git rev-parse --verify HEAD >/dev/null 2>&1; "
                "then rm -rf .git; fi"
            )
            clone_cmd = (
                f"git clone --branch {shlex.quote(base_branch)} --depth 50 "
                f"{shlex.quote(repo_url_with_read_token)} ."
            )
            clone_res = await self.session.execute_command(clone_cmd)
            if clone_res.exit_code != 0:
                clone_res = await self.session.execute_command(
                    f"git clone --depth 50 {shlex.quote(repo_url_with_read_token)} ."
                )
            if clone_res.exit_code != 0:
                sanitized_err = _strip_url_credentials(clone_res.stderr or "")
                raise ValidationError(
                    f"Failed to clone repository: {sanitized_err.strip()}"
                )
            await self.strip_remote_credentials()

        await self.session.execute_command("git config user.name 'agentsonair[bot]'")
        await self.session.execute_command(
            "git config user.email 'bot@agentsonair.dev'"
        )
        await self.install_branch_protection_hook(protected_branches)
        await self.session.execute_command(
            f"git checkout -b {shlex.quote(work_branch)}"
        )

        if install_command and install_command.strip():
            await self._emit_log(
                f"\u001b[34m[workspace:install]\u001b[0m $ {install_command}\n"
            )
            install_res = await self.session.execute_command(install_command)
            if install_res.stdout:
                await self._emit_log(install_res.stdout, "stdout")
            if install_res.stderr:
                await self._emit_log(install_res.stderr, "stderr")

        await self.session.restrict_network(
            self.policy.network_egress_mode,
            self.policy.allowed_egress_domains,
        )

        await self._stream(
            "workspace_init_completed",
            {
                "work_branch": work_branch,
                "status": "ready",
                "network_egress_mode": self.policy.network_egress_mode,
            },
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
        """Tool: write file to workspace after sensitive-path guardrail check."""
        classification = self.policy_evaluator.classify_file_write(
            path, self.policy, cycle_number=self.cycle_number
        )
        await self._enforce_classification(classification)

        await self.session.write_file(path, content)
        await self._stream("tool_write_file", {"path": path, "bytes": len(content)})
        await self._emit_log(
            f"\u001b[35m[tool:edit]\u001b[0m Modified {path} ({len(content)} bytes)\n"
        )
        return f"Successfully wrote {len(content)} bytes to {path}"

    async def run_test(
        self, command: str, timeout_seconds: int = 120
    ) -> SandboxExecutionResult:
        """Tool: run repository tests (exempt from command blocklist)."""
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
        """Tool: execute shell command after guardrail classification."""
        classification = self.policy_evaluator.classify_command(
            command, self.policy, cycle_number=self.cycle_number
        )
        await self._enforce_classification(classification)

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
