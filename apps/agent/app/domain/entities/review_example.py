"""Review example pull request domain entity."""

import uuid
from dataclasses import dataclass, field
from datetime import datetime


@dataclass(slots=True)
class ReviewExample:
    """Curated good or bad pull request example attached to a repository."""

    id: uuid.UUID
    org_id: uuid.UUID
    repo_id: uuid.UUID
    pr_number: int
    pr_url: str
    pr_title: str
    classification: str  # good, bad
    guidance_note: str
    modified_files: list[str] = field(default_factory=list)
    cached_diff_summary: str | None = None
    cached_token_count: int = 0
    cached_at: datetime | None = None
    created_by: str = "system"
    created_at: datetime | None = None
    updated_at: datetime | None = None
