"""Repository listing and per-repository guardrail override API endpoints."""

import uuid
from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.encoders import jsonable_encoder
from pydantic import BaseModel
from pydantic import ValidationError as PydanticValidationError
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.dependencies.auth import (
    get_current_clerk_user,
    require_org_admin,
    resolve_caller_org,
)
from app.application.schemas.guardrails import (
    GuardrailPolicy,
    GuardrailPolicyOverride,
    apply_guardrail_overrides,
)
from app.core.clerk_auth import ClerkUserContext
from app.domain.entities.organization import Organization
from app.domain.exceptions import NotFoundError
from app.domain.services.policy_evaluator import PolicyEvaluator
from app.infrastructure.db.repositories.audit_log_repository import (
    SqlAlchemyAuditLogRepository,
)
from app.infrastructure.db.repositories.repository_repository import (
    SqlAlchemyRepositoryRepository,
)
from app.infrastructure.db.session import get_db

router = APIRouter()


class RepositoryListItem(BaseModel):
    id: uuid.UUID
    org_id: uuid.UUID
    github_repo_id: int
    name: str
    full_name: str
    default_branch: str
    is_private: bool
    config: dict[str, Any]
    effective_policy: GuardrailPolicy


class RepositoryListResponse(BaseModel):
    items: list[RepositoryListItem]
    total: int
    limit: int
    offset: int


class RepositoryGuardrailsResponse(BaseModel):
    repo_id: uuid.UUID
    org_defaults: GuardrailPolicy
    repo_overrides: dict[str, Any]
    effective_policy: GuardrailPolicy


class UpdateRepositoryGuardrailsResponse(BaseModel):
    repo_id: uuid.UUID
    repo_overrides: dict[str, Any]
    effective_policy: GuardrailPolicy


@router.get("", response_model=RepositoryListResponse)
async def list_repositories(
    caller: Annotated[ClerkUserContext, Depends(get_current_clerk_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
    limit: Annotated[int, Query(ge=1, le=100)] = 50,
    offset: Annotated[int, Query(ge=0)] = 0,
):
    """List connected repositories for the org with effective guardrails."""
    org = await resolve_caller_org(caller, db)
    repo_repo = SqlAlchemyRepositoryRepository(db)
    page = (offset // limit) + 1
    repos, total = await repo_repo.list_by_org(org.id, page=page, page_size=limit)

    items = [
        RepositoryListItem(
            id=r.id,
            org_id=r.org_id,
            github_repo_id=r.github_repo_id,
            name=r.name,
            full_name=r.full_name,
            default_branch=r.default_branch,
            is_private=r.is_private,
            config=r.config,
            effective_policy=GuardrailPolicy(
                **PolicyEvaluator.merge_policy(org.settings, r.config).to_dict()
            ),
        )
        for r in repos
    ]
    return RepositoryListResponse(
        items=items,
        total=total,
        limit=limit,
        offset=offset,
    )


@router.get("/{repo_id}/guardrails", response_model=RepositoryGuardrailsResponse)
async def get_repository_guardrails(
    repo_id: uuid.UUID,
    caller: Annotated[ClerkUserContext, Depends(get_current_clerk_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
):
    """Read org defaults, repo overrides, and merged effective guardrails."""
    org = await resolve_caller_org(caller, db)
    repo_repo = SqlAlchemyRepositoryRepository(db)
    try:
        repo = await repo_repo.get_by_id(org.id, repo_id)
    except NotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc

    org_defaults = PolicyEvaluator.merge_policy(org.settings, None)
    effective = PolicyEvaluator.merge_policy(org.settings, repo.config)
    overrides = dict(repo.config.get("guardrails") or {})

    return RepositoryGuardrailsResponse(
        repo_id=repo.id,
        org_defaults=GuardrailPolicy(**org_defaults.to_dict()),
        repo_overrides=overrides,
        effective_policy=GuardrailPolicy(**effective.to_dict()),
    )


@router.patch(
    "/{repo_id}/guardrails", response_model=UpdateRepositoryGuardrailsResponse
)
async def update_repository_guardrails(
    repo_id: uuid.UUID,
    payload: GuardrailPolicyOverride,
    auth_ctx: Annotated[
        tuple[ClerkUserContext, Organization], Depends(require_org_admin)
    ],
    db: Annotated[AsyncSession, Depends(get_db)],
):
    """Update repository guardrail overrides (org:admin only; null removes override)."""
    caller, org = auth_ctx
    repo_repo = SqlAlchemyRepositoryRepository(db)
    try:
        repo = await repo_repo.get_by_id(org.id, repo_id)
    except NotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc

    existing_config = dict(repo.config or {})
    existing_overrides = dict(existing_config.get("guardrails") or {})
    next_overrides = apply_guardrail_overrides(existing_overrides, payload)

    next_config = dict(existing_config)
    next_config["guardrails"] = next_overrides

    # Validate merged policy invariants (e.g. protected_branch_guard consistency)
    merged_effective = PolicyEvaluator.merge_policy(org.settings, next_config)
    try:
        validated_effective = GuardrailPolicy(**merged_effective.to_dict())
    except PydanticValidationError as exc:
        raise HTTPException(
            status_code=422, detail=jsonable_encoder(exc.errors())
        ) from exc

    updated_repo = await repo_repo.update_config(org.id, repo.id, next_config)
    audit_repo = SqlAlchemyAuditLogRepository(db)
    await audit_repo.record_event(
        org_id=org.id,
        actor_type="user",
        actor_id=caller.user_id,
        action="repository.guardrails_updated",
        target_type="repository",
        target_id=repo.id,
        payload_before=existing_overrides,
        payload_after=updated_repo.config.get("guardrails") or {},
    )
    await db.commit()
    return UpdateRepositoryGuardrailsResponse(
        repo_id=updated_repo.id,
        repo_overrides=dict(updated_repo.config.get("guardrails") or {}),
        effective_policy=validated_effective,
    )
