"""TaskApproval declarative model."""

import uuid
from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    String,
    Text,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.infrastructure.db.base import Base, uuid7

if TYPE_CHECKING:
    from app.infrastructure.db.models.organization import OrganizationModel
    from app.infrastructure.db.models.task import TaskModel
    from app.infrastructure.db.models.task_run import TaskRunModel


class TaskApprovalModel(Base):
    """Durable approval request for risky autonomous actions paused via LangGraph."""

    __tablename__ = "task_approvals"

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
    task_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("tasks.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    task_run_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("task_runs.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    status: Mapped[str] = mapped_column(
        String(32),
        nullable=False,
        default="pending",
        server_default="pending",
    )
    risk_category: Mapped[str] = mapped_column(
        String(64),
        nullable=False,
    )
    action_type: Mapped[str] = mapped_column(
        String(64),
        nullable=False,
    )
    action_hash: Mapped[str] = mapped_column(
        String(64),
        nullable=False,
    )
    action_summary: Mapped[str] = mapped_column(
        Text,
        nullable=False,
    )
    action_payload: Mapped[dict] = mapped_column(
        JSONB,
        nullable=False,
        default=dict,
        server_default=text("'{}'::jsonb"),
    )
    consumed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )
    decided_by_clerk_user_id: Mapped[str | None] = mapped_column(
        String(255),
        nullable=True,
    )
    decision_note: Mapped[str | None] = mapped_column(
        Text,
        nullable=True,
    )
    expires_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
    )
    decided_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )

    __table_args__ = (
        CheckConstraint(
            "status IN ('pending', 'approved', 'rejected', 'expired')",
            name="ck_task_approvals_status",
        ),
        Index(
            "uq_task_approvals_pending_task",
            "task_id",
            unique=True,
            postgresql_where=text("status = 'pending'"),
        ),
        Index(
            "ix_task_approvals_task_created",
            "task_id",
            text("created_at DESC"),
        ),
        Index(
            "ix_task_approvals_task_hash_status",
            "task_id",
            "action_hash",
            "status",
        ),
    )

    organization: Mapped["OrganizationModel"] = relationship("OrganizationModel")
    task: Mapped["TaskModel"] = relationship("TaskModel")
    task_run: Mapped["TaskRunModel"] = relationship("TaskRunModel")
