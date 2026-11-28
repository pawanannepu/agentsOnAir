"""SQLAlchemy implementation of ReviewExamplesRepository."""

import uuid
from datetime import UTC, datetime

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.application.ports.review_examples_repository import ReviewExamplesRepository
from app.domain.entities.review_example import ReviewExample
from app.domain.exceptions import ConflictError, NotFoundError, ValidationError
from app.infrastructure.db.models.repository import RepositoryModel
from app.infrastructure.db.models.review_example import ReviewExampleModel

MAX_EXAMPLES_PER_REPO = 5


def _to_entity(model: ReviewExampleModel) -> ReviewExample:
    return ReviewExample(
        id=model.id,
        org_id=model.org_id,
        repo_id=model.repo_id,
        pr_number=model.pr_number,
        pr_url=model.pr_url,
        pr_title=model.pr_title,
        classification=model.classification,
        guidance_note=model.guidance_note,
        modified_files=list(model.modified_files or []),
        cached_diff_summary=model.cached_diff_summary,
        cached_token_count=model.cached_token_count,
        cached_at=model.cached_at,
        created_by=model.created_by,
        created_at=model.created_at,
        updated_at=model.updated_at,
    )


class SqlAlchemyReviewExamplesRepository(ReviewExamplesRepository):
    """Async SQLAlchemy adapter for curated review example PRs."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def _ensure_repo_exists(
        self, org_id: uuid.UUID, repo_id: uuid.UUID, *, lock: bool = False
    ) -> None:
        stmt = select(RepositoryModel.id).where(
            RepositoryModel.id == repo_id,
            RepositoryModel.org_id == org_id,
            RepositoryModel.deleted_at.is_(None),
        )
        if lock:
            stmt = stmt.with_for_update()
        if (await self._session.execute(stmt)).scalar_one_or_none() is None:
            raise NotFoundError(f"Repository {repo_id} not found in organization")

    async def list_by_repo(
        self, org_id: uuid.UUID, repo_id: uuid.UUID
    ) -> list[ReviewExample]:
        await self._ensure_repo_exists(org_id, repo_id)
        stmt = (
            select(ReviewExampleModel)
            .where(
                ReviewExampleModel.org_id == org_id,
                ReviewExampleModel.repo_id == repo_id,
            )
            .order_by(ReviewExampleModel.updated_at.desc())
        )
        models = (await self._session.execute(stmt)).scalars().all()
        return [_to_entity(m) for m in models]

    async def get_by_id(
        self, org_id: uuid.UUID, repo_id: uuid.UUID, example_id: uuid.UUID
    ) -> ReviewExample:
        stmt = select(ReviewExampleModel).where(
            ReviewExampleModel.id == example_id,
            ReviewExampleModel.org_id == org_id,
            ReviewExampleModel.repo_id == repo_id,
        )
        model = (await self._session.execute(stmt)).scalar_one_or_none()
        if model is None:
            raise NotFoundError(f"Review example {example_id} not found")
        return _to_entity(model)

    async def create_example(
        self,
        org_id: uuid.UUID,
        repo_id: uuid.UUID,
        pr_number: int,
        pr_url: str,
        pr_title: str,
        classification: str,
        guidance_note: str,
        modified_files: list[str],
        cached_diff_summary: str | None,
        cached_token_count: int,
        cached_at: datetime | None,
        created_by: str,
    ) -> ReviewExample:
        await self._ensure_repo_exists(org_id, repo_id, lock=True)

        dup_stmt = select(ReviewExampleModel.id).where(
            ReviewExampleModel.repo_id == repo_id,
            ReviewExampleModel.pr_number == pr_number,
        )
        if (await self._session.execute(dup_stmt)).scalar_one_or_none() is not None:
            raise ConflictError(
                f"PR #{pr_number} is already attached as an example on this repository"
            )

        count_stmt = select(func.count(ReviewExampleModel.id)).where(
            ReviewExampleModel.repo_id == repo_id,
        )
        current_count = int((await self._session.execute(count_stmt)).scalar_one())
        if current_count >= MAX_EXAMPLES_PER_REPO:
            raise ValidationError(
                f"Repository already reached the maximum of {MAX_EXAMPLES_PER_REPO} "
                "curated example pull requests"
            )

        model = ReviewExampleModel(
            org_id=org_id,
            repo_id=repo_id,
            pr_number=pr_number,
            pr_url=pr_url,
            pr_title=pr_title,
            classification=classification,
            guidance_note=guidance_note,
            modified_files=modified_files,
            cached_diff_summary=cached_diff_summary,
            cached_token_count=cached_token_count,
            cached_at=cached_at,
            created_by=created_by,
        )
        self._session.add(model)
        await self._session.flush()
        return _to_entity(model)

    async def update_cache(
        self,
        org_id: uuid.UUID,
        repo_id: uuid.UUID,
        example_id: uuid.UUID,
        pr_url: str,
        pr_title: str,
        modified_files: list[str],
        cached_diff_summary: str | None,
        cached_token_count: int,
        cached_at: datetime,
    ) -> ReviewExample:
        stmt = select(ReviewExampleModel).where(
            ReviewExampleModel.id == example_id,
            ReviewExampleModel.org_id == org_id,
            ReviewExampleModel.repo_id == repo_id,
        )
        model = (await self._session.execute(stmt)).scalar_one_or_none()
        if model is None:
            raise NotFoundError(f"Review example {example_id} not found")

        model.pr_url = pr_url
        model.pr_title = pr_title
        model.modified_files = modified_files
        model.cached_diff_summary = cached_diff_summary
        model.cached_token_count = cached_token_count
        model.cached_at = cached_at
        model.updated_at = datetime.now(UTC)
        await self._session.flush()
        return _to_entity(model)

    async def delete_example(
        self, org_id: uuid.UUID, repo_id: uuid.UUID, example_id: uuid.UUID
    ) -> ReviewExample:
        stmt = select(ReviewExampleModel).where(
            ReviewExampleModel.id == example_id,
            ReviewExampleModel.org_id == org_id,
            ReviewExampleModel.repo_id == repo_id,
        )
        model = (await self._session.execute(stmt)).scalar_one_or_none()
        if model is None:
            raise NotFoundError(f"Review example {example_id} not found")
        entity = _to_entity(model)
        await self._session.delete(model)
        await self._session.flush()
        return entity
