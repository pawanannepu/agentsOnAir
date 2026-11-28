"""ReviewRule declarative model."""

import uuid
from typing import TYPE_CHECKING

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    ForeignKey,
    Index,
    String,
    Text,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.infrastructure.db.base import Base, SoftDeleteMixin, TimestampMixin, uuid7

if TYPE_CHECKING:
    from app.infrastructure.db.models.organization import OrganizationModel
    from app.infrastructure.db.models.repository import RepositoryModel


class ReviewRuleModel(Base, TimestampMixin, SoftDeleteMixin):
    """Organization default or repository-specific code review rule."""

    __tablename__ = "review_rules"

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
    repo_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("repositories.id", ondelete="CASCADE"),
        nullable=True,
    )
    title: Mapped[str] = mapped_column(
        String(200),
        nullable=False,
    )
    instruction: Mapped[str] = mapped_column(
        Text,
        nullable=False,
    )
    severity: Mapped[str] = mapped_column(
        String(20),
        nullable=False,
    )
    category: Mapped[str] = mapped_column(
        String(50),
        nullable=False,
    )
    path_globs: Mapped[list[str]] = mapped_column(
        JSONB,
        nullable=False,
        default=lambda: ["**/*"],
        server_default=text("'[\"**/*\"]'::jsonb"),
    )
    is_enabled: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        default=True,
        server_default=text("true"),
    )
    created_by: Mapped[str] = mapped_column(
        String(255),
        nullable=False,
    )

    __table_args__ = (
        CheckConstraint(
            "severity IN ('critical', 'major', 'minor', 'info')",
            name="ck_review_rules_severity",
        ),
        CheckConstraint(
            "category IN ('security', 'bug', 'performance', 'architecture', 'style')",
            name="ck_review_rules_category",
        ),
        Index(
            "ix_review_rules_org_repo_enabled_active",
            "org_id",
            "repo_id",
            "is_enabled",
            postgresql_where=text("deleted_at IS NULL"),
        ),
    )

    organization: Mapped["OrganizationModel"] = relationship("OrganizationModel")
    repository: Mapped["RepositoryModel | None"] = relationship("RepositoryModel")
