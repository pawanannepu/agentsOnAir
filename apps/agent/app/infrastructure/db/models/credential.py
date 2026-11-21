"""Credential declarative model."""

import uuid
from typing import TYPE_CHECKING

from sqlalchemy import ForeignKey, Index, Integer, String, Text, text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.infrastructure.db.base import Base, TimestampMixin, uuid7

if TYPE_CHECKING:
    from app.infrastructure.db.models.organization import OrganizationModel
    from app.infrastructure.db.models.repository import RepositoryModel


class CredentialModel(Base, TimestampMixin):
    """Credential entity storing AES-256-GCM encrypted tokens and keys."""

    __tablename__ = "credentials"

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
    repo_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("repositories.id", ondelete="CASCADE"),
        nullable=True,
        index=True,
    )
    name: Mapped[str] = mapped_column(
        String(100),
        nullable=False,
    )
    credential_type: Mapped[str] = mapped_column(
        String(50),
        nullable=False,
    )
    encrypted_data: Mapped[str] = mapped_column(
        Text,
        nullable=False,
    )
    nonce: Mapped[str] = mapped_column(
        Text,
        nullable=False,
    )
    key_version: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        default=1,
        server_default="1",
    )

    __table_args__ = (
        Index(
            "uq_credentials_active",
            "org_id",
            text("COALESCE(repo_id, '00000000-0000-0000-0000-000000000000'::uuid)"),
            "name",
            unique=True,
        ),
    )

    organization: Mapped["OrganizationModel"] = relationship(
        "OrganizationModel",
        back_populates="credentials",
    )
    repository: Mapped["RepositoryModel | None"] = relationship(
        "RepositoryModel",
        back_populates="credentials",
    )
