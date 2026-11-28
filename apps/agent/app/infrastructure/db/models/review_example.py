"""ReviewExample declarative model."""

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
    Text,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.infrastructure.db.base import Base, TimestampMixin, uuid7

if TYPE_CHECKING:
    from app.infrastructure.db.models.organization import OrganizationModel
    from app.infrastructure.db.models.repository import RepositoryModel


class ReviewExampleModel(Base, TimestampMixin):
    """Curated example pull request cached for repository review context."""

    __tablename__ = "review_examples"

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
    pr_number: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
    )
    pr_url: Mapped[str] = mapped_column(
        String(512),
        nullable=False,
    )
    pr_title: Mapped[str] = mapped_column(
        String(512),
        nullable=False,
    )
    classification: Mapped[str] = mapped_column(
        String(20),
        nullable=False,
    )
    guidance_note: Mapped[str] = mapped_column(
        Text,
        nullable=False,
    )
    modified_files: Mapped[list[str]] = mapped_column(
        JSONB,
        nullable=False,
        default=list,
        server_default=text("'[]'::jsonb"),
    )
    cached_diff_summary: Mapped[str | None] = mapped_column(
        Text,
        nullable=True,
    )
    cached_token_count: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        default=0,
        server_default="0",
    )
    cached_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )
    created_by: Mapped[str] = mapped_column(
        String(255),
        nullable=False,
    )

    __table_args__ = (
        CheckConstraint(
            "classification IN ('good', 'bad')",
            name="ck_review_examples_classification",
        ),
        Index(
            "uq_review_examples_repo_pr",
            "repo_id",
            "pr_number",
            unique=True,
        ),
        Index("ix_review_examples_org_repo", "org_id", "repo_id"),
    )

    organization: Mapped["OrganizationModel"] = relationship("OrganizationModel")
    repository: Mapped["RepositoryModel"] = relationship("RepositoryModel")
