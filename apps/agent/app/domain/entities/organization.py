"""Organization domain entity."""

import uuid
from dataclasses import dataclass, field
from datetime import datetime


@dataclass(slots=True)
class Organization:
    """Core tenant organization entity."""

    id: uuid.UUID
    clerk_org_id: str
    name: str
    slug: str
    github_installation_id: int | None = None
    settings: dict = field(default_factory=dict)
    created_at: datetime | None = None
    updated_at: datetime | None = None
    deleted_at: datetime | None = None
