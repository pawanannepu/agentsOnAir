"""UsageEvent declarative model."""

import uuid
from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.infrastructure.db.base import Base, uuid7

if TYPE_CHECKING:
    from app.infrastructure.db.models.organization import OrganizationModel
    from app.infrastructure.db.models.pull_request_review import PullRequestReviewModel
    from app.infrastructure.db.models.task import TaskModel
    from app.infrastructure.db.models.task_run import TaskRunModel


class UsageEventModel(Base):
    """Append-only LLM token and cost telemetry event per model call."""

    __tablename__ = "usage_events"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid7,
    )
    org_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("organizations.id", ondelete="CASCADE"),
        nullable=False,
    )
    task_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("tasks.id", ondelete="CASCADE"),
        nullable=True,
    )
    task_run_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("task_runs.id", ondelete="CASCADE"),
        nullable=True,
    )
    pr_review_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("pull_request_reviews.id", ondelete="CASCADE"),
        nullable=True,
    )
    provider: Mapped[str] = mapped_column(
        String(64),
        nullable=False,
    )
    model: Mapped[str] = mapped_column(
        String(128),
        nullable=False,
    )
    operation_type: Mapped[str] = mapped_column(
        String(32),
        nullable=False,
    )
    prompt_tokens: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
    )
    completion_tokens: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
    )
    estimated_cost_cents: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )

    __table_args__ = (
        CheckConstraint(
            "operation_type IN ('forge', 'reviewer', 'pr_review')",
            name="ck_usage_events_operation_type",
        ),
        CheckConstraint(
            "task_run_id IS NOT NULL OR pr_review_id IS NOT NULL",
            name="ck_usage_events_parent_ref",
        ),
        Index(
            "ix_usage_events_org_created",
            "org_id",
            text("created_at DESC"),
        ),
        Index(
            "ix_usage_events_task_run_created",
            "task_run_id",
            text("created_at ASC"),
        ),
    )

    organization: Mapped["OrganizationModel"] = relationship("OrganizationModel")
    task: Mapped["TaskModel | None"] = relationship("TaskModel")
    task_run: Mapped["TaskRunModel | None"] = relationship("TaskRunModel")
    pr_review: Mapped["PullRequestReviewModel | None"] = relationship(
        "PullRequestReviewModel"
    )
