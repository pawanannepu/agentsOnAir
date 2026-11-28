"""Repository port protocol for curated repository example pull requests."""

import uuid
from datetime import datetime
from typing import Protocol

from app.domain.entities.review_example import ReviewExample


class ReviewExamplesRepository(Protocol):
    """Port interface for repository curated example PRs."""

    async def list_by_repo(
        self, org_id: uuid.UUID, repo_id: uuid.UUID
    ) -> list[ReviewExample]:
        """List all example PRs attached to a repository."""
        ...

    async def get_by_id(
        self, org_id: uuid.UUID, repo_id: uuid.UUID, example_id: uuid.UUID
    ) -> ReviewExample:
        """Fetch an example PR by ID within org and repository scope."""
        ...

    async def create_example(
        self,
        org_id: uuid.UUID,
        repo_id: uuid.UUID,
        pr_number: int,
        pr_url: str,
        pr_title: str,
        classification: str,
        guidance_note: str,
        modified_files: list[str],
        cached_diff_summary: str | None,
        cached_token_count: int,
        cached_at: datetime | None,
        created_by: str,
    ) -> ReviewExample:
        """Create a curated example PR under repo lock enforcing max 5 cap."""
        ...

    async def update_cache(
        self,
        org_id: uuid.UUID,
        repo_id: uuid.UUID,
        example_id: uuid.UUID,
        pr_url: str,
        pr_title: str,
        modified_files: list[str],
        cached_diff_summary: str | None,
        cached_token_count: int,
        cached_at: datetime,
    ) -> ReviewExample:
        """Refresh cached metadata, modified files, and diff summary for an example."""
        ...

    async def delete_example(
        self, org_id: uuid.UUID, repo_id: uuid.UUID, example_id: uuid.UUID
    ) -> ReviewExample:
        """Delete an example PR from a repository and return deleted entity."""
        ...
