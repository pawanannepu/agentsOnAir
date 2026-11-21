"""Database base definitions, UUIDv7 helpers, and reusable mixins."""

import uuid
from datetime import UTC, datetime

import uuid_utils
from sqlalchemy import DateTime, func
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


def uuid7() -> uuid.UUID:
    """Generate a time-ordered UUIDv7 as a standard uuid.UUID instance."""
    return uuid.UUID(str(uuid_utils.uuid7()))


class Base(DeclarativeBase):
    """Base class for all SQLAlchemy declarative models."""


class TimestampMixin:
    """Mixin providing created_at and updated_at timestamp columns with timezones."""

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(UTC),
        server_default=func.now(),
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(UTC),
        server_default=func.now(),
        onupdate=lambda: datetime.now(UTC),
    )


class SoftDeleteMixin:
    """Mixin providing nullable deleted_at timestamp column for soft deletion."""

    deleted_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
        default=None,
    )
