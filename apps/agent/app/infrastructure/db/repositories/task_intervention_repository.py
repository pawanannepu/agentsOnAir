"""SQLAlchemy task intervention repository implementation."""

import uuid
from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.application.ports.task_intervention_repository import (
    TaskInterventionRepository,
)
from app.domain.entities.task_intervention import TaskIntervention
from app.domain.exceptions import NotFoundError
from app.infrastructure.db.models.task_intervention import TaskInterventionModel


def _to_entity(model: TaskInterventionModel) -> TaskIntervention:
    return TaskIntervention(
        id=model.id,
        org_id=model.org_id,
        task_id=model.task_id,
        task_run_id=model.task_run_id,
        clerk_user_id=model.clerk_user_id,
        intervention_type=model.intervention_type,
        prompt_snapshot=model.prompt_snapshot,
        payload=model.payload or {},
        applied_at=model.applied_at,
        created_at=model.created_at,
    )


class SqlAlchemyTaskInterventionRepository(TaskInterventionRepository):
    """Async SQLAlchemy adapter for TaskIntervention persistence."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def create(
        self,
        org_id: uuid.UUID,
        task_id: uuid.UUID,
        clerk_user_id: str,
        intervention_type: str,
        payload: dict,
        task_run_id: uuid.UUID | None = None,
        prompt_snapshot: str | None = None,
    ) -> TaskIntervention:
        model = TaskInterventionModel(
            org_id=org_id,
            task_id=task_id,
            task_run_id=task_run_id,
            clerk_user_id=clerk_user_id,
            intervention_type=intervention_type,
            prompt_snapshot=prompt_snapshot,
            payload=payload,
        )
        self._session.add(model)
        await self._session.flush()
        return _to_entity(model)

    async def list_by_task(
        self, org_id: uuid.UUID, task_id: uuid.UUID
    ) -> list[TaskIntervention]:
        stmt = (
            select(TaskInterventionModel)
            .where(
                TaskInterventionModel.org_id == org_id,
                TaskInterventionModel.task_id == task_id,
            )
            .order_by(TaskInterventionModel.created_at.asc())
        )
        models = (await self._session.execute(stmt)).scalars().all()
        return [_to_entity(m) for m in models]

    async def mark_applied(
        self, org_id: uuid.UUID, intervention_id: uuid.UUID
    ) -> TaskIntervention:
        stmt = select(TaskInterventionModel).where(
            TaskInterventionModel.org_id == org_id,
            TaskInterventionModel.id == intervention_id,
        )
        model = (await self._session.execute(stmt)).scalar_one_or_none()
        if not model:
            raise NotFoundError(
                f"Intervention {intervention_id} not found in tenant organization"
            )
        model.applied_at = datetime.now(UTC)
        await self._session.flush()
        return _to_entity(model)
