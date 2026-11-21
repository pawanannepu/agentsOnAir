"""SQLAlchemy organization repository implementation."""

import uuid
from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.application.ports.organization_repository import OrganizationRepository
from app.domain.entities.organization import Organization
from app.domain.exceptions import NotFoundError
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

    async def create_or_update(
        self,
        clerk_org_id: str,
        name: str,
        slug: str,
        github_installation_id: int | None = None,
        settings: dict | None = None,
    ) -> Organization:
        stmt = select(OrganizationModel).where(
            OrganizationModel.clerk_org_id == clerk_org_id
        )
        result = await self._session.execute(stmt)
        model = result.scalar_one_or_none()

        if model:
            model.name = name
            model.slug = slug
            if github_installation_id is not None:
                model.github_installation_id = github_installation_id
            if settings is not None:
                model.settings = settings
            model.deleted_at = None
            model.updated_at = datetime.now(UTC)
        else:
            model = OrganizationModel(
                clerk_org_id=clerk_org_id,
                name=name,
                slug=slug,
                github_installation_id=github_installation_id,
                settings=settings or {},
            )
            self._session.add(model)

        await self._session.flush()
        return _to_entity(model)
