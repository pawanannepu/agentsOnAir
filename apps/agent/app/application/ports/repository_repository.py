"""Repository repository port protocol."""

import uuid
from typing import Protocol

from app.domain.entities.repository import Repository


class RepositoryRepository(Protocol):
    """Repository port for synchronized GitHub repositories."""

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
        """Link a new GitHub repository to an organization."""
        ...

    async def get_by_id(self, org_id: uuid.UUID, repo_id: uuid.UUID) -> Repository:
        """Retrieve a repository scoped to the tenant organization."""
        ...

    async def get_by_github_id(
        self, org_id: uuid.UUID, github_repo_id: int
    ) -> Repository:
        """Retrieve an active repository by GitHub repository ID."""
        ...

    async def find_by_github_repo_id(self, github_repo_id: int) -> Repository | None:
        """Retrieve an active repository across orgs by GitHub ID."""
        ...

    async def list_by_org(
        self, org_id: uuid.UUID, page: int = 1, page_size: int = 20
    ) -> tuple[list[Repository], int]:
        """List active repositories for an organization with pagination."""
        ...

    async def soft_delete(self, org_id: uuid.UUID, repo_id: uuid.UUID) -> None:
        """Soft delete a repository by setting deleted_at."""
        ...
