"""Organization repository port protocol."""

import uuid
from typing import Protocol

from app.domain.entities.organization import Organization


class OrganizationRepository(Protocol):
    """Repository port for organization management."""

    async def get_by_id(self, org_id: uuid.UUID) -> Organization:
        """Retrieve an organization by internal UUID."""
        ...

    async def get_by_clerk_id(self, clerk_org_id: str) -> Organization:
        """Retrieve an organization by its external Clerk organization ID."""
        ...

    async def create_or_update(
        self,
        clerk_org_id: str,
        name: str,
        slug: str,
        github_installation_id: int | None = None,
        settings: dict | None = None,
    ) -> Organization:
        """Create a new organization or update an existing one by Clerk ID."""
        ...
