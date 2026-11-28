"""GitHub App webhook ingestion use case."""

import json
import re
import uuid
from dataclasses import dataclass

from app.application.ports.github_gateway import GitHubGateway
from app.application.ports.pr_review_repository import PRReviewRepository
from app.application.ports.repository_repository import RepositoryRepository
from app.application.ports.review_feedback_repository import ReviewFeedbackRepository
from app.application.ports.task_repository import TaskRepository
from app.application.use_cases.review_feedback import ReviewFeedbackUseCase
from app.domain.exceptions import WebhookSignatureError
from app.infrastructure.db.repositories.review_feedback_repository import (
    SqlAlchemyReviewFeedbackRepository,
)
from app.infrastructure.github.webhook import verify_github_signature

ALLOWED_FEEDBACK_ASSOCIATIONS = frozenset({"OWNER", "MEMBER", "COLLABORATOR"})
_DISMISS_PREFIX_RE = re.compile(
    r"^(?:dismiss|false\s+positive|ignore)\b(.*)$",
    re.IGNORECASE | re.DOTALL,
)
_ACCEPT_PREFIX_RE = re.compile(
    r"^(?:good\s+catch|accept)\b(.*)$",
    re.IGNORECASE | re.DOTALL,
)


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
        review_feedback_repo: ReviewFeedbackRepository | None = None,
    ) -> None:
        self._repository_repo = repository_repo
        self._task_repo = task_repo
        self._pr_review_repo = pr_review_repo
        self._github_gateway = github_gateway
        session = getattr(repository_repo, "_session", None)
        self._review_feedback_repo: ReviewFeedbackRepository | None = (
            review_feedback_repo
            or (
                SqlAlchemyReviewFeedbackRepository(session)
                if session is not None
                else None
            )
        )

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

        # 2b. Handle review thread resolve/unresolve & reply comment feedback (AC-3)
        if event_type in ("pull_request_review_thread", "pull_request_review_comment"):
            return await self._handle_feedback_webhook(
                event_type=event_type,
                action=action,
                delivery_id=delivery_id,
                payload=payload,
            )

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

    @staticmethod
    def _is_bot_actor(actor: dict) -> bool:
        login = str(actor.get("login") or "")
        actor_type = str(actor.get("type") or "")
        return (
            actor_type == "Bot"
            or login == "agentsonair[bot]"
            or login.endswith("[bot]")
        )

    @staticmethod
    def _clean_trailing_reason(raw_tail: str) -> str | None:
        cleaned = raw_tail.lstrip(" \t\r\n:,-").strip()
        return cleaned if cleaned else None

    async def _handle_feedback_webhook(
        self,
        *,
        event_type: str,
        action: str,
        delivery_id: str | None,
        payload: dict,
    ) -> WebhookIngestResult:
        if not delivery_id or not delivery_id.strip():
            return WebhookIngestResult(
                status="ignored",
                reason="missing_delivery_id",
            )
        if self._review_feedback_repo is None:
            return WebhookIngestResult(
                status="ignored",
                reason="feedback_repository_unavailable",
            )

        sender = payload.get("sender") or {}
        if self._is_bot_actor(sender):
            return WebhookIngestResult(
                status="ignored",
                reason="bot_sender_excluded",
            )
        sender_login = str(sender.get("login") or "github_user")

        github_repo_id = (payload.get("repository") or {}).get("id")
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

        feedback_uc = ReviewFeedbackUseCase(self._review_feedback_repo)

        if event_type == "pull_request_review_thread":
            if action not in ("resolved", "unresolved"):
                return WebhookIngestResult(
                    status="ignored",
                    reason=f"unhandled_thread_action_{action}",
                )

            thread = payload.get("thread") or {}
            comments = thread.get("comments") or []
            assoc = (
                payload.get("author_association")
                or sender.get("author_association")
                or next(
                    (
                        c.get("author_association")
                        for c in comments
                        if isinstance(c, dict)
                        and (c.get("user") or {}).get("login") == sender_login
                        and c.get("author_association")
                    ),
                    None,
                )
                or (
                    comments[0].get("author_association")
                    if comments and isinstance(comments[0], dict)
                    else None
                )
            )
            if str(assoc or "").upper() not in ALLOWED_FEEDBACK_ASSOCIATIONS:
                return WebhookIngestResult(
                    status="ignored",
                    reason="unauthorized_author_association",
                )

            matched_pair = None
            for comment in comments:
                if not isinstance(comment, dict) or comment.get("id") is None:
                    continue
                matched_pair = (
                    await self._review_feedback_repo.find_finding_by_github_comment_id(
                        repo.id, int(comment["id"])
                    )
                )
                if matched_pair is not None:
                    break

            if matched_pair is None:
                return WebhookIngestResult(
                    status="ignored",
                    reason="finding_not_found",
                )

            finding, review = matched_pair
            if action == "unresolved":
                await feedback_uc.reset_finding_unresolved(repo.org_id, finding.id)
                return WebhookIngestResult(
                    status="processed",
                    review_id=str(review.id),
                    reason="finding_feedback_unresolved",
                )

            result = await feedback_uc.submit_feedback(
                org_id=repo.org_id,
                finding_id=finding.id,
                feedback_type="accepted",
                source="github_thread_resolved",
                actor_id=sender_login,
                github_event_id=delivery_id.strip(),
            )
            return WebhookIngestResult(
                status="ignored"
                if result.deduplicated and not result.applied
                else "processed",
                review_id=str(review.id),
                reason="duplicate_delivery"
                if result.deduplicated
                else "thread_resolved_accepted",
            )

        # pull_request_review_comment
        if action != "created":
            return WebhookIngestResult(
                status="ignored",
                reason=f"unhandled_review_comment_action_{action}",
            )

        comment = payload.get("comment") or {}
        comment_user = comment.get("user") or {}
        if comment_user and self._is_bot_actor(comment_user):
            return WebhookIngestResult(
                status="ignored",
                reason="bot_sender_excluded",
            )

        assoc = (
            comment.get("author_association")
            or sender.get("author_association")
            or payload.get("author_association")
        )
        if str(assoc or "").upper() not in ALLOWED_FEEDBACK_ASSOCIATIONS:
            return WebhookIngestResult(
                status="ignored",
                reason="unauthorized_author_association",
            )

        in_reply_to_id = comment.get("in_reply_to_id")
        if not in_reply_to_id:
            return WebhookIngestResult(
                status="ignored",
                reason="not_a_reply_comment",
            )

        body = str(comment.get("body") or "").strip()
        feedback_type: str | None = None
        reason_text: str | None = None
        dismiss_match = _DISMISS_PREFIX_RE.match(body)
        if dismiss_match:
            feedback_type = "dismissed"
            reason_text = self._clean_trailing_reason(dismiss_match.group(1))
        else:
            accept_match = _ACCEPT_PREFIX_RE.match(body)
            if accept_match:
                feedback_type = "accepted"
                reason_text = self._clean_trailing_reason(accept_match.group(1))

        if feedback_type is None:
            return WebhookIngestResult(
                status="ignored",
                reason="unrecognized_feedback_prefix",
            )

        matched_pair = (
            await self._review_feedback_repo.find_finding_by_github_comment_id(
                repo.id, int(in_reply_to_id)
            )
        )
        if matched_pair is None:
            return WebhookIngestResult(
                status="ignored",
                reason="finding_not_found",
            )

        finding, review = matched_pair
        result = await feedback_uc.submit_feedback(
            org_id=repo.org_id,
            finding_id=finding.id,
            feedback_type=feedback_type,
            source="github_comment_reply",
            actor_id=sender_login,
            reason=reason_text,
            remember_preference=False,
            github_event_id=delivery_id.strip(),
        )
        return WebhookIngestResult(
            status="ignored"
            if result.deduplicated and not result.applied
            else "processed",
            review_id=str(review.id),
            reason="duplicate_delivery"
            if result.deduplicated
            else f"comment_reply_{feedback_type}",
        )
