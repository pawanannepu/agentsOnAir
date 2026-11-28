"""ReviewRuleOverride declarative model."""

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
    func,
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.infrastructure.db.base import Base, uuid7

if TYPE_CHECKING:
    from app.infrastructure.db.models.organization import OrganizationModel
    from app.infrastructure.db.models.repository import RepositoryModel
    from app.infrastructure.db.models.review_rule import ReviewRuleModel


class ReviewRuleOverrideModel(Base):
    """Per-repository override on an inherited organization default rule."""

    __tablename__ = "review_rule_overrides"

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
    rule_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("review_rules.id", ondelete="CASCADE"),
        nullable=False,
    )
    is_enabled: Mapped[bool | None] = mapped_column(
        Boolean,
        nullable=True,
    )
    severity_override: Mapped[str | None] = mapped_column(
        String(20),
        nullable=True,
    )
    updated_by: Mapped[str] = mapped_column(
        String(255),
        nullable=False,
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(UTC),
        server_default=func.now(),
        onupdate=lambda: datetime.now(UTC),
    )

    __table_args__ = (
        CheckConstraint(
            "severity_override IS NULL OR severity_override IN "
            "('critical', 'major', 'minor', 'info')",
            name="ck_review_rule_overrides_severity",
        ),
        Index(
            "uq_review_rule_overrides_repo_rule",
            "repo_id",
            "rule_id",
            unique=True,
        ),
        Index("ix_review_rule_overrides_org_id", "org_id"),
    )

    organization: Mapped["OrganizationModel"] = relationship("OrganizationModel")
    repository: Mapped["RepositoryModel"] = relationship("RepositoryModel")
    rule: Mapped["ReviewRuleModel"] = relationship("ReviewRuleModel")
