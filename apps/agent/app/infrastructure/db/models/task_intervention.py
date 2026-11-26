"""Task intervention declarative model."""

import uuid
from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import DateTime, ForeignKey, Index, String, Text, text
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.infrastructure.db.base import Base, TimestampMixin, uuid7

if TYPE_CHECKING:
    from app.infrastructure.db.models.organization import OrganizationModel
    from app.infrastructure.db.models.task import TaskModel
    from app.infrastructure.db.models.task_run import TaskRunModel


class TaskInterventionModel(Base, TimestampMixin):
    """Developer steering comments, clarification replies, and abort actions."""

    __tablename__ = "task_interventions"

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
    task_run_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("task_runs.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    clerk_user_id: Mapped[str] = mapped_column(
        String(255),
        nullable=False,
        index=True,
    )
    intervention_type: Mapped[str] = mapped_column(
        String(50),
        nullable=False,
    )
    prompt_snapshot: Mapped[str | None] = mapped_column(
        Text,
        nullable=True,
    )
    payload: Mapped[dict] = mapped_column(
        JSONB,
        nullable=False,
        default=dict,
        server_default=text("'{}'::jsonb"),
    )
    applied_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )

    __table_args__ = (
        Index(
            "ix_task_interventions_task_created",
            "task_id",
            text("created_at ASC"),
        ),
        Index(
            "ix_task_interventions_org_created",
            "org_id",
            text("created_at DESC"),
        ),
    )

    organization: Mapped["OrganizationModel"] = relationship("OrganizationModel")
    task: Mapped["TaskModel"] = relationship(
        "TaskModel", back_populates="interventions"
    )
    task_run: Mapped["TaskRunModel | None"] = relationship("TaskRunModel")
