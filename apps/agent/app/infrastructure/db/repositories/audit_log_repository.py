"""SQLAlchemy audit_log repository implementation."""

import uuid

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.application.ports.audit_log_repository import AuditLogRepository
from app.domain.entities.audit_log import AuditLog
from app.infrastructure.db.models.audit_log import AuditLogModel


def _to_entity(model: AuditLogModel) -> AuditLog:
    return AuditLog(
        id=model.id,
        org_id=model.org_id,
        actor_type=model.actor_type,
        actor_id=model.actor_id,
        action=model.action,
        target_type=model.target_type,
        target_id=model.target_id,
        payload_before=model.payload_before,
        payload_after=model.payload_after,
        ip_address=model.ip_address,
        created_at=model.created_at,
    )


class SqlAlchemyAuditLogRepository(AuditLogRepository):
    """Async SQLAlchemy adapter for append-only AuditLog persistence."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def record_event(
        self,
        org_id: uuid.UUID,
        actor_type: str,
        actor_id: str,
        action: str,
        target_type: str,
        target_id: uuid.UUID,
        payload_before: dict | None = None,
        payload_after: dict | None = None,
        ip_address: str | None = None,
    ) -> AuditLog:
        model = AuditLogModel(
            org_id=org_id,
            actor_type=actor_type,
            actor_id=actor_id,
            action=action,
            target_type=target_type,
            target_id=target_id,
            payload_before=payload_before,
            payload_after=payload_after,
            ip_address=ip_address,
        )
        self._session.add(model)
        await self._session.flush()
        return _to_entity(model)

    async def list_events(
        self,
        org_id: uuid.UUID,
        page: int = 1,
        page_size: int = 20,
        target_type: str | None = None,
    ) -> tuple[list[AuditLog], int]:
        count_stmt = select(func.count(AuditLogModel.id)).where(
            AuditLogModel.org_id == org_id
        )
        if target_type:
            count_stmt = count_stmt.where(AuditLogModel.target_type == target_type)
        total = (await self._session.execute(count_stmt)).scalar_one()

        offset = max(0, (page - 1) * page_size)
        list_stmt = (
            select(AuditLogModel)
            .where(AuditLogModel.org_id == org_id)
            .order_by(AuditLogModel.created_at.desc())
            .offset(offset)
            .limit(page_size)
        )
        if target_type:
            list_stmt = list_stmt.where(AuditLogModel.target_type == target_type)

        models = (await self._session.execute(list_stmt)).scalars().all()
        return [_to_entity(m) for m in models], total
