"""Model gateway ports for Forge coder and Reviewer critic."""

from dataclasses import dataclass
from typing import Protocol


@dataclass(slots=True)
class ForgeResult:
    """Outcome of Forge inner tool execution."""

    completed: bool
    summary: str
    steps_taken: int
    test_output: str
    diff: str


@dataclass(slots=True)
class ReviewerFinding:
    """Individual code review finding."""

    file_path: str
    line_number: int
    severity: str  # "critical", "major", "minor", "info"
    message: str
    suggested_fix: str


@dataclass(slots=True)
class ReviewerResult:
    """Structured critique output from Reviewer critic node."""

    verdict: str  # "approved" or "changes_requested"
    summary: str
    findings: list[dict]
    blocking_count: int
    non_blocking_count: int


class ForgeAgent(Protocol):
    """Forge autonomous engineering node."""

    async def run_cycle(
        self,
        task_context: dict,
        previous_review: dict | None,
        workspace: object,
    ) -> ForgeResult:
        """Execute inner ReAct loop to implement code fixes and run tests."""
        ...


class ReviewerCritic(Protocol):
    """Reviewer autonomous critic node."""

    async def evaluate(
        self,
        task_context: dict,
        diff: str,
        test_output: str,
    ) -> ReviewerResult:
        """Perform independent critique of diff and test outputs."""
        ...
