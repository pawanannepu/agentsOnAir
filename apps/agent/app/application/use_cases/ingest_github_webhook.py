"""GitHub App webhook ingestion use case."""

import json
import uuid
from dataclasses import dataclass

from app.application.ports.github_gateway import GitHubGateway
from app.application.ports.pr_review_repository import PRReviewRepository
from app.application.ports.repository_repository import RepositoryRepository
from app.application.ports.task_repository import TaskRepository
from app.domain.exceptions import WebhookSignatureError
from app.infrastructure.github.webhook import verify_github_signature


@dataclass(slots=True)
class WebhookIngestResult:
    """Result of processing a GitHub webhook event."""

    status: str  # "queued" or "ignored"
    task_id: str | None = None
    review_id: str | None = None
    reason: str | None = None


class IngestGitHubWebhookUseCase:
    """Ingest, verify, filter, and schedule GitHub webhook events."""

    def __init__(
        self,
        repository_repo: RepositoryRepository,
        task_repo: TaskRepository,
        pr_review_repo: PRReviewRepository | None = None,
        github_gateway: GitHubGateway | None = None,
    ) -> None:
        self._repository_repo = repository_repo
        self._task_repo = task_repo
        self._pr_review_repo = pr_review_repo
        self._github_gateway = github_gateway

    async def execute(
        self,
        event_type: str | None,
        delivery_id: str | None,
        payload_bytes: bytes,
        signature_header: str | None,
        webhook_secret: str,
    ) -> WebhookIngestResult:
        # 1. Verify HMAC SHA256 signature
        if not verify_github_signature(payload_bytes, signature_header, webhook_secret):
            raise WebhookSignatureError("Invalid webhook signature")

        # 2. Parse payload JSON
        try:
            payload = json.loads(payload_bytes.decode("utf-8"))
        except Exception:
            return WebhookIngestResult(
                status="ignored",
                reason="malformed_json_payload",
            )

        if not event_type:
            return WebhookIngestResult(
                status="ignored",
                reason="missing_event_header",
            )

        action = payload.get("action", "")

        # 3. Handle Pull Request Events and Review Comments
        if event_type == "pull_request":
            if action not in ("opened", "synchronize"):
                return WebhookIngestResult(
                    status="ignored",
                    reason=f"unhandled_pr_action_{action}",
                )

            pr_data = payload.get("pull_request", {})
            pr_author = pr_data.get("user", {}).get("login", "")

            # AC-1: Bot author exclusion
            if pr_author == "agentsonair[bot]":
                return WebhookIngestResult(
                    status="ignored",
                    reason="bot_author_excluded",
                )

            # Resolve repository
            github_repo = payload.get("repository", {})
            github_repo_id = github_repo.get("id")
            if not github_repo_id:
                return WebhookIngestResult(
                    status="ignored",
                    reason="missing_repository_id",
                )

            repo = await self._repository_repo.find_by_github_repo_id(
                int(github_repo_id)
            )
            if not repo:
                return WebhookIngestResult(
                    status="ignored",
                    reason="repository_not_tracked",
                )

            review_settings = getattr(repo, "review_settings", {}) or {}
            if not review_settings.get("enabled", True):
                return WebhookIngestResult(
                    status="ignored",
                    reason="reviews_disabled",
                )
            if not review_settings.get("auto_review", True):
                return WebhookIngestResult(
                    status="ignored",
                    reason="auto_review_disabled",
                )
            is_bot = pr_data.get("user", {}).get("type") == "Bot" or pr_author.endswith(
                "[bot]"
            )
            if review_settings.get("ignore_all_bots", False) and is_bot:
                return WebhookIngestResult(
                    status="ignored",
                    reason="bot_author_excluded_by_settings",
                )

            pr_number = pr_data.get("number")
            if not pr_number:
                return WebhookIngestResult(
                    status="ignored",
                    reason="missing_pr_number",
                )

            # Check active PR review
            if self._pr_review_repo:
                active_review = await self._pr_review_repo.find_active_by_repo_and_pr(
                    repo.id, int(pr_number)
                )
                if active_review:
                    return WebhookIngestResult(
                        status="ignored",
                        review_id=str(active_review.id),
                        reason="active_review_already_exists",
                    )

                review = await self._pr_review_repo.create_review(
                    org_id=repo.org_id,
                    repo_id=repo.id,
                    pr_number=int(pr_number),
                    pr_title=pr_data.get("title", f"PR #{pr_number}"),
                    pr_author=pr_author,
                    head_commit_sha=pr_data.get("head", {}).get("sha", ""),
                    base_commit_sha=pr_data.get("base", {}).get("sha", ""),
                    model_name="claude-3-5-sonnet",
                )
                return WebhookIngestResult(
                    status="queued",
                    review_id=str(review.id),
                )

            return WebhookIngestResult(status="queued")

        # 4. Handle issue_comment events (disambiguating PR review vs autonomous task)
        if event_type == "issue_comment" and action == "created":
            comment_body = payload.get("comment", {}).get("body", "")
            sender_login = payload.get("sender", {}).get("login", "")
            sender_type = payload.get("sender", {}).get("type", "")

            # Exclude bot senders
            if sender_login == "agentsonair[bot]" or sender_type == "Bot":
                return WebhookIngestResult(
                    status="ignored",
                    reason="bot_comment_excluded",
                )

            is_pr = "pull_request" in payload.get("issue", {})
            if "@agentsonair review" in comment_body:
                if not is_pr:
                    return WebhookIngestResult(
                        status="ignored",
                        reason="review_command_on_issue_not_pr",
                    )

                # Fetch PR metadata from GitHub
                github_repo = payload.get("repository", {})
                github_repo_id = github_repo.get("id")
                if not github_repo_id:
                    return WebhookIngestResult(
                        status="ignored",
                        reason="missing_repository_id",
                    )

                repo = await self._repository_repo.find_by_github_repo_id(
                    int(github_repo_id)
                )
                if not repo:
                    return WebhookIngestResult(
                        status="ignored",
                        reason="repository_not_tracked",
                    )

                issue_number = payload.get("issue", {}).get("number")
                if not issue_number:
                    return WebhookIngestResult(
                        status="ignored",
                        reason="missing_issue_number",
                    )

                head_sha = ""
                base_sha = ""
                pr_title = payload.get("issue", {}).get("title", f"PR #{issue_number}")
                pr_author = payload.get("issue", {}).get("user", {}).get("login", "")

                if self._github_gateway:
                    token = await self._github_gateway.get_installation_token(
                        repo.github_installation_id
                    )
                    pr_info = await self._github_gateway.get_pull_request(
                        repo.full_name, int(issue_number), token
                    )
                    head_sha = pr_info.get("head", {}).get("sha", "")
                    base_sha = pr_info.get("base", {}).get("sha", "")
                    pr_title = pr_info.get("title", pr_title)
                    pr_author = pr_info.get("user", {}).get("login", pr_author)

                if self._pr_review_repo:
                    active_review = (
                        await self._pr_review_repo.find_active_by_repo_and_pr(
                            repo.id, int(issue_number)
                        )
                    )
                    if active_review:
                        return WebhookIngestResult(
                            status="ignored",
                            review_id=str(active_review.id),
                            reason="active_review_already_exists",
                        )

                    review = await self._pr_review_repo.create_review(
                        org_id=repo.org_id,
                        repo_id=repo.id,
                        pr_number=int(issue_number),
                        pr_title=pr_title,
                        pr_author=pr_author,
                        head_commit_sha=head_sha,
                        base_commit_sha=base_sha,
                        model_name="claude-3-5-sonnet",
                    )
                    return WebhookIngestResult(
                        status="queued",
                        review_id=str(review.id),
                    )

                return WebhookIngestResult(status="queued")

            # Fall through for regular issue tasks if @agentsonair is mentioned
            # without review
            if is_pr:
                # Regular agent instruction on a PR comment without review keyword
                return WebhookIngestResult(
                    status="ignored",
                    reason="agent_instruction_on_pr_without_review",
                )

        # 5. Filter event type and action for standard tasks (issues / issue_comment)
        event_matched = False
        trigger_type = "github_issue"

        if event_type == "issues":
            if action == "opened":
                event_matched = True
            elif action == "labeled":
                label_name = payload.get("label", {}).get("name", "")
                if label_name == "agentsonair":
                    event_matched = True
        elif event_type == "issue_comment":
            if action == "created":
                comment_body = payload.get("comment", {}).get("body", "")
                if "@agentsonair" in comment_body:
                    event_matched = True
                    trigger_type = "github_comment"

        if not event_matched:
            return WebhookIngestResult(
                status="ignored",
                reason=f"unhandled_event_{event_type}_{action}",
            )

        # 4. Resolve repository & organization
        github_repo = payload.get("repository", {})
        github_repo_id = github_repo.get("id")
        if not github_repo_id:
            return WebhookIngestResult(
                status="ignored",
                reason="missing_repository_id",
            )

        repo = await self._repository_repo.find_by_github_repo_id(int(github_repo_id))
        if not repo:
            return WebhookIngestResult(
                status="ignored",
                reason="repository_not_tracked",
            )

        # 5. Check duplicate active task for this issue
        issue_data = payload.get("issue", {})
        issue_number = issue_data.get("number")
        if not issue_number:
            return WebhookIngestResult(
                status="ignored",
                reason="missing_issue_number",
            )

        active_task = await self._task_repo.find_active_by_repo_and_issue(
            repo.id, int(issue_number)
        )
        if active_task:
            return WebhookIngestResult(
                status="ignored",
                task_id=str(active_task.id),
                reason="active_task_already_exists",
            )

        # 6. Sourced values per spec 0004
        task_id_short = uuid.uuid4().hex[:8]
        branch_name = f"agentsonair/task-{task_id_short}-issue-{issue_number}"
        base_branch = repo.default_branch or github_repo.get("default_branch") or "main"
        issue_title = issue_data.get("title", "")
        issue_body = issue_data.get("body", "") or ""

        if trigger_type == "github_comment":
            comment_user = payload.get("sender", {}).get("login", "user")
            comment_text = payload.get("comment", {}).get("body", "")
            description = (
                f"{issue_body}\n\n---\n"
                f"**Instruction from @{comment_user}**:\n{comment_text}"
            )
        else:
            description = issue_body

        title = f"Fix issue #{issue_number}: {issue_title}"
        trigger_metadata = {
            "issue_number": issue_number,
            "issue_title": issue_title,
            "issue_url": issue_data.get("html_url", ""),
            "sender": payload.get("sender", {}).get("login", ""),
            "delivery_id": delivery_id or "",
            "action": action,
            "event": event_type,
            "branch_name": branch_name,
        }

        # 7. Create queued task
        task = await self._task_repo.create_task(
            org_id=repo.org_id,
            repo_id=repo.id,
            title=title,
            description=description,
            trigger_type=trigger_type,
            trigger_metadata=trigger_metadata,
            base_branch=base_branch,
            branch_name=branch_name,
        )

        return WebhookIngestResult(
            status="queued",
            task_id=str(task.id),
        )
