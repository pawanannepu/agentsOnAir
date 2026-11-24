"""PullRequestReview declarative model."""

import uuid
from typing import TYPE_CHECKING

from sqlalchemy import BigInteger, ForeignKey, Index, Integer, String, Text, text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.infrastructure.db.base import Base, TimestampMixin, uuid7

if TYPE_CHECKING:
    from app.infrastructure.db.models.organization import OrganizationModel
    from app.infrastructure.db.models.pr_review_finding import PRReviewFindingModel
    from app.infrastructure.db.models.repository import RepositoryModel
    from app.infrastructure.db.models.task import TaskModel


class PullRequestReviewModel(Base, TimestampMixin):
    """PR code review entity with structured findings and GitHub submission state."""

    __tablename__ = "pull_request_reviews"

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
    task_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("tasks.id", ondelete="SET NULL"),
        nullable=True,
    )
    pr_number: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
    )
    pr_title: Mapped[str] = mapped_column(
        String(512),
        nullable=False,
    )
    pr_author: Mapped[str] = mapped_column(
        String(100),
        nullable=False,
    )
    head_commit_sha: Mapped[str] = mapped_column(
        String(40),
        nullable=False,
    )
    base_commit_sha: Mapped[str] = mapped_column(
        String(40),
        nullable=False,
    )
    status: Mapped[str] = mapped_column(
        String(50),
        nullable=False,
        default="pending",
        server_default="pending",
    )
    verdict: Mapped[str | None] = mapped_column(
        String(50),
        nullable=True,
    )
    summary: Mapped[str | None] = mapped_column(
        Text,
        nullable=True,
    )
    github_review_id: Mapped[int | None] = mapped_column(
        BigInteger,
        nullable=True,
    )
    context_token_count: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        default=0,
        server_default="0",
    )
    model_name: Mapped[str] = mapped_column(
        String(100),
        nullable=False,
    )
    execution_duration_ms: Mapped[int | None] = mapped_column(
        Integer,
        nullable=True,
    )
    error_message: Mapped[str | None] = mapped_column(
        Text,
        nullable=True,
    )

    __table_args__ = (
        Index(
            "ix_pr_reviews_repo_pr_created",
            "repo_id",
            "pr_number",
            text("created_at DESC"),
        ),
        Index(
            "ix_pr_reviews_org_created",
            "org_id",
            text("created_at DESC"),
        ),
        Index(
            "uq_pr_reviews_active_pr",
            "repo_id",
            "pr_number",
            unique=True,
            postgresql_where=text(
                "status IN ('pending', 'analyzing', 'reviewing', 'posting')"
            ),
        ),
    )

    organization: Mapped["OrganizationModel"] = relationship(
        "OrganizationModel",
    )
    repository: Mapped["RepositoryModel"] = relationship(
        "RepositoryModel",
    )
    task: Mapped["TaskModel | None"] = relationship(
        "TaskModel",
    )
    findings: Mapped[list["PRReviewFindingModel"]] = relationship(
        "PRReviewFindingModel",
        back_populates="review",
        cascade="all, delete-orphan",
    )
