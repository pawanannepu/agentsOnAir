"""Forge coder and Reviewer critic node implementations."""

from app.application.ports.model_gateway import (
    ForgeAgent,
    ForgeResult,
    ReviewerCritic,
    ReviewerResult,
)
from app.application.services.sandbox_workspace import SandboxWorkspace


class ForgeCoderAgent(ForgeAgent):
    """Forge autonomous engineering node executing an inner tool loop."""

    def __init__(
        self,
        api_key: str | None = None,
        model: str = "claude-sonnet-4",
    ) -> None:
        self._api_key = api_key
        self._model = model

    async def run_cycle(
        self,
        task_context: dict,
        previous_review: dict | None,
        workspace: object,
    ) -> ForgeResult:
        if not isinstance(workspace, SandboxWorkspace):
            raise TypeError("workspace must be an instance of SandboxWorkspace")

        test_command = task_context.get("test_command", "pytest")
        file_path = task_context.get("target_file", "src/module.py")
        steps_taken = 0

        # Step 1: Read existing target file if present
        try:
            content = await workspace.read_file(file_path)
            steps_taken += 1
        except Exception:
            content = ""

        # Step 2: Apply fixes or implement changes idempotently across replays
        if previous_review and previous_review.get("findings"):
            findings = previous_review["findings"]
            suggested_fix = findings[0].get("suggested_fix", "# fixed issue")
            marker = f"# Fix applied: {suggested_fix}"
            if marker in content:
                new_content = content
            else:
                new_content = f"{content}\n{marker}\n"
            summary = f"Applied requested fix: {suggested_fix}"
        else:
            title = task_context.get("title", "Feature")
            marker = f"# Implemented: {title}"
            if marker in content:
                new_content = content
            else:
                new_content = f"{content}\n{marker}\ndef solution():\n    return True\n"
            summary = f"Implemented initial solution for: {title}"

        # Step 3: Write modified code to workspace (idempotent if already written)
        if new_content != content:
            await workspace.write_file(file_path, new_content)
        steps_taken += 1

        # Optional risky tool actions requested by context (checked by PolicyEvaluator)
        risky_command = task_context.get("risky_command")
        if isinstance(risky_command, str) and risky_command.strip():
            await workspace.run_command(risky_command)
            steps_taken += 1

        risky_write_path = task_context.get("risky_write_path")
        if isinstance(risky_write_path, str) and risky_write_path.strip():
            risky_content = str(
                task_context.get("risky_write_content", "# automated config\n")
            )
            await workspace.write_file(risky_write_path, risky_content)
            steps_taken += 1

        # Step 4: Run repository test suite
        test_res = await workspace.run_test(test_command)
        steps_taken += 1

        # Step 5: Extract unified diff
        diff = await workspace.get_diff()
        steps_taken += 1

        model_name = str(task_context.get("simulated_model") or self._model)
        prompt_tokens = int(
            task_context.get("simulated_prompt_tokens")
            or max(250, len(content) // 4 + 250)
        )
        completion_tokens = int(
            task_context.get("simulated_completion_tokens")
            or max(120, len(new_content) // 4 + 100)
        )

        return ForgeResult(
            completed=True,
            summary=summary,
            steps_taken=steps_taken,
            test_output=test_res.stdout or test_res.stderr,
            diff=diff,
            provider="anthropic",
            model=model_name,
            prompt_tokens=prompt_tokens,
            completion_tokens=completion_tokens,
        )


class ReviewerCriticAgent(ReviewerCritic):
    """Reviewer independent critic node evaluating diffs with severity scoring."""

    def __init__(
        self,
        api_key: str | None = None,
        model: str = "claude-sonnet-4",
    ) -> None:
        self._api_key = api_key
        self._model = model

    async def evaluate(
        self,
        task_context: dict,
        diff: str,
        test_output: str,
    ) -> ReviewerResult:
        findings: list[dict] = []

        force_critical = task_context.get("force_review_critical", False)
        target_file = task_context.get("target_file", "src/module.py")

        if force_critical:
            findings.append(
                {
                    "file_path": target_file,
                    "line_number": 10,
                    "severity": "critical",
                    "message": "Potential security vulnerability detected",
                    "suggested_fix": "Sanitize inputs and add validation",
                }
            )
        elif "FAIL" in test_output or "error" in test_output.lower():
            findings.append(
                {
                    "file_path": target_file,
                    "line_number": 1,
                    "severity": "major",
                    "message": "Test suite failed on current diff",
                    "suggested_fix": "Fix syntax error or failing assertion",
                }
            )

        blocking_count = sum(
            1 for f in findings if f["severity"] in ("critical", "major")
        )
        non_blocking_count = sum(
            1 for f in findings if f["severity"] in ("minor", "info")
        )

        if blocking_count == 0:
            verdict = "approved"
            summary = (
                "Diff satisfies requirements, passes tests, and has 0 blocking issues."
            )
        else:
            verdict = "changes_requested"
            summary = (
                f"Reviewer identified {blocking_count} blocking issue(s) to repair."
            )

        model_name = str(task_context.get("simulated_model") or self._model)
        prompt_tokens = int(
            task_context.get("simulated_reviewer_prompt_tokens")
            or max(200, len(diff) // 4 + 150)
        )
        completion_tokens = int(
            task_context.get("simulated_reviewer_completion_tokens")
            or max(80, len(summary) // 4 + 60)
        )

        return ReviewerResult(
            verdict=verdict,
            summary=summary,
            findings=findings,
            blocking_count=blocking_count,
            non_blocking_count=non_blocking_count,
            provider="anthropic",
            model=model_name,
            prompt_tokens=prompt_tokens,
            completion_tokens=completion_tokens,
        )
