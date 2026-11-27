"""SQLAlchemy repository repository implementation."""

import uuid
from datetime import UTC, datetime

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.application.ports.repository_repository import RepositoryRepository
from app.domain.entities.repository import Repository
from app.domain.exceptions import ConflictError, NotFoundError
from app.infrastructure.db.models.repository import RepositoryModel


def _to_entity(model: RepositoryModel) -> Repository:
    return Repository(
        id=model.id,
        org_id=model.org_id,
        github_repo_id=model.github_repo_id,
        github_installation_id=model.github_installation_id,
        name=model.name,
        full_name=model.full_name,
        default_branch=model.default_branch,
        is_private=model.is_private,
        config=model.config or {},
        review_settings=getattr(model, "review_settings", None) or {},
        created_at=model.created_at,
        updated_at=model.updated_at,
        deleted_at=model.deleted_at,
    )


class SqlAlchemyRepositoryRepository(RepositoryRepository):
    """Async SQLAlchemy adapter for Repository persistence."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def create(
        self,
        org_id: uuid.UUID,
        github_repo_id: int,
        github_installation_id: int,
        name: str,
        full_name: str,
        default_branch: str = "main",
        is_private: bool = True,
        config: dict | None = None,
    ) -> Repository:
        # Check active repository in same org
        check_stmt = select(RepositoryModel).where(
            RepositoryModel.org_id == org_id,
            RepositoryModel.github_repo_id == github_repo_id,
            RepositoryModel.deleted_at.is_(None),
        )
        existing = (await self._session.execute(check_stmt)).scalar_one_or_none()
        if existing:
            raise ConflictError(
                f"Repository {github_repo_id} already exists in organization"
            )

        model = RepositoryModel(
            org_id=org_id,
            github_repo_id=github_repo_id,
            github_installation_id=github_installation_id,
            name=name,
            full_name=full_name,
            default_branch=default_branch,
            is_private=is_private,
            config=config or {},
        )
        self._session.add(model)
        await self._session.flush()
        return _to_entity(model)

    async def get_by_id(self, org_id: uuid.UUID, repo_id: uuid.UUID) -> Repository:
        stmt = select(RepositoryModel).where(
            RepositoryModel.org_id == org_id,
            RepositoryModel.id == repo_id,
            RepositoryModel.deleted_at.is_(None),
        )
        model = (await self._session.execute(stmt)).scalar_one_or_none()
        if not model:
            raise NotFoundError(f"Repository {repo_id} not found in organization")
        return _to_entity(model)

    async def get_by_github_id(
        self, org_id: uuid.UUID, github_repo_id: int
    ) -> Repository:
        stmt = select(RepositoryModel).where(
            RepositoryModel.org_id == org_id,
            RepositoryModel.github_repo_id == github_repo_id,
            RepositoryModel.deleted_at.is_(None),
        )
        model = (await self._session.execute(stmt)).scalar_one_or_none()
        if not model:
            raise NotFoundError(
                f"Repository with GitHub ID {github_repo_id} not found in organization"
            )
        return _to_entity(model)

    async def find_by_github_repo_id(self, github_repo_id: int) -> Repository | None:
        stmt = select(RepositoryModel).where(
            RepositoryModel.github_repo_id == github_repo_id,
            RepositoryModel.deleted_at.is_(None),
        )
        model = (await self._session.execute(stmt)).scalar_one_or_none()
        return _to_entity(model) if model else None

    async def list_by_org(
        self, org_id: uuid.UUID, page: int = 1, page_size: int = 20
    ) -> tuple[list[Repository], int]:
        count_stmt = select(func.count(RepositoryModel.id)).where(
            RepositoryModel.org_id == org_id,
            RepositoryModel.deleted_at.is_(None),
        )
        total = (await self._session.execute(count_stmt)).scalar_one()

        offset = max(0, (page - 1) * page_size)
        list_stmt = (
            select(RepositoryModel)
            .where(
                RepositoryModel.org_id == org_id,
                RepositoryModel.deleted_at.is_(None),
            )
            .order_by(RepositoryModel.created_at.desc())
            .offset(offset)
            .limit(page_size)
        )
        models = (await self._session.execute(list_stmt)).scalars().all()
        return [_to_entity(m) for m in models], total

    async def soft_delete(self, org_id: uuid.UUID, repo_id: uuid.UUID) -> None:
        stmt = select(RepositoryModel).where(
            RepositoryModel.org_id == org_id,
            RepositoryModel.id == repo_id,
            RepositoryModel.deleted_at.is_(None),
        )
        model = (await self._session.execute(stmt)).scalar_one_or_none()
        if not model:
            raise NotFoundError(f"Repository {repo_id} not found in organization")
        model.deleted_at = datetime.now(UTC)
        await self._session.flush()

    async def update_config(
        self, org_id: uuid.UUID, repo_id: uuid.UUID, config: dict
    ) -> Repository:
        stmt = select(RepositoryModel).where(
            RepositoryModel.org_id == org_id,
            RepositoryModel.id == repo_id,
            RepositoryModel.deleted_at.is_(None),
        )
        model = (await self._session.execute(stmt)).scalar_one_or_none()
        if not model:
            raise NotFoundError(f"Repository {repo_id} not found in organization")
        model.config = config
        model.updated_at = datetime.now(UTC)
        await self._session.flush()
        return _to_entity(model)
