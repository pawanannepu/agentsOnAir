"""Organization declarative model."""

import uuid
from typing import TYPE_CHECKING

from sqlalchemy import BigInteger, Index, String, text
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.infrastructure.db.base import Base, SoftDeleteMixin, TimestampMixin, uuid7

if TYPE_CHECKING:
    from app.infrastructure.db.models.audit_log import AuditLogModel
    from app.infrastructure.db.models.credential import CredentialModel
    from app.infrastructure.db.models.repository import RepositoryModel
    from app.infrastructure.db.models.sandbox_run import SandboxRunModel
    from app.infrastructure.db.models.task import TaskModel
    from app.infrastructure.db.models.task_intervention import TaskInterventionModel
    from app.infrastructure.db.models.task_run import TaskRunModel
    from app.infrastructure.db.models.task_transcript import TaskTranscriptModel


class OrganizationModel(Base, TimestampMixin, SoftDeleteMixin):
    """Organization entity representing a tenant organization linked to Clerk."""

    __tablename__ = "organizations"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid7,
    )
    clerk_org_id: Mapped[str] = mapped_column(
        String(255),
        unique=True,
        nullable=False,
        index=True,
    )
    name: Mapped[str] = mapped_column(
        String(255),
        nullable=False,
    )
    slug: Mapped[str] = mapped_column(
        String(255),
        nullable=False,
    )
    github_installation_id: Mapped[int | None] = mapped_column(
        BigInteger,
        nullable=True,
    )
    settings: Mapped[dict] = mapped_column(
        JSONB,
        nullable=False,
        default=dict,
        server_default=text("'{}'::jsonb"),
    )

    __table_args__ = (
        Index(
            "uq_organizations_slug_active",
            "slug",
            unique=True,
            postgresql_where=text("deleted_at IS NULL"),
        ),
    )

    repositories: Mapped[list["RepositoryModel"]] = relationship(
        "RepositoryModel",
        back_populates="organization",
        cascade="all, delete-orphan",
    )
    credentials: Mapped[list["CredentialModel"]] = relationship(
        "CredentialModel",
        back_populates="organization",
        cascade="all, delete-orphan",
    )
    tasks: Mapped[list["TaskModel"]] = relationship(
        "TaskModel",
        back_populates="organization",
        cascade="all, delete-orphan",
    )
    task_runs: Mapped[list["TaskRunModel"]] = relationship(
        "TaskRunModel",
        back_populates="organization",
        cascade="all, delete-orphan",
    )
    sandbox_runs: Mapped[list["SandboxRunModel"]] = relationship(
        "SandboxRunModel",
        back_populates="organization",
        cascade="all, delete-orphan",
    )
    audit_logs: Mapped[list["AuditLogModel"]] = relationship(
        "AuditLogModel",
        back_populates="organization",
    )
    interventions: Mapped[list["TaskInterventionModel"]] = relationship(
        "TaskInterventionModel",
        back_populates="organization",
        cascade="all, delete-orphan",
    )
    transcripts: Mapped[list["TaskTranscriptModel"]] = relationship(
        "TaskTranscriptModel",
        back_populates="organization",
        cascade="all, delete-orphan",
    )
