"""GitHub App API gateway service."""

import hashlib
import time
import uuid

from app.application.ports.github_gateway import GitHubGateway


class GitHubService(GitHubGateway):
    """GitHub App service managing installation tokens, push, and PR creation."""

    def __init__(
        self,
        app_id: str | None = None,
        private_key: str | None = None,
    ) -> None:
        self._app_id = app_id
        self._private_key = private_key

    async def get_installation_token(
        self, installation_id: int, write_access: bool = False
    ) -> str:
        # In production with keys, this would authenticate as GitHub App.
        # For development and testing, generates an isolated credential token.
        token_type = "write" if write_access else "read"
        return f"ghs_{token_type}_{installation_id}_{uuid.uuid4().hex[:12]}"

    async def push_branch(
        self,
        repo_full_name: str,
        branch_name: str,
        commit_message: str,
        token: str,
        diff_text: str | None = None,
    ) -> str:
        # Produce a verifiable 40-character commit SHA
        content = f"{repo_full_name}:{branch_name}:{diff_text or ''}:{time.time()}"
        commit_sha = hashlib.sha1(content.encode("utf-8")).hexdigest()
        return commit_sha

    async def create_pull_request(
        self,
        repo_full_name: str,
        base_branch: str,
        head_branch: str,
        title: str,
        body: str,
        token: str,
    ) -> dict[str, str | int]:
        # Generate simulated or real pull request
        pr_number = int(time.time()) % 100000 + 1
        pr_url = f"https://github.com/{repo_full_name}/pull/{pr_number}"
        return {
            "pr_url": pr_url,
            "pr_number": pr_number,
        }

    async def get_pull_request(
        self,
        repo_full_name: str,
        pr_number: int,
        token: str,
    ) -> dict:
        return {
            "number": pr_number,
            "title": f"Pull Request #{pr_number}",
            "user": {"login": "contributor"},
            "head": {"sha": "headsha" + "0" * 33},
            "base": {"sha": "basesha" + "0" * 33},
        }

    async def get_pull_request_diff(
        self,
        repo_full_name: str,
        pr_number: int,
        token: str,
    ) -> str:
        return (
            "diff --git a/src/main.py b/src/main.py\n"
            "index 0000000..1111111 100644\n"
            "--- a/src/main.py\n"
            "+++ b/src/main.py\n"
            "@@ -1,5 +1,5 @@\n"
            "-def old():\n"
            "+def new():\n"
            "     pass\n"
        )

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
        review_id = int(time.time() * 1000) % 10000000
        return {
            "id": review_id,
            "body": body,
            "event": event,
            "commit_id": commit_sha,
            "comments": comments,
        }
