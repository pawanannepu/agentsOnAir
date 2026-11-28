"""Use case orchestrating end-to-end pull request code review execution."""

import time
import uuid
from typing import Any

from app.application.ports.audit_log_repository import AuditLogRepository
from app.application.ports.github_gateway import GitHubGateway
from app.application.ports.organization_repository import OrganizationRepository
from app.application.ports.pr_review_repository import PRReviewRepository
from app.application.ports.repository_repository import RepositoryRepository
from app.application.ports.review_examples_repository import ReviewExamplesRepository
from app.application.ports.review_feedback_repository import ReviewFeedbackRepository
from app.application.ports.review_rules_repository import ReviewRulesRepository
from app.application.ports.usage_repository import UsageRepository
from app.application.services.context_budget_allocator import ContextBudgetAllocator
from app.application.services.symbol_indexer import SymbolIndexer
from app.application.services.usage_tracker import UsageTracker
from app.domain.entities.pull_request_review import PullRequestReview
from app.domain.services.policy_evaluator import PolicyEvaluator
from app.infrastructure.db.repositories.review_examples_repository import (
    SqlAlchemyReviewExamplesRepository,
)
from app.infrastructure.db.repositories.review_feedback_repository import (
    SqlAlchemyReviewFeedbackRepository,
)
from app.infrastructure.db.repositories.review_rules_repository import (
    SqlAlchemyReviewRulesRepository,
)
from app.infrastructure.github.review_publisher import GitHubReviewPublisher
from app.infrastructure.llm.reviewer_node import CodeReviewAnalyzerNode


