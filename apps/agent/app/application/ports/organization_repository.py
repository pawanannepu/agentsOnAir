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
        """Retrieve an active organization by its external Clerk organization ID."""
        ...

    async def get_by_clerk_id_including_deleted(
        self, clerk_org_id: str
    ) -> Organization | None:
        """Retrieve an organization by Clerk ID even if soft deleted, or None."""
        ...

    async def create_or_update(
        self,
        clerk_org_id: str,
        name: str,
        slug: str,
        github_installation_id: int | None = None,
        settings: dict | None = None,
    ) -> Organization:
        """Atomically upsert an active organization by Clerk ID."""
        ...

    async def create_or_update_if_active(
        self,
        clerk_org_id: str,
        name: str,
        slug: str,
    ) -> Organization | None:
        """Insert if absent or update only if active (deleted_at IS NULL)."""
        ...

    async def soft_delete_by_clerk_id(self, clerk_org_id: str) -> Organization | None:
        """Idempotently soft delete an active organization by Clerk ID."""
        ...

    async def update_settings(
        self,
        org_id: uuid.UUID,
        settings: dict,
    ) -> Organization:
        """Update settings JSONB for an active organization."""
        ...
