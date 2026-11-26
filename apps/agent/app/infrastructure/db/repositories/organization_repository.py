"""SQLAlchemy organization repository implementation."""

import uuid
from datetime import UTC, datetime

from sqlalchemy import func, select, update
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.application.ports.organization_repository import OrganizationRepository
from app.domain.entities.organization import Organization
from app.domain.exceptions import ConflictError, NotFoundError
from app.infrastructure.db.base import uuid7
from app.infrastructure.db.models.organization import OrganizationModel


def _to_entity(model: OrganizationModel) -> Organization:
    return Organization(
        id=model.id,
        clerk_org_id=model.clerk_org_id,
        name=model.name,
        slug=model.slug,
        github_installation_id=model.github_installation_id,
        settings=model.settings or {},
        created_at=model.created_at,
        updated_at=model.updated_at,
        deleted_at=model.deleted_at,
    )


class SqlAlchemyOrganizationRepository(OrganizationRepository):
    """Async SQLAlchemy adapter for Organization persistence."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def get_by_id(self, org_id: uuid.UUID) -> Organization:
        stmt = select(OrganizationModel).where(
            OrganizationModel.id == org_id,
            OrganizationModel.deleted_at.is_(None),
        )
        result = await self._session.execute(stmt)
        model = result.scalar_one_or_none()
        if not model:
            raise NotFoundError(f"Organization {org_id} not found")
        return _to_entity(model)

    async def get_by_clerk_id(self, clerk_org_id: str) -> Organization:
        stmt = select(OrganizationModel).where(
            OrganizationModel.clerk_org_id == clerk_org_id,
            OrganizationModel.deleted_at.is_(None),
        )
        result = await self._session.execute(stmt)
        model = result.scalar_one_or_none()
        if not model:
            raise NotFoundError(
                f"Organization with Clerk ID '{clerk_org_id}' not found"
            )
        return _to_entity(model)

    async def get_by_clerk_id_including_deleted(
        self, clerk_org_id: str
    ) -> Organization | None:
        stmt = select(OrganizationModel).where(
            OrganizationModel.clerk_org_id == clerk_org_id
        )
        result = await self._session.execute(stmt)
        model = result.scalar_one_or_none()
        return _to_entity(model) if model else None

    async def create_or_update(
        self,
        clerk_org_id: str,
        name: str,
        slug: str,
        github_installation_id: int | None = None,
        settings: dict | None = None,
    ) -> Organization:
        """Atomically upsert an active organization via PostgreSQL ON CONFLICT."""
        now = datetime.now(UTC)
        update_values: dict[str, object] = {
            "name": name,
            "slug": slug,
            "deleted_at": None,
            "updated_at": func.now(),
        }
        if github_installation_id is not None:
            update_values["github_installation_id"] = github_installation_id
        if settings is not None:
            update_values["settings"] = settings

        stmt = (
            pg_insert(OrganizationModel)
            .values(
                id=uuid7(),
                clerk_org_id=clerk_org_id,
                name=name,
                slug=slug,
                github_installation_id=github_installation_id,
                settings=settings if settings is not None else {},
                created_at=now,
                updated_at=now,
                deleted_at=None,
            )
            .on_conflict_do_update(
                index_elements=[OrganizationModel.clerk_org_id],
                set_=update_values,
            )
            .returning(OrganizationModel)
        )
        try:
            result = await self._session.execute(stmt)
        except IntegrityError as exc:
            raise ConflictError(
                f"Active organization slug '{slug}' conflicts with another organization"
            ) from exc

        model = result.scalar_one()
        await self._session.flush()
        return _to_entity(model)

    async def create_or_update_if_active(
        self,
        clerk_org_id: str,
        name: str,
        slug: str,
    ) -> Organization | None:
        """Insert if absent or update only active rows without resurrecting."""
        now = datetime.now(UTC)
        stmt = (
            pg_insert(OrganizationModel)
            .values(
                id=uuid7(),
                clerk_org_id=clerk_org_id,
                name=name,
                slug=slug,
                settings={},
                created_at=now,
                updated_at=now,
                deleted_at=None,
            )
            .on_conflict_do_update(
                index_elements=[OrganizationModel.clerk_org_id],
                set_={
                    "name": name,
                    "slug": slug,
                    "updated_at": func.now(),
                },
                where=OrganizationModel.deleted_at.is_(None),
            )
            .returning(OrganizationModel)
        )
        try:
            result = await self._session.execute(stmt)
        except IntegrityError as exc:
            raise ConflictError(
                f"Active organization slug '{slug}' conflicts with another organization"
            ) from exc

        model = result.scalar_one_or_none()
        if not model:
            return None
        await self._session.flush()
        return _to_entity(model)

    async def soft_delete_by_clerk_id(self, clerk_org_id: str) -> Organization | None:
        """Idempotently soft delete an active organization by Clerk ID."""
        now = datetime.now(UTC)
        stmt = (
            update(OrganizationModel)
            .where(
                OrganizationModel.clerk_org_id == clerk_org_id,
                OrganizationModel.deleted_at.is_(None),
            )
            .values(
                deleted_at=now,
                updated_at=now,
            )
            .returning(OrganizationModel)
        )
        result = await self._session.execute(stmt)
        model = result.scalar_one_or_none()
        if not model:
            return None
        await self._session.flush()
        return _to_entity(model)

    async def update_settings(
        self,
        org_id: uuid.UUID,
        settings: dict,
    ) -> Organization:
        """Update JSONB settings on an active organization."""
        now = datetime.now(UTC)
        stmt = (
            update(OrganizationModel)
            .where(
                OrganizationModel.id == org_id,
                OrganizationModel.deleted_at.is_(None),
            )
            .values(
                settings=settings,
                updated_at=now,
            )
            .returning(OrganizationModel)
        )
        result = await self._session.execute(stmt)
        model = result.scalar_one_or_none()
        if not model:
            raise NotFoundError(f"Organization {org_id} not found")
        await self._session.flush()
        return _to_entity(model)
