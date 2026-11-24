"""PullRequestReview repository port protocol."""

import uuid
from typing import Protocol

from app.domain.entities.pr_review_finding import PRReviewFinding
from app.domain.entities.pull_request_review import PullRequestReview


class PRReviewRepository(Protocol):
    """Repository port for pull request code reviews."""

    async def create_review(
        self,
        org_id: uuid.UUID,
        repo_id: uuid.UUID,
        pr_number: int,
        pr_title: str,
        pr_author: str,
        head_commit_sha: str,
        base_commit_sha: str,
        model_name: str,
        task_id: uuid.UUID | None = None,
    ) -> PullRequestReview:
        """Create a new pending PR review."""
        ...

    async def get_by_id(
        self, org_id: uuid.UUID, review_id: uuid.UUID
    ) -> PullRequestReview:
        """Retrieve a review by ID scoped to organization."""
        ...

    async def find_active_by_repo_and_pr(
        self, repo_id: uuid.UUID, pr_number: int
    ) -> PullRequestReview | None:
        """Find an active review for a PR (pending/analyzing/reviewing/posting)."""
        ...

    async def list_by_repo_and_pr(
        self,
        org_id: uuid.UUID,
        repo_id: uuid.UUID,
        pr_number: int,
        page: int = 1,
        page_size: int = 20,
    ) -> tuple[list[PullRequestReview], int]:
        """List reviews for a PR in a repository with pagination."""
        ...

    async def update_status(
        self,
        review_id: uuid.UUID,
        status: str,
        verdict: str | None = None,
        summary: str | None = None,
        github_review_id: int | None = None,
        context_token_count: int | None = None,
        execution_duration_ms: int | None = None,
        error_message: str | None = None,
    ) -> PullRequestReview:
        """Update review status and optional fields."""
        ...

    async def add_findings(
        self,
        review_id: uuid.UUID,
        findings: list[dict],
    ) -> list[PRReviewFinding]:
        """Bulk insert findings for a review."""
        ...

    async def list_findings(
        self,
        review_id: uuid.UUID,
        page: int = 1,
        page_size: int = 50,
    ) -> tuple[list[PRReviewFinding], int]:
        """List findings for a review with pagination."""
        ...

    async def update_finding_github_id(
        self,
        finding_id: uuid.UUID,
        github_comment_id: int,
    ) -> None:
        """Set the GitHub inline comment ID on a finding after submission."""
        ...
