"""SQLAlchemy sandbox_run repository implementation."""

import uuid
from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.application.ports.sandbox_run_repository import SandboxRunRepository
from app.domain.entities.sandbox_run import SandboxRun
from app.domain.exceptions import NotFoundError
from app.infrastructure.db.models.sandbox_run import SandboxRunModel
from app.infrastructure.db.models.task_run import TaskRunModel


def _to_entity(model: SandboxRunModel) -> SandboxRun:
    return SandboxRun(
        id=model.id,
        org_id=model.org_id,
        task_run_id=model.task_run_id,
        provider=model.provider,
        sandbox_id=model.sandbox_id,
        status=model.status,
        exit_code=model.exit_code,
        logs_storage_key=model.logs_storage_key,
        memory_limit_mb=model.memory_limit_mb,
        timeout_seconds=model.timeout_seconds,
        allocated_at=model.allocated_at,
        terminated_at=model.terminated_at,
        created_at=model.created_at,
        updated_at=model.updated_at,
    )


class SqlAlchemySandboxRunRepository(SandboxRunRepository):
    """Async SQLAlchemy adapter for SandboxRun persistence."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def record_allocation(
        self,
        org_id: uuid.UUID,
        task_run_id: uuid.UUID,
        provider: str,
        sandbox_id: str,
        memory_limit_mb: int = 2048,
        timeout_seconds: int = 600,
    ) -> SandboxRun:
        # Verify task_run belongs to this org
        tr_stmt = select(TaskRunModel.id).where(
            TaskRunModel.id == task_run_id,
            TaskRunModel.org_id == org_id,
        )
        tr = (await self._session.execute(tr_stmt)).scalar_one_or_none()
        if not tr:
            raise NotFoundError(
                f"TaskRun {task_run_id} not found in tenant organization"
            )

        model = SandboxRunModel(
            org_id=org_id,
            task_run_id=task_run_id,
            provider=provider,
            sandbox_id=sandbox_id,
            memory_limit_mb=memory_limit_mb,
            timeout_seconds=timeout_seconds,
            status="active",
            allocated_at=datetime.now(UTC),
        )
        self._session.add(model)
        await self._session.flush()
        return _to_entity(model)

    async def get_by_task_run_id(
        self, org_id: uuid.UUID, task_run_id: uuid.UUID
    ) -> SandboxRun:
        stmt = select(SandboxRunModel).where(
            SandboxRunModel.org_id == org_id,
            SandboxRunModel.task_run_id == task_run_id,
        )
        model = (await self._session.execute(stmt)).scalar_one_or_none()
        if not model:
            raise NotFoundError(
                f"SandboxRun for TaskRun {task_run_id} not found in tenant organization"
            )
        return _to_entity(model)

    async def update_timeout(
        self,
        org_id: uuid.UUID,
        task_run_id: uuid.UUID,
        timeout_seconds: int,
    ) -> SandboxRun:
        stmt = select(SandboxRunModel).where(
            SandboxRunModel.org_id == org_id,
            SandboxRunModel.task_run_id == task_run_id,
        )
        model = (await self._session.execute(stmt)).scalar_one_or_none()
        if not model:
            raise NotFoundError(
                f"SandboxRun for TaskRun {task_run_id} not found in tenant organization"
            )
        model.timeout_seconds = timeout_seconds
        model.updated_at = datetime.now(UTC)
        await self._session.flush()
        return _to_entity(model)

    async def record_termination(
        self,
        org_id: uuid.UUID,
        sandbox_run_id: uuid.UUID,
        exit_code: int | None = None,
        logs_storage_key: str | None = None,
    ) -> SandboxRun:
        stmt = select(SandboxRunModel).where(
            SandboxRunModel.org_id == org_id,
            SandboxRunModel.id == sandbox_run_id,
        )
        model = (await self._session.execute(stmt)).scalar_one_or_none()
        if not model:
            raise NotFoundError(
                f"SandboxRun {sandbox_run_id} not found in tenant organization"
            )

        model.status = "terminated"
        model.exit_code = exit_code
        model.logs_storage_key = logs_storage_key
        model.terminated_at = datetime.now(UTC)
        model.updated_at = datetime.now(UTC)

        await self._session.flush()
        return _to_entity(model)
