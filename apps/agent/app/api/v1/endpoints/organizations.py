"""Organization synchronization, guardrails, settings, and usage API endpoints."""

import re
from typing import Annotated, Any, Literal

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.encoders import jsonable_encoder
from pydantic import BaseModel, Field
from pydantic import ValidationError as PydanticValidationError
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.dependencies.auth import (
    forbidden_error,
    get_current_clerk_user,
    require_org_admin,
    resolve_caller_org,
    sync_organization_isolated,
)
from app.application.schemas.guardrails import (
    GuardrailPolicy,
    NetworkEgressModeLiteral,
    RiskCategoryLiteral,
)
from app.application.services.usage_tracker import UsageTracker
from app.core.clerk_auth import ClerkUserContext
from app.domain.entities.organization import Organization
from app.domain.services.policy_evaluator import PolicyEvaluator
from app.infrastructure.db.repositories.audit_log_repository import (
    SqlAlchemyAuditLogRepository,
)
from app.infrastructure.db.repositories.organization_repository import (
    SqlAlchemyOrganizationRepository,
)
from app.infrastructure.db.repositories.usage_repository import (
    SqlAlchemyUsageRepository,
)
from app.infrastructure.db.session import get_db

router = APIRouter()

_MONTH_RE = re.compile(r"^\d{4}-(0[1-9]|1[0-2])$")


class OrganizationSyncResponse(BaseModel):
    id: str
    clerk_org_id: str
    name: str
    slug: str


class UpdateOrganizationSettingsRequest(BaseModel):
    sandbox_provider: Literal["e2b", "docker"] | None = None
    timeout_minutes: int | None = Field(default=None, ge=1, le=60)
    protected_branch_guard: bool | None = None
    protected_branches: list[str] | None = None
    require_approval_for: list[RiskCategoryLiteral] | None = None
    max_task_cost_cents: int | None = Field(default=None, ge=1)
    max_monthly_org_cost_cents: int | None = Field(default=None, ge=1)
    max_cycles: int | None = Field(default=None, ge=1, le=10)
    network_egress_mode: NetworkEgressModeLiteral | None = None
    allowed_egress_domains: list[str] | None = None
    large_diff_lines_threshold: int | None = Field(default=None, ge=1)


class OrganizationSettingsResponse(BaseModel):
    id: str
    settings: dict


class OrganizationUsageResponse(BaseModel):
    billing_month: str
    total_tokens: int
    total_cost_cents: int
    max_monthly_org_cost_cents: int
    remaining_cents: int


@router.post("/sync", response_model=OrganizationSyncResponse)
async def sync_active_organization(
    caller: Annotated[ClerkUserContext, Depends(get_current_clerk_user)],
):
    """Explicitly sync the caller's active Clerk organization into PostgreSQL."""
    if not caller.clerk_org_id:
        raise forbidden_error(
            "org_missing",
            "Active organization claim is required",
        )

    org = await sync_organization_isolated(
        clerk_org_id=caller.clerk_org_id,
        actor_user_id=caller.user_id,
    )
    return OrganizationSyncResponse(
        id=str(org.id),
        clerk_org_id=org.clerk_org_id,
        name=org.name,
        slug=org.slug,
    )


@router.get("/guardrails", response_model=GuardrailPolicy)
async def get_organization_guardrails(
    caller: Annotated[ClerkUserContext, Depends(get_current_clerk_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
):
    """Read effective organization guardrail and budget defaults (any org member)."""
    org = await resolve_caller_org(caller, db)
    effective = PolicyEvaluator.merge_policy(org.settings, None)
    return GuardrailPolicy(**effective.to_dict())


@router.get("/usage", response_model=OrganizationUsageResponse)
async def get_organization_usage(
    caller: Annotated[ClerkUserContext, Depends(get_current_clerk_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
    month: Annotated[str | None, Query()] = None,
):
    """Read organization monthly token and integer-cent spend vs cap."""
    org = await resolve_caller_org(caller, db)
    billing_month = month or UsageTracker.current_billing_month()
    if not _MONTH_RE.fullmatch(billing_month):
        raise HTTPException(
            status_code=422,
            detail="Invalid month format; expected YYYY-MM",
        )

    usage_repo = SqlAlchemyUsageRepository(session=db)
    monthly = await usage_repo.get_org_monthly_usage(org.id, billing_month)
    effective = PolicyEvaluator.merge_policy(org.settings, None)
    remaining = max(0, effective.max_monthly_org_cost_cents - monthly.total_cost_cents)
    return OrganizationUsageResponse(
        billing_month=billing_month,
        total_tokens=monthly.total_tokens,
        total_cost_cents=monthly.total_cost_cents,
        max_monthly_org_cost_cents=effective.max_monthly_org_cost_cents,
        remaining_cents=remaining,
    )


@router.get("/settings", response_model=OrganizationSettingsResponse)
async def get_organization_settings(
    auth_ctx: Annotated[
        tuple[ClerkUserContext, Organization], Depends(require_org_admin)
    ],
):
    """Read workspace settings for the active organization (org:admin only)."""
    _caller, org = auth_ctx
    return OrganizationSettingsResponse(id=str(org.id), settings=org.settings)


@router.patch("/settings", response_model=OrganizationSettingsResponse)
async def update_organization_settings(
    payload: UpdateOrganizationSettingsRequest,
    auth_ctx: Annotated[
        tuple[ClerkUserContext, Organization], Depends(require_org_admin)
    ],
    db: Annotated[AsyncSession, Depends(get_db)],
):
    """Update workspace and guardrail settings (org:admin only)."""
    caller, org = auth_ctx
    updates = payload.model_dump(exclude_none=True)
    merged_settings: dict[str, Any] = {**org.settings, **updates}

    # Validate merged guardrail fields against strict Pydantic bounds and invariants
    policy_keys = set(GuardrailPolicy.model_fields.keys())
    policy_input = {k: v for k, v in merged_settings.items() if k in policy_keys}
    try:
        validated_policy = GuardrailPolicy(**policy_input)
    except PydanticValidationError as exc:
        raise HTTPException(
            status_code=422, detail=jsonable_encoder(exc.errors())
        ) from exc

    merged_settings.update(validated_policy.model_dump())

    org_repo = SqlAlchemyOrganizationRepository(db)
    audit_repo = SqlAlchemyAuditLogRepository(db)

    updated_org = await org_repo.update_settings(org.id, merged_settings)
    await audit_repo.record_event(
        org_id=org.id,
        actor_type="user",
        actor_id=caller.user_id,
        action="organization.settings_updated",
        target_type="organization",
        target_id=org.id,
        payload_before=org.settings,
        payload_after=updated_org.settings,
    )
    await db.commit()
    return OrganizationSettingsResponse(
        id=str(updated_org.id),
        settings=updated_org.settings,
    )
