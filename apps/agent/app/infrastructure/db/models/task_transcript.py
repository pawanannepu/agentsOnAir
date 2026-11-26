"""Task transcript declarative model."""

import uuid
from typing import TYPE_CHECKING

from sqlalchemy import ForeignKey, Index, Integer, LargeBinary, text
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.infrastructure.db.base import Base, TimestampMixin, uuid7

if TYPE_CHECKING:
    from app.infrastructure.db.models.organization import OrganizationModel
    from app.infrastructure.db.models.task import TaskModel
    from app.infrastructure.db.models.task_run import TaskRunModel


class TaskTranscriptModel(Base, TimestampMixin):
    """Archived terminal logs and stream events for completed task runs."""

    __tablename__ = "task_transcripts"

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
        unique=True,
        index=True,
    )
    terminal_log: Mapped[bytes] = mapped_column(
        LargeBinary,
        nullable=False,
    )
    events_json: Mapped[list] = mapped_column(
        JSONB,
        nullable=False,
        default=list,
        server_default=text("'[]'::jsonb"),
    )
    total_lines: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        default=0,
        server_default=text("0"),
    )

    __table_args__ = (
        Index(
            "ix_task_transcripts_task_created",
            "task_id",
            text("created_at DESC"),
        ),
        Index(
            "ix_task_transcripts_org_created",
            "org_id",
            text("created_at DESC"),
        ),
    )

    organization: Mapped["OrganizationModel"] = relationship("OrganizationModel")
    task: Mapped["TaskModel"] = relationship("TaskModel", back_populates="transcripts")
    task_run: Mapped["TaskRunModel"] = relationship("TaskRunModel")
