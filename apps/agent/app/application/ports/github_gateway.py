"""GitHub gateway port protocol."""

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
    ) -> dict[str, str | int]:
        """Open a pull request on GitHub."""
        ...
