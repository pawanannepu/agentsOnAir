"""ReviewFindingFeedback declarative model."""

import uuid
from datetime import UTC, datetime
from typing import TYPE_CHECKING

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    String,
    Text,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.infrastructure.db.base import Base, uuid7

if TYPE_CHECKING:
    from app.infrastructure.db.models.organization import OrganizationModel
    from app.infrastructure.db.models.pr_review_finding import PRReviewFindingModel
    from app.infrastructure.db.models.repository import RepositoryModel


class ReviewFindingFeedbackModel(Base):
    """Append-only feedback event for a PR review finding."""

    __tablename__ = "review_finding_feedback"

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
    repo_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("repositories.id", ondelete="CASCADE"),
        nullable=False,
    )
    finding_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("pr_review_findings.id", ondelete="CASCADE"),
        nullable=False,
    )
    feedback_type: Mapped[str] = mapped_column(
        String(20),
        nullable=False,
    )
    source: Mapped[str] = mapped_column(
        String(32),
        nullable=False,
    )
    reason: Mapped[str | None] = mapped_column(
        Text,
        nullable=True,
    )
    remember_preference: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        default=False,
        server_default=text("false"),
    )
    actor_id: Mapped[str] = mapped_column(
        String(255),
        nullable=False,
    )
    github_event_id: Mapped[str | None] = mapped_column(
        String(128),
        nullable=True,
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(UTC),
        server_default=func.now(),
    )

    __table_args__ = (
        CheckConstraint(
            "feedback_type IN ('accepted', 'dismissed')",
            name="ck_review_finding_feedback_type",
        ),
        CheckConstraint(
            "source IN ('console', 'github_thread_resolved', 'github_comment_reply')",
            name="ck_review_finding_feedback_source",
        ),
        Index(
            "uq_review_finding_feedback_gh_event",
            "github_event_id",
            unique=True,
            postgresql_where=text("github_event_id IS NOT NULL"),
        ),
        Index(
            "ix_review_finding_feedback_finding_created",
            "finding_id",
            text("created_at DESC"),
        ),
        Index("ix_review_finding_feedback_org_repo", "org_id", "repo_id"),
    )

    organization: Mapped["OrganizationModel"] = relationship("OrganizationModel")
    repository: Mapped["RepositoryModel"] = relationship("RepositoryModel")
    finding: Mapped["PRReviewFindingModel"] = relationship("PRReviewFindingModel")
