"""Repository port protocol for custom review rules and per-repo overrides."""

import uuid
from typing import Protocol

from app.domain.entities.review_rule import (
    EffectiveReviewRule,
    ReviewRule,
    ReviewRuleOverride,
)


class ReviewRulesRepository(Protocol):
    """Port interface for organization and repository review rules."""

    async def list_org_rules(
        self,
        org_id: uuid.UUID,
        page: int = 1,
        page_size: int = 50,
    ) -> tuple[list[ReviewRule], int]:
        """List non-deleted organization default rules (`repo_id IS NULL`)."""
        ...

    async def get_rule(self, org_id: uuid.UUID, rule_id: uuid.UUID) -> ReviewRule:
        """Fetch a non-deleted rule scoped to org_id."""
        ...

    async def create_org_rule(
        self,
        org_id: uuid.UUID,
        title: str,
        instruction: str,
        severity: str,
        category: str,
        path_globs: list[str],
        is_enabled: bool,
        created_by: str,
    ) -> ReviewRule:
        """Create an organization default rule while enforcing repo 25-rule caps."""
        ...

    async def create_repo_rule(
        self,
        org_id: uuid.UUID,
        repo_id: uuid.UUID,
        title: str,
        instruction: str,
        severity: str,
        category: str,
        path_globs: list[str],
        is_enabled: bool,
        created_by: str,
    ) -> ReviewRule:
        """Create a repository-specific rule under row lock enforcing 25-rule cap."""
        ...

    async def update_rule(
        self,
        org_id: uuid.UUID,
        rule_id: uuid.UUID,
        *,
        expected_repo_id: uuid.UUID | None = None,
        require_org_default: bool = False,
        title: str | None = None,
        instruction: str | None = None,
        severity: str | None = None,
        category: str | None = None,
        path_globs: list[str] | None = None,
        is_enabled: bool | None = None,
    ) -> ReviewRule:
        """Update rule fields under row lock enforcing active 25-rule cap."""
        ...

    async def soft_delete_rule(
        self,
        org_id: uuid.UUID,
        rule_id: uuid.UUID,
        *,
        expected_repo_id: uuid.UUID | None = None,
        require_org_default: bool = False,
    ) -> ReviewRule:
        """Soft-delete a review rule (`deleted_at = now()`)."""
        ...

    async def list_repo_rules_with_overrides(
        self,
        org_id: uuid.UUID,
        repo_id: uuid.UUID,
    ) -> list[EffectiveReviewRule]:
        """List merged org default rules (with overrides) plus repo-owned rules."""
        ...

    async def get_override(
        self,
        org_id: uuid.UUID,
        repo_id: uuid.UUID,
        rule_id: uuid.UUID,
    ) -> ReviewRuleOverride | None:
        """Fetch an existing per-repository override if present."""
        ...

    async def upsert_override(
        self,
        org_id: uuid.UUID,
        repo_id: uuid.UUID,
        rule_id: uuid.UUID,
        is_enabled: bool | None,
        severity_override: str | None,
        updated_by: str,
    ) -> tuple[ReviewRuleOverride | None, EffectiveReviewRule]:
        """Upsert or clear a per-repo override on an org default rule under row lock."""
        ...
