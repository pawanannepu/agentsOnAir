"""Organization synchronization and settings API endpoints."""

from typing import Annotated, Literal

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.dependencies.auth import (
    forbidden_error,
    get_current_clerk_user,
    require_org_admin,
    sync_organization_isolated,
)
from app.core.clerk_auth import ClerkUserContext
from app.domain.entities.organization import Organization
from app.infrastructure.db.repositories.audit_log_repository import (
    SqlAlchemyAuditLogRepository,
)
from app.infrastructure.db.repositories.organization_repository import (
    SqlAlchemyOrganizationRepository,
)
from app.infrastructure.db.session import get_db

router = APIRouter()


class OrganizationSyncResponse(BaseModel):
    id: str
    clerk_org_id: str
    name: str
    slug: str


class UpdateOrganizationSettingsRequest(BaseModel):
    sandbox_provider: Literal["e2b", "docker"] | None = None
    timeout_minutes: int | None = Field(default=None, ge=1, le=60)
    protected_branch_guard: bool | None = None


class OrganizationSettingsResponse(BaseModel):
    id: str
    settings: dict


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
    """Update workspace settings for the active organization (org:admin only)."""
    caller, org = auth_ctx
    updates = payload.model_dump(exclude_none=True)
    merged_settings = {**org.settings, **updates}

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
