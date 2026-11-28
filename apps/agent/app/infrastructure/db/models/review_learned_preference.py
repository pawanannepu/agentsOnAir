"""ReviewLearnedPreference declarative model."""

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
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.infrastructure.db.base import Base, TimestampMixin, uuid7

if TYPE_CHECKING:
    from app.infrastructure.db.models.organization import OrganizationModel
    from app.infrastructure.db.models.repository import RepositoryModel
    from app.infrastructure.db.models.review_finding_feedback import (
        ReviewFindingFeedbackModel,
    )
    from app.infrastructure.db.models.review_rule import ReviewRuleModel


class ReviewLearnedPreferenceModel(Base, TimestampMixin):
    """Repository-scoped learned pattern preference with dampening and suppression."""

    __tablename__ = "review_learned_preferences"

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
    rule_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("review_rules.id", ondelete="SET NULL"),
        nullable=True,
    )
    source_feedback_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("review_finding_feedback.id", ondelete="SET NULL"),
        nullable=True,
    )
    pattern_key: Mapped[str] = mapped_column(
        String(255),
        nullable=False,
    )
    instruction: Mapped[str] = mapped_column(
        Text,
        nullable=False,
    )
    dismiss_count: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        default=0,
        server_default="0",
    )
    accept_count: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        default=0,
        server_default="0",
    )
    consecutive_dismissals: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        default=0,
        server_default="0",
    )
    status: Mapped[str] = mapped_column(
        String(20),
        nullable=False,
        default="active",
        server_default="active",
    )
    last_feedback_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )

    __table_args__ = (
        CheckConstraint(
            "status IN ('active', 'dampened', 'suppressed')",
            name="ck_review_learned_prefs_status",
        ),
        Index(
            "uq_review_learned_prefs_repo_pattern",
            "repo_id",
            "pattern_key",
            unique=True,
        ),
        Index(
            "ix_review_learned_prefs_org_repo_status",
            "org_id",
            "repo_id",
            "status",
        ),
    )

    organization: Mapped["OrganizationModel"] = relationship("OrganizationModel")
    repository: Mapped["RepositoryModel"] = relationship("RepositoryModel")
    rule: Mapped["ReviewRuleModel | None"] = relationship("ReviewRuleModel")
    source_feedback: Mapped["ReviewFindingFeedbackModel | None"] = relationship(
        "ReviewFindingFeedbackModel"
    )
