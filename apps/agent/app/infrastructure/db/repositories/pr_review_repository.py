"""SqlAlchemy implementation of PRReviewRepository."""

import uuid
from datetime import UTC, datetime

from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.application.ports.pr_review_repository import PRReviewRepository
from app.domain.entities.pr_review_finding import PRReviewFinding
from app.domain.entities.pull_request_review import PullRequestReview
from app.domain.exceptions import ConflictError, NotFoundError
from app.infrastructure.db.models.pr_review_finding import PRReviewFindingModel
from app.infrastructure.db.models.pull_request_review import PullRequestReviewModel


def _review_to_entity(model: PullRequestReviewModel) -> PullRequestReview:
    return PullRequestReview(
        id=model.id,
        org_id=model.org_id,
        repo_id=model.repo_id,
        task_id=model.task_id,
        pr_number=model.pr_number,
        pr_title=model.pr_title,
        pr_author=model.pr_author,
        head_commit_sha=model.head_commit_sha,
        base_commit_sha=model.base_commit_sha,
        status=model.status,
        verdict=model.verdict,
        summary=model.summary,
        github_review_id=model.github_review_id,
        context_token_count=model.context_token_count,
        model_name=model.model_name,
        execution_duration_ms=model.execution_duration_ms,
        error_message=model.error_message,
        created_at=model.created_at,
        updated_at=model.updated_at,
    )


def _finding_to_entity(model: PRReviewFindingModel) -> PRReviewFinding:
    return PRReviewFinding(
        id=model.id,
        review_id=model.review_id,
        file_path=model.file_path,
        start_line=model.start_line,
        line_number=model.line_number,
        side=model.side,
        severity=model.severity,
        category=model.category,
        title=model.title,
        message=model.message,
        suggested_patch=model.suggested_patch,
        github_comment_id=model.github_comment_id,
        status=model.status,
        created_at=model.created_at,
    )


class SqlAlchemyPRReviewRepository(PRReviewRepository):
    """Async SQLAlchemy adapter for PR review and findings persistence."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

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
        active = await self.find_active_by_repo_and_pr(repo_id, pr_number)
        if active:
            raise ConflictError(
                f"An active review already exists for PR #{pr_number} on repo {repo_id}"
            )

        model = PullRequestReviewModel(
            org_id=org_id,
            repo_id=repo_id,
            task_id=task_id,
            pr_number=pr_number,
            pr_title=pr_title,
            pr_author=pr_author,
            head_commit_sha=head_commit_sha,
            base_commit_sha=base_commit_sha,
            model_name=model_name,
            status="pending",
        )
        self._session.add(model)
        await self._session.flush()
        return _review_to_entity(model)

    async def get_by_id(
        self, org_id: uuid.UUID, review_id: uuid.UUID
    ) -> PullRequestReview:
        stmt = select(PullRequestReviewModel).where(
            PullRequestReviewModel.id == review_id,
            PullRequestReviewModel.org_id == org_id,
        )
        model = (await self._session.execute(stmt)).scalar_one_or_none()
        if not model:
            raise NotFoundError(f"PR Review {review_id} not found in organization")
        return _review_to_entity(model)

    async def find_active_by_repo_and_pr(
        self, repo_id: uuid.UUID, pr_number: int
    ) -> PullRequestReview | None:
        stmt = select(PullRequestReviewModel).where(
            PullRequestReviewModel.repo_id == repo_id,
            PullRequestReviewModel.pr_number == pr_number,
            PullRequestReviewModel.status.in_(
                ["pending", "analyzing", "reviewing", "posting"]
            ),
        )
        model = (await self._session.execute(stmt)).scalar_one_or_none()
        return _review_to_entity(model) if model else None

    async def list_by_repo_and_pr(
        self,
        org_id: uuid.UUID,
        repo_id: uuid.UUID,
        pr_number: int,
        page: int = 1,
        page_size: int = 20,
    ) -> tuple[list[PullRequestReview], int]:
        count_stmt = select(func.count(PullRequestReviewModel.id)).where(
            PullRequestReviewModel.org_id == org_id,
            PullRequestReviewModel.repo_id == repo_id,
            PullRequestReviewModel.pr_number == pr_number,
        )
        total = (await self._session.execute(count_stmt)).scalar_one()

        offset = max(0, (page - 1) * page_size)
        stmt = (
            select(PullRequestReviewModel)
            .where(
                PullRequestReviewModel.org_id == org_id,
                PullRequestReviewModel.repo_id == repo_id,
                PullRequestReviewModel.pr_number == pr_number,
            )
            .order_by(PullRequestReviewModel.created_at.desc())
            .offset(offset)
            .limit(page_size)
        )
        models = (await self._session.execute(stmt)).scalars().all()
        return [_review_to_entity(m) for m in models], total

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
        stmt = select(PullRequestReviewModel).where(
            PullRequestReviewModel.id == review_id
        )
        model = (await self._session.execute(stmt)).scalar_one_or_none()
        if not model:
            raise NotFoundError(f"PR Review {review_id} not found")

        model.status = status
        model.updated_at = datetime.now(UTC)
        if verdict is not None:
            model.verdict = verdict
        if summary is not None:
            model.summary = summary
        if github_review_id is not None:
            model.github_review_id = github_review_id
        if context_token_count is not None:
            model.context_token_count = context_token_count
        if execution_duration_ms is not None:
            model.execution_duration_ms = execution_duration_ms
        if error_message is not None:
            model.error_message = error_message

        await self._session.flush()
        return _review_to_entity(model)

    async def add_findings(
        self,
        review_id: uuid.UUID,
        findings: list[dict],
    ) -> list[PRReviewFinding]:
        models = []
        for f in findings:
            model = PRReviewFindingModel(
                review_id=review_id,
                file_path=f["file_path"],
                start_line=f.get("start_line"),
                line_number=f["line_number"],
                side=f.get("side", "RIGHT"),
                severity=f["severity"],
                category=f["category"],
                title=f["title"],
                message=f["message"],
                suggested_patch=f.get("suggested_patch"),
                github_comment_id=f.get("github_comment_id"),
                status=f.get("status", "open"),
            )
            models.append(model)
            self._session.add(model)

        await self._session.flush()
        return [_finding_to_entity(m) for m in models]

    async def list_findings(
        self,
        review_id: uuid.UUID,
        page: int = 1,
        page_size: int = 50,
    ) -> tuple[list[PRReviewFinding], int]:
        count_stmt = select(func.count(PRReviewFindingModel.id)).where(
            PRReviewFindingModel.review_id == review_id
        )
        total = (await self._session.execute(count_stmt)).scalar_one()

        offset = max(0, (page - 1) * page_size)
        stmt = (
            select(PRReviewFindingModel)
            .where(PRReviewFindingModel.review_id == review_id)
            .order_by(
                PRReviewFindingModel.file_path.asc(),
                PRReviewFindingModel.line_number.asc(),
            )
            .offset(offset)
            .limit(page_size)
        )
        models = (await self._session.execute(stmt)).scalars().all()
        return [_finding_to_entity(m) for m in models], total

    async def update_finding_github_id(
        self,
        finding_id: uuid.UUID,
        github_comment_id: int,
    ) -> None:
        stmt = (
            update(PRReviewFindingModel)
            .where(PRReviewFindingModel.id == finding_id)
            .values(github_comment_id=github_comment_id)
        )
        await self._session.execute(stmt)
        await self._session.flush()
