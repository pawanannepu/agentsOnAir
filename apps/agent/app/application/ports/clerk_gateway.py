"""Clerk Backend API organization gateway port."""

from dataclasses import dataclass
from typing import Protocol


@dataclass(frozen=True, slots=True)
class ClerkOrganizationInfo:
    """Organization metadata retrieved from the Clerk Backend API."""

    clerk_org_id: str
    name: str
    slug: str


class ClerkOrganizationGateway(Protocol):
    """Port for fetching organization metadata from Clerk Backend API."""

    async def get_organization(self, clerk_org_id: str) -> ClerkOrganizationInfo:
        """Fetch an organization by its Clerk ID (`org_...`)."""
        ...
