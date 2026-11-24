"""PRReviewFinding declarative model."""

import uuid
from datetime import UTC, datetime
from typing import TYPE_CHECKING

from sqlalchemy import (
    BigInteger,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    func,
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.infrastructure.db.base import Base, uuid7

if TYPE_CHECKING:
    from app.infrastructure.db.models.pull_request_review import PullRequestReviewModel


class PRReviewFindingModel(Base):
    """Individual code review finding with severity classification."""

    __tablename__ = "pr_review_findings"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid7,
    )
    review_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("pull_request_reviews.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    file_path: Mapped[str] = mapped_column(
        String(1024),
        nullable=False,
    )
    start_line: Mapped[int | None] = mapped_column(
        Integer,
        nullable=True,
    )
    line_number: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
    )
    side: Mapped[str] = mapped_column(
        String(10),
        nullable=False,
        default="RIGHT",
        server_default="RIGHT",
    )
    severity: Mapped[str] = mapped_column(
        String(20),
        nullable=False,
    )
    category: Mapped[str] = mapped_column(
        String(50),
        nullable=False,
    )
    title: Mapped[str] = mapped_column(
        String(255),
        nullable=False,
    )
    message: Mapped[str] = mapped_column(
        Text,
        nullable=False,
    )
    suggested_patch: Mapped[str | None] = mapped_column(
        Text,
        nullable=True,
    )
    github_comment_id: Mapped[int | None] = mapped_column(
        BigInteger,
        nullable=True,
    )
    status: Mapped[str] = mapped_column(
        String(30),
        nullable=False,
        default="open",
        server_default="open",
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(UTC),
        server_default=func.now(),
    )

    __table_args__ = (
        Index("ix_pr_findings_review_severity", "review_id", "severity"),
        Index("ix_pr_findings_review_file", "review_id", "file_path"),
    )

    review: Mapped["PullRequestReviewModel"] = relationship(
        "PullRequestReviewModel",
        back_populates="findings",
    )