class RunPRReviewUseCase:
    """Orchestrates full repo context code review pipeline for a pull request."""

    def __init__(
        self,
        pr_review_repo: PRReviewRepository,
        repository_repo: RepositoryRepository,
        github_gateway: GitHubGateway,
        audit_log_repo: AuditLogRepository | None = None,
        reviewer_node: CodeReviewAnalyzerNode | None = None,
        review_publisher: GitHubReviewPublisher | None = None,
        organization_repo: OrganizationRepository | None = None,
        usage_repo: UsageRepository | None = None,
        review_rules_repo: ReviewRulesRepository | None = None,
        review_examples_repo: ReviewExamplesRepository | None = None,
        review_feedback_repo: ReviewFeedbackRepository | None = None,
    ) -> None:
        self._pr_review_repo = pr_review_repo
        self._repository_repo = repository_repo
        self._github_gateway = github_gateway
        self._audit_log_repo = audit_log_repo
        self._reviewer_node = reviewer_node or CodeReviewAnalyzerNode()
        self._review_publisher = review_publisher or GitHubReviewPublisher(
            github_gateway
        )
        self._organization_repo = organization_repo
        self._usage_repo = usage_repo
        self._usage_tracker = (
            UsageTracker(usage_repo) if usage_repo is not None else None
        )
        session = getattr(pr_review_repo, "_session", None)
        self._review_rules_repo: ReviewRulesRepository | None = review_rules_repo or (
            SqlAlchemyReviewRulesRepository(session) if session is not None else None
        )
        self._review_examples_repo: ReviewExamplesRepository | None = (
            review_examples_repo
            or (
                SqlAlchemyReviewExamplesRepository(session)
                if session is not None
                else None
            )
        )
        self._review_feedback_repo: ReviewFeedbackRepository | None = (
            review_feedback_repo
            or (
                SqlAlchemyReviewFeedbackRepository(session)
                if session is not None
                else None
            )
        )
        self._policy_evaluator = PolicyEvaluator()

    async def execute(
        self,
        org_id: uuid.UUID,
        review_id: uuid.UUID,
        repo_dir: str = ".",
        simulated_findings: list[dict] | None = None,
    ) -> PullRequestReview:
        start_time = time.time()
        review = await self._pr_review_repo.get_by_id(org_id, review_id)
        repo = await self._repository_repo.get_by_id(org_id, review.repo_id)

        org_settings: dict[str, Any] | None = None
        if self._organization_repo is not None:
            try:
                org = await self._organization_repo.get_by_id(org_id)
                org_settings = org.settings
            except Exception:
                org_settings = None
        policy = self._policy_evaluator.merge_policy(org_settings, repo.config)

        try:
            if self._usage_tracker is not None:
                preflight = await self._usage_tracker.check_preflight(org_id, policy)
                if preflight == "budget_exceeded":
                    duration_ms = int((time.time() - start_time) * 1000)
                    failed_review = await self._pr_review_repo.update_status(
                        review_id=review_id,
                        status="failed",
                        error_message="budget_exceeded",
                        execution_duration_ms=duration_ms,
                    )
                    if self._audit_log_repo:
                        await self._audit_log_repo.record_event(
                            org_id=org_id,
                            actor_type="system",
                            actor_id="pr_reviewer_engine",
                            action="pr_review_budget_exceeded",
                            target_type="pull_request_review",
                            target_id=review_id,
                            payload_after={"error": "budget_exceeded"},
                        )
                    return failed_review

            # 1. Sub-state: analyzing (fetch diff & index repository)
            await self._pr_review_repo.update_status(review_id, status="analyzing")

            token = await self._github_gateway.get_installation_token(
                repo.github_installation_id
            )
            diff_text = await self._github_gateway.get_pull_request_diff(
                repo.full_name, review.pr_number, token
            )

            indexer = SymbolIndexer(repo_dir)
            symbol_graph = indexer.build_graph()

            merged_rules = (
                await self._review_rules_repo.list_repo_rules_with_overrides(
                    org_id, repo.id
                )
                if self._review_rules_repo is not None
                else []
            )
            learned_preferences = (
                (
                    await self._review_feedback_repo.list_preferences_for_repo(
                        org_id, repo.id, page=1, page_size=200
                    )
                )[0]
                if self._review_feedback_repo is not None
                else []
            )
            example_prs = (
                await self._review_examples_repo.list_by_repo(org_id, repo.id)
                if self._review_examples_repo is not None
                else []
            )

            assembled = ContextBudgetAllocator.assemble_context(
                diff_text=diff_text,
                symbol_graph=symbol_graph,
                repo_dir=repo_dir,
                ignored_patterns=repo.review_settings.get("ignored_paths"),
                custom_rules=merged_rules,
                learned_preferences=learned_preferences,
                example_prs=example_prs,
            )

            # 2. Sub-state: reviewing (invoke reviewer node)
            await self._pr_review_repo.update_status(
                review_id,
                status="reviewing",
                context_token_count=assembled.total_token_count,
            )

            active_rule_ids = {uuid.UUID(rid) for rid in assembled.included_rule_ids}
            analysis = await self._reviewer_node.analyze(
                tier1_diff_context=assembled.tier1_content,
                tier2_symbol_context=assembled.tier2_content,
                omitted_files=assembled.omitted_files,
                allow_approval=repo.review_settings.get("allow_approval", False),
                simulated_findings=simulated_findings,
                active_rule_ids=active_rule_ids if merged_rules else set(),
                dampened_patterns=set(assembled.dampened_patterns),
                suppressed_patterns=set(assembled.suppressed_patterns),
                min_severity=str(repo.review_settings.get("min_severity", "info")),
                max_comments=int(repo.review_settings.get("max_comments", 25)),
            )

            if self._usage_tracker is not None:
                await self._usage_tracker.record_call_and_check(
                    org_id=org_id,
                    provider=analysis.provider,
                    model=analysis.model,
                    operation_type="pr_review",
                    prompt_tokens=analysis.prompt_tokens,
                    completion_tokens=analysis.completion_tokens,
                    policy=policy,
                    task_id=review.task_id,
                    pr_review_id=review_id,
                )

            # Store findings and attach persisted IDs for comment backfill
            publish_findings: list[dict] = []
            if analysis.findings:
                persisted_findings = await self._pr_review_repo.add_findings(
                    review_id=review_id,
                    findings=analysis.findings,
                )
                for raw_f, persisted_f in zip(
                    analysis.findings, persisted_findings, strict=False
                ):
                    enriched = dict(raw_f)
                    enriched["id"] = persisted_f.id
                    publish_findings.append(enriched)

            # 3. Sub-state: posting (publish review to GitHub)
            await self._pr_review_repo.update_status(
                review_id,
                status="posting",
                verdict=analysis.verdict,
                summary=analysis.summary,
            )

            write_token = await self._github_gateway.get_installation_token(
                repo.github_installation_id, write_access=True
            )
            pub_result = await self._review_publisher.publish(
                repo_full_name=repo.full_name,
                pr_number=review.pr_number,
                head_commit_sha=review.head_commit_sha,
                verdict=analysis.verdict,
                summary=analysis.summary,
                findings=publish_findings,
                diff_text=diff_text,
                token=write_token,
                pr_review_repo=self._pr_review_repo,
            )

            duration_ms = int((time.time() - start_time) * 1000)

            # 4. Completed
            completed_review = await self._pr_review_repo.update_status(
                review_id=review_id,
                status="completed",
                verdict=analysis.verdict,
                summary=pub_result.summary_markdown,
                github_review_id=pub_result.github_review_id,
                execution_duration_ms=duration_ms,
            )

            if self._audit_log_repo:
                await self._audit_log_repo.record_event(
                    org_id=org_id,
                    actor_type="system",
                    actor_id="pr_reviewer_engine",
                    action="pr_review_completed",
                    target_type="pull_request_review",
                    target_id=review_id,
                    payload_after={
                        "verdict": analysis.verdict,
                        "findings_count": len(analysis.findings),
                        "github_review_id": pub_result.github_review_id,
                        "fallback_applied": pub_result.fallback_applied,
                    },
                )

            return completed_review

        except Exception as exc:
            duration_ms = int((time.time() - start_time) * 1000)
            failed_review = await self._pr_review_repo.update_status(
                review_id=review_id,
                status="failed",
                error_message=str(exc),
                execution_duration_ms=duration_ms,
            )
            if self._audit_log_repo:
                await self._audit_log_repo.record_event(
                    org_id=org_id,
                    actor_type="system",
                    actor_id="pr_reviewer_engine",
                    action="pr_review_failed",
                    target_type="pull_request_review",
                    target_id=review_id,
                    payload_after={"error": str(exc)},
                )
            return failed_review
