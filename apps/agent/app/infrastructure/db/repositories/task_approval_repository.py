"""SQLAlchemy task approval repository implementation."""

import uuid
from datetime import UTC, datetime

from sqlalchemy import select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.application.ports.task_approval_repository import TaskApprovalRepository
from app.domain.entities.task_approval import TaskApproval
from app.domain.exceptions import ConflictError, NotFoundError
from app.infrastructure.db.models.task_approval import TaskApprovalModel


def _to_entity(model: TaskApprovalModel) -> TaskApproval:
    return TaskApproval(
        id=model.id,
        org_id=model.org_id,
        task_id=model.task_id,
        task_run_id=model.task_run_id,
        status=model.status,
        risk_category=model.risk_category,
        action_type=model.action_type,
        action_hash=model.action_hash,
        action_summary=model.action_summary,
        action_payload=model.action_payload or {},
        consumed_at=model.consumed_at,
        decided_by_clerk_user_id=model.decided_by_clerk_user_id,
        decision_note=model.decision_note,
        expires_at=model.expires_at,
        decided_at=model.decided_at,
        created_at=model.created_at,
    )


class SqlAlchemyTaskApprovalRepository(TaskApprovalRepository):
    """Async SQLAlchemy adapter for TaskApproval persistence and atomic transitions."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def create_pending(
        self,
        org_id: uuid.UUID,
        task_id: uuid.UUID,
        task_run_id: uuid.UUID,
        risk_category: str,
        action_type: str,
        action_hash: str,
        action_summary: str,
        action_payload: dict,
        expires_at: datetime,
    ) -> TaskApproval:
        model = TaskApprovalModel(
            org_id=org_id,
            task_id=task_id,
            task_run_id=task_run_id,
            status="pending",
            risk_category=risk_category,
            action_type=action_type,
            action_hash=action_hash,
            action_summary=action_summary,
            action_payload=action_payload,
            expires_at=expires_at,
        )
        self._session.add(model)
        try:
            await self._session.flush()
        except IntegrityError as exc:
            raise ConflictError(
                f"Task {task_id} already has a pending approval request"
            ) from exc
        return _to_entity(model)

    async def get_by_id(
        self, org_id: uuid.UUID, approval_id: uuid.UUID
    ) -> TaskApproval:
        stmt = (
            select(TaskApprovalModel)
            .where(
                TaskApprovalModel.org_id == org_id,
                TaskApprovalModel.id == approval_id,
            )
            .execution_options(populate_existing=True)
        )
        model = (await self._session.execute(stmt)).scalar_one_or_none()
        if not model:
            raise NotFoundError(
                f"Approval {approval_id} not found in tenant organization"
            )
        return _to_entity(model)

    async def get_pending_for_task(
        self, org_id: uuid.UUID, task_id: uuid.UUID
    ) -> TaskApproval | None:
        stmt = (
            select(TaskApprovalModel)
            .where(
                TaskApprovalModel.org_id == org_id,
                TaskApprovalModel.task_id == task_id,
                TaskApprovalModel.status == "pending",
            )
            .execution_options(populate_existing=True)
        )
        model = (await self._session.execute(stmt)).scalar_one_or_none()
        return _to_entity(model) if model else None

    async def find_approved_unconsumed(
        self, org_id: uuid.UUID, task_id: uuid.UUID, action_hash: str
    ) -> TaskApproval | None:
        stmt = (
            select(TaskApprovalModel)
            .where(
                TaskApprovalModel.org_id == org_id,
                TaskApprovalModel.task_id == task_id,
                TaskApprovalModel.action_hash == action_hash,
                TaskApprovalModel.status == "approved",
                TaskApprovalModel.consumed_at.is_(None),
            )
            .order_by(TaskApprovalModel.created_at.desc())
            .limit(1)
        )
        model = (await self._session.execute(stmt)).scalar_one_or_none()
        return _to_entity(model) if model else None

    async def mark_consumed(
        self, org_id: uuid.UUID, approval_id: uuid.UUID
    ) -> TaskApproval:
        now = datetime.now(UTC)
        stmt = (
            update(TaskApprovalModel)
            .where(
                TaskApprovalModel.org_id == org_id,
                TaskApprovalModel.id == approval_id,
                TaskApprovalModel.status == "approved",
                TaskApprovalModel.consumed_at.is_(None),
            )
            .values(consumed_at=now)
            .execution_options(synchronize_session="fetch")
            .returning(TaskApprovalModel)
        )
        model = (await self._session.execute(stmt)).scalar_one_or_none()
        if not model:
            return await self.get_by_id(org_id, approval_id)
        await self._session.flush()
        return _to_entity(model)

    async def decide_atomic(
        self,
        org_id: uuid.UUID,
        task_id: uuid.UUID,
        approval_id: uuid.UUID,
        decision: str,
        decided_by_clerk_user_id: str,
        decision_note: str | None = None,
    ) -> TaskApproval | None:
        now = datetime.now(UTC)
        stmt = (
            update(TaskApprovalModel)
            .where(
                TaskApprovalModel.id == approval_id,
                TaskApprovalModel.org_id == org_id,
                TaskApprovalModel.task_id == task_id,
                TaskApprovalModel.status == "pending",
            )
            .values(
                status=decision,
                decided_by_clerk_user_id=decided_by_clerk_user_id,
                decision_note=decision_note,
                decided_at=now,
            )
            .returning(TaskApprovalModel)
        )
        model = (await self._session.execute(stmt)).scalar_one_or_none()
        if not model:
            return None
        await self._session.flush()
        return _to_entity(model)

    async def expire_atomic(
        self,
        org_id: uuid.UUID,
        task_id: uuid.UUID,
        approval_id: uuid.UUID,
    ) -> TaskApproval | None:
        now = datetime.now(UTC)
        stmt = (
            update(TaskApprovalModel)
            .where(
                TaskApprovalModel.id == approval_id,
                TaskApprovalModel.org_id == org_id,
                TaskApprovalModel.task_id == task_id,
                TaskApprovalModel.status == "pending",
            )
            .values(
                status="expired",
                decided_at=now,
            )
            .returning(TaskApprovalModel)
        )
        model = (await self._session.execute(stmt)).scalar_one_or_none()
        if not model:
            return None
        await self._session.flush()
        return _to_entity(model)
