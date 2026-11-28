"""Review rule and override domain entities."""

import uuid
from dataclasses import dataclass, field
from datetime import datetime


@dataclass(slots=True)
class ReviewRule:
    """Organization default or repository-specific code review rule."""

    id: uuid.UUID
    org_id: uuid.UUID
    repo_id: uuid.UUID | None
    title: str
    instruction: str
    severity: str  # critical, major, minor, info
    category: str  # security, bug, performance, architecture, style
    path_globs: list[str] = field(default_factory=lambda: ["**/*"])
    is_enabled: bool = True
    created_by: str = "system"
    deleted_at: datetime | None = None
    created_at: datetime | None = None
    updated_at: datetime | None = None


@dataclass(slots=True)
class ReviewRuleOverride:
    """Per-repository override on an inherited organization default rule."""

    id: uuid.UUID
    org_id: uuid.UUID
    repo_id: uuid.UUID
    rule_id: uuid.UUID
    is_enabled: bool | None
    severity_override: str | None
    updated_by: str
    updated_at: datetime | None = None


@dataclass(slots=True)
class EffectiveReviewRule:
    """Merged view of a rule for a specific repository."""

    id: uuid.UUID
    org_id: uuid.UUID
    repo_id: uuid.UUID | None
    scope: str  # "org" | "repo"
    title: str
    instruction: str
    base_severity: str
    severity: str
    category: str
    path_globs: list[str]
    base_is_enabled: bool
    is_enabled: bool
    has_override: bool
    override_is_enabled: bool | None
    override_severity: str | None
    created_by: str
    created_at: datetime | None = None
    updated_at: datetime | None = None
