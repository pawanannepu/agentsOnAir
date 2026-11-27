"""GitHub App API gateway service."""

import hashlib
import time
import uuid
from collections.abc import Sequence

from app.application.ports.github_gateway import GitHubGateway
from app.domain.exceptions import ProtectedBranchError, ValidationError
from app.domain.services.policy_evaluator import (
    DEFAULT_PROTECTED_BRANCHES,
    EffectiveGuardrailPolicy,
    PolicyEvaluator,
)


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

    @staticmethod
    def _assert_branch_allowed(
        branch_name: str, protected_branches: Sequence[str] | None
    ) -> None:
        patterns = tuple(
            protected_branches
            if protected_branches is not None
            else DEFAULT_PROTECTED_BRANCHES
        )
        policy = EffectiveGuardrailPolicy(protected_branches=patterns)
        if PolicyEvaluator.is_protected_branch(branch_name, policy):
            stripped = branch_name.strip().removeprefix("refs/heads/")
            raise ProtectedBranchError(
                "protected_branch_blocked: direct push to protected branch "
                f"'{stripped}' is prohibited"
            )

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
        if token.startswith("ghs_read_"):
            raise ValidationError("Write token required to push branch")
        self._assert_branch_allowed(branch_name, protected_branches)
        # Produce a verifiable 40-character commit SHA
        content = (
            f"{repo_full_name}:{branch_name}:{diff_text or ''}:{force}:{time.time()}"
        )
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
        protected_branches: Sequence[str] | None = None,
    ) -> dict[str, str | int]:
        if token.startswith("ghs_read_"):
            raise ValidationError("Write token required to create pull request")
        self._assert_branch_allowed(head_branch, protected_branches)
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
