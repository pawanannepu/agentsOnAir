"""SQLAlchemy task_run repository implementation."""

import uuid
from datetime import UTC, datetime

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.application.ports.task_run_repository import TaskRunRepository
from app.domain.entities.task_run import TaskRun
from app.domain.exceptions import ConcurrencyError, NotFoundError
from app.infrastructure.db.models.task import TaskModel
from app.infrastructure.db.models.task_run import TaskRunModel


def _to_entity(model: TaskRunModel) -> TaskRun:
    return TaskRun(
        id=model.id,
        org_id=model.org_id,
        task_id=model.task_id,
        run_number=model.run_number,
        status=model.status,
        version=model.version,
        failure_reason=model.failure_reason,
        checkpoint_state=model.checkpoint_state or {},
        prompt_tokens=model.prompt_tokens,
        completion_tokens=model.completion_tokens,
        tokens_used=model.tokens_used,
        estimated_cost_cents=model.estimated_cost_cents,
        paused_seconds=model.paused_seconds,
        started_at=model.started_at,
        completed_at=model.completed_at,
        created_at=model.created_at,
        updated_at=model.updated_at,
    )


class SqlAlchemyTaskRunRepository(TaskRunRepository):
    """Async SQLAlchemy adapter for TaskRun with row locking and versioning."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def create_run(self, org_id: uuid.UUID, task_id: uuid.UUID) -> TaskRun:
        # Acquire row lock on parent task to ensure sequential run numbers
        task_stmt = (
            select(TaskModel.id)
            .where(
                TaskModel.id == task_id,
                TaskModel.org_id == org_id,
                TaskModel.deleted_at.is_(None),
            )
            .with_for_update()
        )
        task_id_locked = (await self._session.execute(task_stmt)).scalar_one_or_none()
        if not task_id_locked:
            raise NotFoundError(f"Task {task_id} not found in tenant organization")

        # Determine next sequential run number
        max_run_stmt = select(
            func.coalesce(func.max(TaskRunModel.run_number), 0)
        ).where(TaskRunModel.task_id == task_id)
        current_max = (await self._session.execute(max_run_stmt)).scalar_one()
        next_run_number = current_max + 1

        model = TaskRunModel(
            org_id=org_id,
            task_id=task_id,
            run_number=next_run_number,
            status="pending",
            version=1,
            started_at=datetime.now(UTC),
        )
        self._session.add(model)
        await self._session.flush()
        return _to_entity(model)

    async def get_by_id(self, org_id: uuid.UUID, task_run_id: uuid.UUID) -> TaskRun:
        stmt = select(TaskRunModel).where(
            TaskRunModel.org_id == org_id,
            TaskRunModel.id == task_run_id,
        )
        model = (await self._session.execute(stmt)).scalar_one_or_none()
        if not model:
            raise NotFoundError(
                f"TaskRun {task_run_id} not found in tenant organization"
            )
        return _to_entity(model)

    async def get_latest_by_task(
        self, org_id: uuid.UUID, task_id: uuid.UUID
    ) -> TaskRun:
        stmt = (
            select(TaskRunModel)
            .where(
                TaskRunModel.org_id == org_id,
                TaskRunModel.task_id == task_id,
            )
            .order_by(TaskRunModel.run_number.desc())
            .limit(1)
        )
        model = (await self._session.execute(stmt)).scalar_one_or_none()
        if not model:
            raise NotFoundError(
                f"TaskRun for Task {task_id} not found in tenant organization"
            )
        return _to_entity(model)

    async def set_status(
        self, org_id: uuid.UUID, task_run_id: uuid.UUID, status: str
    ) -> TaskRun:
        stmt = select(TaskRunModel).where(
            TaskRunModel.org_id == org_id,
            TaskRunModel.id == task_run_id,
        )
        model = (await self._session.execute(stmt)).scalar_one_or_none()
        if not model:
            raise NotFoundError(
                f"TaskRun {task_run_id} not found in tenant organization"
            )
        model.status = status
        model.updated_at = datetime.now(UTC)
        await self._session.flush()
        return _to_entity(model)

    async def increment_paused_seconds(
        self, org_id: uuid.UUID, task_run_id: uuid.UUID, delta_seconds: int
    ) -> TaskRun:
        stmt = select(TaskRunModel).where(
            TaskRunModel.org_id == org_id,
            TaskRunModel.id == task_run_id,
        )
        model = (await self._session.execute(stmt)).scalar_one_or_none()
        if not model:
            raise NotFoundError(
                f"TaskRun {task_run_id} not found in tenant organization"
            )
        if delta_seconds > 0:
            model.paused_seconds += delta_seconds
            model.updated_at = datetime.now(UTC)
            await self._session.flush()
        return _to_entity(model)

    async def update_checkpoint(
        self,
        org_id: uuid.UUID,
        task_run_id: uuid.UUID,
        checkpoint_state: dict,
        expected_version: int,
    ) -> TaskRun:
        stmt = select(TaskRunModel).where(
            TaskRunModel.org_id == org_id,
            TaskRunModel.id == task_run_id,
        )
        model = (await self._session.execute(stmt)).scalar_one_or_none()
        if not model:
            raise NotFoundError(
                f"TaskRun {task_run_id} not found in tenant organization"
            )

        # Optimistic concurrency check
        if model.version != expected_version:
            raise ConcurrencyError(
                f"TaskRun {task_run_id} conflict: expected {expected_version}, "
                f"found {model.version}"
            )

        model.checkpoint_state = checkpoint_state
        model.version += 1
        model.updated_at = datetime.now(UTC)

        await self._session.flush()
        return _to_entity(model)

    async def complete_run(
        self,
        org_id: uuid.UUID,
        task_run_id: uuid.UUID,
        status: str,
        prompt_tokens: int = 0,
        completion_tokens: int = 0,
        estimated_cost_cents: int = 0,
        failure_reason: str | None = None,
    ) -> TaskRun:
        stmt = select(TaskRunModel).where(
            TaskRunModel.org_id == org_id,
            TaskRunModel.id == task_run_id,
        )
        model = (await self._session.execute(stmt)).scalar_one_or_none()
        if not model:
            raise NotFoundError(
                f"TaskRun {task_run_id} not found in tenant organization"
            )

        model.status = status
        model.prompt_tokens = prompt_tokens
        model.completion_tokens = completion_tokens
        model.tokens_used = prompt_tokens + completion_tokens
        model.estimated_cost_cents = estimated_cost_cents
        model.failure_reason = failure_reason
        model.completed_at = datetime.now(UTC)
        model.updated_at = datetime.now(UTC)

        await self._session.flush()
        return _to_entity(model)
