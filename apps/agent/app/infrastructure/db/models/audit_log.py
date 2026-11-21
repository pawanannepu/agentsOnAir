"""AuditLog declarative model."""

import uuid
from datetime import UTC, datetime
from typing import TYPE_CHECKING

from sqlalchemy import (
    DateTime,
    ForeignKey,
    Index,
    String,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.infrastructure.db.base import Base, uuid7

if TYPE_CHECKING:
    from app.infrastructure.db.models.organization import OrganizationModel


class AuditLogModel(Base):
    """AuditLog entity storing append-only compliance and mutation records."""

    __tablename__ = "audit_logs"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid7,
    )
    org_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("organizations.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
    actor_type: Mapped[str] = mapped_column(
        String(50),
        nullable=False,
    )
    actor_id: Mapped[str] = mapped_column(
        String(255),
        nullable=False,
    )
    action: Mapped[str] = mapped_column(
        String(100),
        nullable=False,
    )
    target_type: Mapped[str] = mapped_column(
        String(50),
        nullable=False,
    )
    target_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        nullable=False,
    )
    payload_before: Mapped[dict | None] = mapped_column(
        JSONB,
        nullable=True,
    )
    payload_after: Mapped[dict | None] = mapped_column(
        JSONB,
        nullable=True,
    )
    ip_address: Mapped[str | None] = mapped_column(
        String(45),
        nullable=True,
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(UTC),
        server_default=func.now(),
    )

    __table_args__ = (
        Index(
            "ix_audit_logs_org_created",
            "org_id",
            text("created_at DESC"),
        ),
        Index("ix_audit_logs_target", "target_type", "target_id"),
    )

    organization: Mapped["OrganizationModel"] = relationship(
        "OrganizationModel",
        back_populates="audit_logs",
    )
