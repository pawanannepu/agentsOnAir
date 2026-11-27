"""Pydantic schemas and validation for org and repository guardrails."""

import re
from typing import Any, Literal

from pydantic import BaseModel, Field, field_validator, model_validator

from app.domain.services.policy_evaluator import (
    DEFAULT_PROTECTED_BRANCHES,
    RISK_CATEGORIES,
)

RiskCategoryLiteral = Literal[
    "destructive_shell",
    "external_network",
    "sensitive_path_edit",
    "force_git_op",
    "large_diff",
]
NetworkEgressModeLiteral = Literal["off_after_install", "allowlist", "unrestricted"]

_DOMAIN_PATTERN = re.compile(
    r"^(\*\.)?[a-z0-9]([a-z0-9-]{0,61}[a-z0-9])?"
    r"(\.[a-z0-9]([a-z0-9-]{0,61}[a-z0-9])?)+$"
)


def _validate_protected_branches_list(branches: list[str]) -> list[str]:
    cleaned = [b.strip() for b in branches if isinstance(b, str) and b.strip()]
    if not cleaned:
        raise ValueError(
            "protected_branches must contain at least one non-empty pattern"
        )
    if len(cleaned) != len(branches):
        raise ValueError("protected_branches cannot contain empty entries")
    return cleaned


def _validate_egress_domains_list(domains: list[str]) -> list[str]:
    validated: list[str] = []
    for raw in domains:
        domain = raw.strip()
        if not domain or domain != domain.lower():
            raise ValueError(
                f"Invalid egress domain '{raw}': must be lowercase hostname "
                "with optional leading '*.'"
            )
        if not _DOMAIN_PATTERN.fullmatch(domain):
            raise ValueError(
                f"Invalid egress domain '{raw}': expected lowercase hostname "
                "with optional leading '*.'"
            )
        validated.append(domain)
    return validated


class GuardrailPolicy(BaseModel):
    """Typed organization-level guardrail and budget policy."""

    protected_branches: list[str] = Field(
        default_factory=lambda: list(DEFAULT_PROTECTED_BRANCHES)
    )
    protected_branch_guard: bool = True
    require_approval_for: list[RiskCategoryLiteral] = Field(
        default_factory=lambda: list(RISK_CATEGORIES)  # type: ignore[arg-type]
    )
    max_task_cost_cents: int = Field(default=500, ge=1)
    max_monthly_org_cost_cents: int = Field(default=10000, ge=1)
    timeout_minutes: int = Field(default=10, ge=1, le=60)
    max_cycles: int = Field(default=3, ge=1, le=10)
    network_egress_mode: NetworkEgressModeLiteral = "off_after_install"
    allowed_egress_domains: list[str] = Field(default_factory=list)
    large_diff_lines_threshold: int = Field(default=500, ge=1)

    @field_validator("protected_branches")
    @classmethod
    def check_protected_branches(cls, value: list[str]) -> list[str]:
        return _validate_protected_branches_list(value)

    @field_validator("allowed_egress_domains")
    @classmethod
    def check_allowed_egress_domains(cls, value: list[str]) -> list[str]:
        return _validate_egress_domains_list(value)

    @model_validator(mode="after")
    def check_branch_guard_consistency(self) -> "GuardrailPolicy":
        if self.protected_branch_guard is False and self.protected_branches:
            raise ValueError(
                "protected_branch_guard cannot be false while "
                "protected_branches is non-empty"
            )
        return self


class GuardrailPolicyOverride(BaseModel):
    """Partial repository guardrail override (null removes override key)."""

    protected_branches: list[str] | None = None
    protected_branch_guard: bool | None = None
    require_approval_for: list[RiskCategoryLiteral] | None = None
    max_task_cost_cents: int | None = Field(default=None, ge=1)
    max_monthly_org_cost_cents: int | None = Field(default=None, ge=1)
    timeout_minutes: int | None = Field(default=None, ge=1, le=60)
    max_cycles: int | None = Field(default=None, ge=1, le=10)
    network_egress_mode: NetworkEgressModeLiteral | None = None
    allowed_egress_domains: list[str] | None = None
    large_diff_lines_threshold: int | None = Field(default=None, ge=1)

    @field_validator("protected_branches")
    @classmethod
    def check_protected_branches(cls, value: list[str] | None) -> list[str] | None:
        if value is None:
            return None
        return _validate_protected_branches_list(value)

    @field_validator("allowed_egress_domains")
    @classmethod
    def check_allowed_egress_domains(cls, value: list[str] | None) -> list[str] | None:
        if value is None:
            return None
        return _validate_egress_domains_list(value)

    @model_validator(mode="after")
    def check_branch_guard_consistency(self) -> "GuardrailPolicyOverride":
        if (
            self.protected_branch_guard is False
            and self.protected_branches is not None
            and len(self.protected_branches) > 0
        ):
            raise ValueError(
                "protected_branch_guard cannot be false while "
                "protected_branches is non-empty"
            )
        return self


def apply_guardrail_overrides(
    existing_overrides: dict[str, Any],
    patch: GuardrailPolicyOverride,
) -> dict[str, Any]:
    """Apply partial override patch, removing keys explicitly sent as null."""
    updated = dict(existing_overrides)
    for field_name in patch.model_fields_set:
        value = getattr(patch, field_name)
        if value is None:
            updated.pop(field_name, None)
        else:
            updated[field_name] = value
    return updated
