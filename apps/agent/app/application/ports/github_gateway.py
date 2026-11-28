"""GitHub gateway port protocol."""

from collections.abc import Sequence
from typing import Protocol


class GitHubGateway(Protocol):
    """Port interface for GitHub App interactions."""

    async def get_installation_token(
        self, installation_id: int, write_access: bool = False
    ) -> str:
        """Obtain short-lived installation access token."""
        ...

    async def push_branch(
        self,
        repo_full_name: str,
        branch_name: str,
        commit_message: str,
        token: str,
        diff_text: str | None = None,
        protected_branches: Sequence[str] | None = None,
        force: bool = False,
    ) -> str:
        """Push work branch to GitHub and return commit SHA."""
        ...

    async def create_pull_request(
        self,
        repo_full_name: str,
        base_branch: str,
        head_branch: str,
        title: str,
        body: str,
        token: str,
        protected_branches: Sequence[str] | None = None,
    ) -> dict[str, str | int]:
        """Open a pull request on GitHub."""
        ...

    async def get_pull_request(
        self,
        repo_full_name: str,
        pr_number: int,
        token: str,
    ) -> dict:
        """Fetch pull request metadata from GitHub API."""
        ...

    async def get_pull_request_diff(
        self,
        repo_full_name: str,
        pr_number: int,
        token: str,
    ) -> str:
        """Fetch unified diff for pull request."""
        ...

    async def submit_review(
        self,
        repo_full_name: str,
        pr_number: int,
        commit_sha: str,
        body: str,
        event: str,
        comments: list[dict],
        token: str,
    ) -> dict:
        """Submit unified review with optional inline comments."""
        ...

    async def list_review_comments(
        self,
        repo_full_name: str,
        pr_number: int,
        github_review_id: int,
        token: str,
    ) -> list[dict]:
        """Fetch inline comments created by a submitted GitHub pull request review."""
        ...
