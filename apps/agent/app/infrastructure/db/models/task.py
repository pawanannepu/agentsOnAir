"""Task declarative model."""

import uuid
from typing import TYPE_CHECKING

from sqlalchemy import ForeignKey, Index, Integer, String, Text, text
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.infrastructure.db.base import Base, SoftDeleteMixin, TimestampMixin, uuid7

if TYPE_CHECKING:
    from app.infrastructure.db.models.organization import OrganizationModel
    from app.infrastructure.db.models.repository import RepositoryModel
    from app.infrastructure.db.models.task_run import TaskRunModel


class TaskModel(Base, TimestampMixin, SoftDeleteMixin):
    """Task entity representing a user intent or webhook triggered agent job."""

    __tablename__ = "tasks"

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
    repo_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("repositories.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    title: Mapped[str] = mapped_column(
        String(255),
        nullable=False,
    )
    description: Mapped[str] = mapped_column(
        Text,
        nullable=False,
    )
    status: Mapped[str] = mapped_column(
        String(50),
        nullable=False,
        default="queued",
        server_default="queued",
    )
    trigger_type: Mapped[str] = mapped_column(
        String(50),
        nullable=False,
    )
    trigger_metadata: Mapped[dict] = mapped_column(
        JSONB,
        nullable=False,
        default=dict,
        server_default=text("'{}'::jsonb"),
    )
    branch_name: Mapped[str | None] = mapped_column(
        String(255),
        nullable=True,
    )
    base_branch: Mapped[str] = mapped_column(
        String(100),
        nullable=False,
        default="main",
        server_default="main",
    )
    pr_number: Mapped[int | None] = mapped_column(
        Integer,
        nullable=True,
    )
    pr_url: Mapped[str | None] = mapped_column(
        String(512),
        nullable=True,
    )
    head_commit_sha: Mapped[str | None] = mapped_column(
        String(40),
        nullable=True,
    )
    pr_review_status: Mapped[str | None] = mapped_column(
        String(50),
        nullable=True,
    )
    created_by_clerk_user_id: Mapped[str | None] = mapped_column(
        String(255),
        nullable=True,
    )

    __table_args__ = (
        Index(
            "ix_tasks_org_status_created",
            "org_id",
            "status",
            text("created_at DESC"),
        ),
        Index(
            "ix_tasks_repo_created",
            "repo_id",
            text("created_at DESC"),
        ),
        Index(
            "uq_tasks_active_repo_issue",
            "repo_id",
            text("(trigger_metadata->>'issue_number')"),
            unique=True,
            postgresql_where=text(
                "status IN ('queued', 'in_progress') AND deleted_at IS NULL"
            ),
        ),
    )

    organization: Mapped["OrganizationModel"] = relationship(
        "OrganizationModel",
        back_populates="tasks",
    )
    repository: Mapped["RepositoryModel"] = relationship(
        "RepositoryModel",
        back_populates="tasks",
    )
    task_runs: Mapped[list["TaskRunModel"]] = relationship(
        "TaskRunModel",
        back_populates="task",
        cascade="all, delete-orphan",
    )
