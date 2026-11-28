"""Pydantic request and response schemas for review rules, examples, and feedback."""

import uuid
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field, field_validator

SeverityLiteral = Literal["critical", "major", "minor", "info"]
CategoryLiteral = Literal["security", "bug", "performance", "architecture", "style"]
ClassificationLiteral = Literal["good", "bad"]
FeedbackTypeLiteral = Literal["accepted", "dismissed"]
PreferenceStatusLiteral = Literal["active", "dampened", "suppressed"]


class ReviewRuleCreateRequest(BaseModel):
    """Create payload for an organization default or repository review rule."""

    title: str = Field(min_length=1, max_length=200)
    instruction: str = Field(min_length=1)
    severity: SeverityLiteral
    category: CategoryLiteral
    path_globs: list[str] = Field(default_factory=lambda: ["**/*"])
    is_enabled: bool = True

    @field_validator("path_globs")
    @classmethod
    def _validate_path_globs(cls, v: list[str]) -> list[str]:
        cleaned = [g.strip() for g in v if isinstance(g, str) and g.strip()]
        if not cleaned:
            raise ValueError("path_globs must contain at least one non-empty glob")
        return cleaned


class ReviewRuleUpdateRequest(BaseModel):
    """Partial update payload for a review rule."""

    title: str | None = Field(default=None, min_length=1, max_length=200)
    instruction: str | None = Field(default=None, min_length=1)
    severity: SeverityLiteral | None = None
    category: CategoryLiteral | None = None
    path_globs: list[str] | None = None
    is_enabled: bool | None = None

    @field_validator("path_globs")
    @classmethod
    def _validate_path_globs(cls, v: list[str] | None) -> list[str] | None:
        if v is None:
            return None
        cleaned = [g.strip() for g in v if isinstance(g, str) and g.strip()]
        if not cleaned:
            raise ValueError("path_globs must contain at least one non-empty glob")
        return cleaned


class ReviewRuleResponse(BaseModel):
    """Serialized review rule."""

    id: uuid.UUID
    org_id: uuid.UUID
    repo_id: uuid.UUID | None
    title: str
    instruction: str
    severity: str
    category: str
    path_globs: list[str]
    is_enabled: bool
    created_by: str
    created_at: datetime | None = None
    updated_at: datetime | None = None


class EffectiveReviewRuleResponse(BaseModel):
    """Serialized merged rule for a repository with override metadata."""

    id: uuid.UUID
    org_id: uuid.UUID
    repo_id: uuid.UUID | None
    scope: Literal["org", "repo"]
    title: str
    instruction: str
    base_severity: str
    severity: str
    category: str
    path_globs: list[str]
    base_is_enabled: bool
    is_enabled: bool
    has_override: bool
    override_is_enabled: bool | None = None
    override_severity: str | None = None
    created_by: str
    created_at: datetime | None = None
    updated_at: datetime | None = None


class ReviewRuleOverridePutRequest(BaseModel):
    """Put payload to set or clear a per-repository override on an org rule."""

    is_enabled: bool | None = None
    severity_override: SeverityLiteral | None = None


class ReviewRuleOverrideResponse(BaseModel):
    """Result of updating or clearing a per-repository rule override."""

    override_id: uuid.UUID | None = None
    cleared: bool
    effective_rule: EffectiveReviewRuleResponse


class ReviewExampleCreateRequest(BaseModel):
    """Create payload attaching a curated PR example to a repository."""

    pr_number: int | None = Field(default=None, ge=1)
    pr_url: str | None = None
    classification: ClassificationLiteral
    guidance_note: str = Field(min_length=1)


class ReviewExampleResponse(BaseModel):
    """Serialized curated PR example."""

    id: uuid.UUID
    org_id: uuid.UUID
    repo_id: uuid.UUID
    pr_number: int
    pr_url: str
    pr_title: str
    classification: str
    guidance_note: str
    modified_files: list[str]
    cached_diff_summary: str | None = None
    cached_token_count: int
    cached_at: datetime | None = None
    created_by: str
    created_at: datetime | None = None
    updated_at: datetime | None = None


class LearnedPreferenceResponse(BaseModel):
    """Serialized repository learned preference."""

    id: uuid.UUID
    org_id: uuid.UUID
    repo_id: uuid.UUID
    rule_id: uuid.UUID | None = None
    pattern_key: str
    instruction: str
    dismiss_count: int
    accept_count: int
    consecutive_dismissals: int
    status: str
    last_feedback_at: datetime | None = None
    created_at: datetime | None = None
    updated_at: datetime | None = None


class LearnedPreferenceUpdateRequest(BaseModel):
    """Admin update payload for a learned preference."""

    status: PreferenceStatusLiteral
    instruction: str | None = None


class FindingFeedbackRequest(BaseModel):
    """Developer feedback payload for a PR review finding."""

    feedback_type: FeedbackTypeLiteral
    reason: str | None = None
    remember_preference: bool = False


class FindingFeedbackStateResponse(BaseModel):
    """Updated finding feedback state summary."""

    id: uuid.UUID
    rule_id: uuid.UUID | None = None
    feedback_state: str
    status: str


class FindingFeedbackResponse(BaseModel):
    """Response returned after submitting feedback on a finding."""

    finding: FindingFeedbackStateResponse
    learned_preference: LearnedPreferenceResponse | None = None
    applied: bool
    deduplicated: bool = False
