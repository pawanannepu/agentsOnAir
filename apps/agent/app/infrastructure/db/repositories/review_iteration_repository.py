"""SQLAlchemy review iteration repository implementation."""

import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.application.ports.review_iteration_repository import ReviewIterationRepository
from app.domain.entities.review_iteration import ReviewIteration
from app.infrastructure.db.models.review_iteration import ReviewIterationModel


def _to_entity(model: ReviewIterationModel) -> ReviewIteration:
    return ReviewIteration(
        id=model.id,
        org_id=model.org_id,
        task_run_id=model.task_run_id,
        cycle_number=model.cycle_number,
        verdict=model.verdict,
        summary=model.summary,
        findings=model.findings or [],
        blocking_count=model.blocking_count,
        non_blocking_count=model.non_blocking_count,
        diff_snapshot=model.diff_snapshot,
        created_at=model.created_at,
    )


class SqlAlchemyReviewIterationRepository(ReviewIterationRepository):
    """Async SQLAlchemy adapter for ReviewIteration persistence."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def create(
        self,
        org_id: uuid.UUID,
        task_run_id: uuid.UUID,
        cycle_number: int,
        verdict: str,
        summary: str,
        findings: list[dict],
        blocking_count: int,
        non_blocking_count: int,
        diff_snapshot: str | None = None,
    ) -> ReviewIteration:
        model = ReviewIterationModel(
            org_id=org_id,
            task_run_id=task_run_id,
            cycle_number=cycle_number,
            verdict=verdict,
            summary=summary,
            findings=findings,
            blocking_count=blocking_count,
            non_blocking_count=non_blocking_count,
            diff_snapshot=diff_snapshot,
        )
        self._session.add(model)
        await self._session.flush()
        return _to_entity(model)

    async def get_by_id(
        self, org_id: uuid.UUID, iteration_id: uuid.UUID
    ) -> ReviewIteration | None:
        stmt = select(ReviewIterationModel).where(
            ReviewIterationModel.org_id == org_id,
            ReviewIterationModel.id == iteration_id,
        )
        model = (await self._session.execute(stmt)).scalar_one_or_none()
        return _to_entity(model) if model else None

    async def list_by_task_run_id(
        self, org_id: uuid.UUID, task_run_id: uuid.UUID
    ) -> list[ReviewIteration]:
        stmt = (
            select(ReviewIterationModel)
            .where(
                ReviewIterationModel.org_id == org_id,
                ReviewIterationModel.task_run_id == task_run_id,
            )
            .order_by(ReviewIterationModel.cycle_number.asc())
        )
        models = (await self._session.execute(stmt)).scalars().all()
        return [_to_entity(m) for m in models]
