"""Repository declarative model."""

import uuid
from typing import TYPE_CHECKING

from sqlalchemy import BigInteger, Boolean, ForeignKey, Index, String, text
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.infrastructure.db.base import Base, SoftDeleteMixin, TimestampMixin, uuid7

if TYPE_CHECKING:
    from app.infrastructure.db.models.credential import CredentialModel
    from app.infrastructure.db.models.organization import OrganizationModel
    from app.infrastructure.db.models.task import TaskModel


class RepositoryModel(Base, TimestampMixin, SoftDeleteMixin):
    """Repository entity representing a synchronized GitHub repository."""

    __tablename__ = "repositories"

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
    github_repo_id: Mapped[int] = mapped_column(
        BigInteger,
        nullable=False,
        index=True,
    )
    github_installation_id: Mapped[int] = mapped_column(
        BigInteger,
        nullable=False,
    )
    name: Mapped[str] = mapped_column(
        String(255),
        nullable=False,
    )
    full_name: Mapped[str] = mapped_column(
        String(255),
        nullable=False,
    )
    default_branch: Mapped[str] = mapped_column(
        String(100),
        nullable=False,
        default="main",
        server_default="main",
    )
    is_private: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        default=True,
        server_default=text("true"),
    )
    config: Mapped[dict] = mapped_column(
        JSONB,
        nullable=False,
        default=dict,
        server_default=text("'{}'::jsonb"),
    )

    __table_args__ = (
        Index(
            "uq_repositories_active",
            "org_id",
            "github_repo_id",
            unique=True,
            postgresql_where=text("deleted_at IS NULL"),
        ),
        Index("ix_repositories_org_name", "org_id", "name"),
    )

    organization: Mapped["OrganizationModel"] = relationship(
        "OrganizationModel",
        back_populates="repositories",
    )
    credentials: Mapped[list["CredentialModel"]] = relationship(
        "CredentialModel",
        back_populates="repository",
        cascade="all, delete-orphan",
    )
    tasks: Mapped[list["TaskModel"]] = relationship(
        "TaskModel",
        back_populates="repository",
        cascade="all, delete-orphan",
    )
