"""SandboxRun declarative model."""

import uuid
from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import (
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.infrastructure.db.base import Base, TimestampMixin, uuid7

if TYPE_CHECKING:
    from app.infrastructure.db.models.organization import OrganizationModel
    from app.infrastructure.db.models.task_run import TaskRunModel


class SandboxRunModel(Base, TimestampMixin):
    """SandboxRun entity tracking isolated microVM execution sessions."""

    __tablename__ = "sandbox_runs"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid7,
    )
    org_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("organizations.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    task_run_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("task_runs.id", ondelete="CASCADE"),
        nullable=False,
        unique=True,
    )
    provider: Mapped[str] = mapped_column(
        String(50),
        nullable=False,
    )
    sandbox_id: Mapped[str] = mapped_column(
        String(255),
        nullable=False,
    )
    status: Mapped[str] = mapped_column(
        String(50),
        nullable=False,
        default="allocating",
        server_default="allocating",
    )
    exit_code: Mapped[int | None] = mapped_column(
        Integer,
        nullable=True,
    )
    logs_storage_key: Mapped[str | None] = mapped_column(
        String(512),
        nullable=True,
    )
    memory_limit_mb: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        default=2048,
        server_default="2048",
    )
    timeout_seconds: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        default=600,
        server_default="600",
    )
    allocated_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )
    terminated_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )

    __table_args__ = (
        Index("ix_sandbox_runs_org_status", "org_id", "status"),
        Index("ix_sandbox_runs_sandbox_id", "sandbox_id"),
        Index("ix_sandbox_runs_status_created", "status", "created_at"),
    )

    organization: Mapped["OrganizationModel"] = relationship(
        "OrganizationModel",
        back_populates="sandbox_runs",
    )
    task_run: Mapped["TaskRunModel"] = relationship(
        "TaskRunModel",
        back_populates="sandbox_run",
    )
