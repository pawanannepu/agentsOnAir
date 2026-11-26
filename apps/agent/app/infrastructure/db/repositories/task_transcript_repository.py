"""SQLAlchemy task transcript repository implementation."""

import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.application.ports.task_transcript_repository import TaskTranscriptRepository
from app.domain.entities.task_transcript import TaskTranscript
from app.infrastructure.db.models.task_transcript import TaskTranscriptModel


def _to_entity(model: TaskTranscriptModel) -> TaskTranscript:
    return TaskTranscript(
        id=model.id,
        org_id=model.org_id,
        task_id=model.task_id,
        task_run_id=model.task_run_id,
        terminal_log=model.terminal_log,
        events_json=model.events_json or [],
        total_lines=model.total_lines,
        created_at=model.created_at,
    )


class SqlAlchemyTaskTranscriptRepository(TaskTranscriptRepository):
    """Async SQLAlchemy adapter for TaskTranscript persistence."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def create_or_update(
        self,
        org_id: uuid.UUID,
        task_id: uuid.UUID,
        task_run_id: uuid.UUID,
        terminal_log: bytes,
        events_json: list[dict],
        total_lines: int,
    ) -> TaskTranscript:
        stmt = select(TaskTranscriptModel).where(
            TaskTranscriptModel.org_id == org_id,
            TaskTranscriptModel.task_run_id == task_run_id,
        )
        model = (await self._session.execute(stmt)).scalar_one_or_none()
        if model:
            model.terminal_log = terminal_log
            model.events_json = events_json
            model.total_lines = total_lines
        else:
            model = TaskTranscriptModel(
                org_id=org_id,
                task_id=task_id,
                task_run_id=task_run_id,
                terminal_log=terminal_log,
                events_json=events_json,
                total_lines=total_lines,
            )
            self._session.add(model)

        await self._session.flush()
        return _to_entity(model)

    async def get_by_task(
        self,
        org_id: uuid.UUID,
        task_id: uuid.UUID,
        task_run_id: uuid.UUID | None = None,
    ) -> TaskTranscript | None:
        stmt = select(TaskTranscriptModel).where(
            TaskTranscriptModel.org_id == org_id,
            TaskTranscriptModel.task_id == task_id,
        )
        if task_run_id is not None:
            stmt = stmt.where(TaskTranscriptModel.task_run_id == task_run_id)
        else:
            stmt = stmt.order_by(TaskTranscriptModel.created_at.desc())

        model = (await self._session.execute(stmt)).scalars().first()
        return _to_entity(model) if model else None
