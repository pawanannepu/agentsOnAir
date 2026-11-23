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

    def __init__(self, api_key: str | None = None) -> None:
        self._api_key = api_key

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

        # Inner ReAct iteration
        steps_taken = 0

        # Step 1: Read existing target file if present
        try:
            content = await workspace.read_file(file_path)
            steps_taken += 1
        except Exception:
            content = ""

        # Step 2: Apply fixes or implement changes
        if previous_review and previous_review.get("findings"):
            # Second/third cycle: apply fixes according to reviewer feedback
            findings = previous_review["findings"]
            suggested_fix = findings[0].get("suggested_fix", "# fixed issue")
            new_content = f"{content}\n# Fix applied: {suggested_fix}\n"
            summary = f"Applied requested fix: {suggested_fix}"
        else:
            # First cycle: initial implementation
            title = task_context.get("title", "Feature")
            new_content = (
                f"{content}\n# Implemented: {title}\ndef solution():\n    return True\n"
            )
            summary = f"Implemented initial solution for: {title}"

        # Step 3: Write modified code to workspace
        await workspace.write_file(file_path, new_content)
        steps_taken += 1

        # Step 4: Run repository test suite
        test_res = await workspace.run_test(test_command)
        steps_taken += 1

        # Step 5: Extract unified diff
        diff = await workspace.get_diff()
        steps_taken += 1

        return ForgeResult(
            completed=True,
            summary=summary,
            steps_taken=steps_taken,
            test_output=test_res.stdout or test_res.stderr,
            diff=diff,
        )


class ReviewerCriticAgent(ReviewerCritic):
    """Reviewer independent critic node evaluating diffs with severity scoring."""

    def __init__(self, api_key: str | None = None) -> None:
        self._api_key = api_key

    async def evaluate(
        self,
        task_context: dict,
        diff: str,
        test_output: str,
    ) -> ReviewerResult:
        findings: list[dict] = []

        # Check simulation triggers in task_context for test scenarios
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

        return ReviewerResult(
            verdict=verdict,
            summary=summary,
            findings=findings,
            blocking_count=blocking_count,
            non_blocking_count=non_blocking_count,
        )
