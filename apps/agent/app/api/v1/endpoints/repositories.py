"""Repository listing and per-repository guardrail override API endpoints."""

import uuid
from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException, Query, Response
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
from app.application.schemas.review_rules import (
    EffectiveReviewRuleResponse,
    LearnedPreferenceResponse,
    LearnedPreferenceUpdateRequest,
    ReviewExampleCreateRequest,
    ReviewExampleResponse,
    ReviewRuleCreateRequest,
    ReviewRuleOverridePutRequest,
    ReviewRuleOverrideResponse,
    ReviewRuleResponse,
    ReviewRuleUpdateRequest,
)
from app.application.use_cases.review_examples import ReviewExamplesUseCase
from app.application.use_cases.review_feedback import ReviewFeedbackUseCase
from app.application.use_cases.review_rules import ReviewRulesUseCase
from app.core.clerk_auth import ClerkUserContext
from app.core.config import settings
from app.domain.entities.organization import Organization
from app.domain.exceptions import ConflictError, NotFoundError, ValidationError
from app.domain.services.policy_evaluator import PolicyEvaluator
from app.infrastructure.db.repositories.audit_log_repository import (
    SqlAlchemyAuditLogRepository,
)
from app.infrastructure.db.repositories.repository_repository import (
    SqlAlchemyRepositoryRepository,
)
from app.infrastructure.db.repositories.review_examples_repository import (
    SqlAlchemyReviewExamplesRepository,
)
from app.infrastructure.db.repositories.review_feedback_repository import (
    SqlAlchemyReviewFeedbackRepository,
)
from app.infrastructure.db.repositories.review_rules_repository import (
    SqlAlchemyReviewRulesRepository,
)
from app.infrastructure.db.session import get_db
from app.infrastructure.github.github_service import GitHubService

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


def _to_rule_response(rule) -> ReviewRuleResponse:
    return ReviewRuleResponse(
        id=rule.id,
        org_id=rule.org_id,
        repo_id=rule.repo_id,
        title=rule.title,
        instruction=rule.instruction,
        severity=rule.severity,
        category=rule.category,
        path_globs=rule.path_globs,
        is_enabled=rule.is_enabled,
        created_by=rule.created_by,
        created_at=rule.created_at,
        updated_at=rule.updated_at,
    )


def _to_effective_rule_response(rule) -> EffectiveReviewRuleResponse:
    return EffectiveReviewRuleResponse(
        id=rule.id,
        org_id=rule.org_id,
        repo_id=rule.repo_id,
        scope="org" if rule.scope == "org" else "repo",
        title=rule.title,
        instruction=rule.instruction,
        base_severity=rule.base_severity,
        severity=rule.severity,
        category=rule.category,
        path_globs=rule.path_globs,
        base_is_enabled=rule.base_is_enabled,
        is_enabled=rule.is_enabled,
        has_override=rule.has_override,
        override_is_enabled=rule.override_is_enabled,
        override_severity=rule.override_severity,
        created_by=rule.created_by,
        created_at=rule.created_at,
        updated_at=rule.updated_at,
    )


def _to_example_response(ex) -> ReviewExampleResponse:
    return ReviewExampleResponse(
        id=ex.id,
        org_id=ex.org_id,
        repo_id=ex.repo_id,
        pr_number=ex.pr_number,
        pr_url=ex.pr_url,
        pr_title=ex.pr_title,
        classification=ex.classification,
        guidance_note=ex.guidance_note,
        modified_files=ex.modified_files,
        cached_diff_summary=ex.cached_diff_summary,
        cached_token_count=ex.cached_token_count,
        cached_at=ex.cached_at,
        created_by=ex.created_by,
        created_at=ex.created_at,
        updated_at=ex.updated_at,
    )


def _to_pref_response(pref) -> LearnedPreferenceResponse:
    return LearnedPreferenceResponse(
        id=pref.id,
        org_id=pref.org_id,
        repo_id=pref.repo_id,
        rule_id=pref.rule_id,
        pattern_key=pref.pattern_key,
        instruction=pref.instruction,
        dismiss_count=pref.dismiss_count,
        accept_count=pref.accept_count,
        consecutive_dismissals=pref.consecutive_dismissals,
        status=pref.status,
        last_feedback_at=pref.last_feedback_at,
        created_at=pref.created_at,
        updated_at=pref.updated_at,
    )


@router.get("/{repo_id}/review-rules")
async def list_repository_review_rules(
    repo_id: uuid.UUID,
    caller: Annotated[ClerkUserContext, Depends(get_current_clerk_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
):
    """List merged org default rules (with overrides) plus repo-specific rules."""
    org = await resolve_caller_org(caller, db)
    use_case = ReviewRulesUseCase(
        rules_repo=SqlAlchemyReviewRulesRepository(db),
        repository_repo=SqlAlchemyRepositoryRepository(db),
        audit_log_repo=SqlAlchemyAuditLogRepository(db),
    )
    try:
        merged = await use_case.list_repo_rules(org.id, repo_id)
    except NotFoundError as exc:
        raise HTTPException(status_code=404, detail=exc.message) from exc

    active_count = sum(1 for r in merged if r.is_enabled)
    return {
        "items": [_to_effective_rule_response(r) for r in merged],
        "active_count": active_count,
        "max_active": 25,
    }


@router.post(
    "/{repo_id}/review-rules",
    response_model=ReviewRuleResponse,
    status_code=201,
)
async def create_repository_review_rule(
    repo_id: uuid.UUID,
    payload: ReviewRuleCreateRequest,
    auth_ctx: Annotated[
        tuple[ClerkUserContext, Organization], Depends(require_org_admin)
    ],
    db: Annotated[AsyncSession, Depends(get_db)],
):
    """Create a repository-specific review rule (org:admin only)."""
    caller, org = auth_ctx
    use_case = ReviewRulesUseCase(
        rules_repo=SqlAlchemyReviewRulesRepository(db),
        repository_repo=SqlAlchemyRepositoryRepository(db),
        audit_log_repo=SqlAlchemyAuditLogRepository(db),
    )
    try:
        created = await use_case.create_repo_rule(
            org_id=org.id,
            repo_id=repo_id,
            actor_id=caller.user_id,
            title=payload.title,
            instruction=payload.instruction,
            severity=payload.severity,
            category=payload.category,
            path_globs=payload.path_globs,
            is_enabled=payload.is_enabled,
        )
    except NotFoundError as exc:
        raise HTTPException(status_code=404, detail=exc.message) from exc
    except ValidationError as exc:
        raise HTTPException(status_code=422, detail=exc.message) from exc

    await db.commit()
    return _to_rule_response(created)


@router.patch(
    "/{repo_id}/review-rules/{rule_id}",
    response_model=ReviewRuleResponse,
)
async def update_repository_review_rule(
    repo_id: uuid.UUID,
    rule_id: uuid.UUID,
    payload: ReviewRuleUpdateRequest,
    auth_ctx: Annotated[
        tuple[ClerkUserContext, Organization], Depends(require_org_admin)
    ],
    db: Annotated[AsyncSession, Depends(get_db)],
):
    """Update a repository-specific review rule (org:admin only)."""
    caller, org = auth_ctx
    use_case = ReviewRulesUseCase(
        rules_repo=SqlAlchemyReviewRulesRepository(db),
        repository_repo=SqlAlchemyRepositoryRepository(db),
        audit_log_repo=SqlAlchemyAuditLogRepository(db),
    )
    try:
        updated = await use_case.update_repo_rule(
            org_id=org.id,
            repo_id=repo_id,
            rule_id=rule_id,
            actor_id=caller.user_id,
            title=payload.title,
            instruction=payload.instruction,
            severity=payload.severity,
            category=payload.category,
            path_globs=payload.path_globs,
            is_enabled=payload.is_enabled,
        )
    except NotFoundError as exc:
        raise HTTPException(status_code=404, detail=exc.message) from exc
    except ValidationError as exc:
        raise HTTPException(status_code=422, detail=exc.message) from exc

    await db.commit()
    return _to_rule_response(updated)


@router.delete("/{repo_id}/review-rules/{rule_id}", status_code=204)
async def delete_repository_review_rule(
    repo_id: uuid.UUID,
    rule_id: uuid.UUID,
    auth_ctx: Annotated[
        tuple[ClerkUserContext, Organization], Depends(require_org_admin)
    ],
    db: Annotated[AsyncSession, Depends(get_db)],
):
    """Soft-delete a repository-specific review rule (org:admin only)."""
    caller, org = auth_ctx
    use_case = ReviewRulesUseCase(
        rules_repo=SqlAlchemyReviewRulesRepository(db),
        repository_repo=SqlAlchemyRepositoryRepository(db),
        audit_log_repo=SqlAlchemyAuditLogRepository(db),
    )
    try:
        await use_case.delete_repo_rule(org.id, repo_id, rule_id, caller.user_id)
    except NotFoundError as exc:
        raise HTTPException(status_code=404, detail=exc.message) from exc
    except ValidationError as exc:
        raise HTTPException(status_code=422, detail=exc.message) from exc

    await db.commit()
    return Response(status_code=204)


@router.put(
    "/{repo_id}/review-rules/{rule_id}/override",
    response_model=ReviewRuleOverrideResponse,
)
async def put_repository_rule_override(
    repo_id: uuid.UUID,
    rule_id: uuid.UUID,
    payload: ReviewRuleOverridePutRequest,
    auth_ctx: Annotated[
        tuple[ClerkUserContext, Organization], Depends(require_org_admin)
    ],
    db: Annotated[AsyncSession, Depends(get_db)],
):
    """Set or clear a repository override on an inherited org rule (org:admin only)."""
    caller, org = auth_ctx
    use_case = ReviewRulesUseCase(
        rules_repo=SqlAlchemyReviewRulesRepository(db),
        repository_repo=SqlAlchemyRepositoryRepository(db),
        audit_log_repo=SqlAlchemyAuditLogRepository(db),
    )
    try:
        override, effective = await use_case.upsert_rule_override(
            org_id=org.id,
            repo_id=repo_id,
            rule_id=rule_id,
            actor_id=caller.user_id,
            is_enabled=payload.is_enabled,
            severity_override=payload.severity_override,
        )
    except NotFoundError as exc:
        raise HTTPException(status_code=404, detail=exc.message) from exc
    except ValidationError as exc:
        raise HTTPException(status_code=422, detail=exc.message) from exc

    await db.commit()
    return ReviewRuleOverrideResponse(
        override_id=override.id if override is not None else None,
        cleared=override is None,
        effective_rule=_to_effective_rule_response(effective),
    )


@router.get("/{repo_id}/review-examples")
async def list_repository_review_examples(
    repo_id: uuid.UUID,
    caller: Annotated[ClerkUserContext, Depends(get_current_clerk_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
):
    """List curated example PRs attached to a repository."""
    org = await resolve_caller_org(caller, db)
    use_case = ReviewExamplesUseCase(
        examples_repo=SqlAlchemyReviewExamplesRepository(db),
        repository_repo=SqlAlchemyRepositoryRepository(db),
        github_gateway=GitHubService(
            app_id=settings.GITHUB_APP_ID,
            private_key=settings.GITHUB_APP_PRIVATE_KEY,
        ),
        audit_log_repo=SqlAlchemyAuditLogRepository(db),
    )
    try:
        examples = await use_case.list_examples(org.id, repo_id)
    except NotFoundError as exc:
        raise HTTPException(status_code=404, detail=exc.message) from exc
    return {"items": [_to_example_response(ex) for ex in examples]}


@router.post(
    "/{repo_id}/review-examples",
    response_model=ReviewExampleResponse,
    status_code=201,
)
async def create_repository_review_example(
    repo_id: uuid.UUID,
    payload: ReviewExampleCreateRequest,
    auth_ctx: Annotated[
        tuple[ClerkUserContext, Organization], Depends(require_org_admin)
    ],
    db: Annotated[AsyncSession, Depends(get_db)],
):
    """Attach a curated example PR to a repository (org:admin only)."""
    caller, org = auth_ctx
    use_case = ReviewExamplesUseCase(
        examples_repo=SqlAlchemyReviewExamplesRepository(db),
        repository_repo=SqlAlchemyRepositoryRepository(db),
        github_gateway=GitHubService(
            app_id=settings.GITHUB_APP_ID,
            private_key=settings.GITHUB_APP_PRIVATE_KEY,
        ),
        audit_log_repo=SqlAlchemyAuditLogRepository(db),
    )
    try:
        created = await use_case.create_example(
            org_id=org.id,
            repo_id=repo_id,
            actor_id=caller.user_id,
            pr_number=payload.pr_number,
            pr_url=payload.pr_url,
            classification=payload.classification,
            guidance_note=payload.guidance_note,
        )
    except NotFoundError as exc:
        raise HTTPException(status_code=404, detail=exc.message) from exc
    except ConflictError as exc:
        raise HTTPException(status_code=409, detail=exc.message) from exc
    except ValidationError as exc:
        raise HTTPException(status_code=422, detail=exc.message) from exc

    await db.commit()
    return _to_example_response(created)


@router.post(
    "/{repo_id}/review-examples/{example_id}/refresh",
    response_model=ReviewExampleResponse,
)
async def refresh_repository_review_example(
    repo_id: uuid.UUID,
    example_id: uuid.UUID,
    auth_ctx: Annotated[
        tuple[ClerkUserContext, Organization], Depends(require_org_admin)
    ],
    db: Annotated[AsyncSession, Depends(get_db)],
):
    """Refresh cached metadata and diff summary for a curated example PR."""
    caller, org = auth_ctx
    use_case = ReviewExamplesUseCase(
        examples_repo=SqlAlchemyReviewExamplesRepository(db),
        repository_repo=SqlAlchemyRepositoryRepository(db),
        github_gateway=GitHubService(
            app_id=settings.GITHUB_APP_ID,
            private_key=settings.GITHUB_APP_PRIVATE_KEY,
        ),
        audit_log_repo=SqlAlchemyAuditLogRepository(db),
    )
    try:
        refreshed = await use_case.refresh_example(
            org_id=org.id,
            repo_id=repo_id,
            example_id=example_id,
            actor_id=caller.user_id,
        )
    except NotFoundError as exc:
        raise HTTPException(status_code=404, detail=exc.message) from exc
    except ValidationError as exc:
        raise HTTPException(status_code=422, detail=exc.message) from exc

    await db.commit()
    return _to_example_response(refreshed)


@router.delete("/{repo_id}/review-examples/{example_id}", status_code=204)
async def delete_repository_review_example(
    repo_id: uuid.UUID,
    example_id: uuid.UUID,
    auth_ctx: Annotated[
        tuple[ClerkUserContext, Organization], Depends(require_org_admin)
    ],
    db: Annotated[AsyncSession, Depends(get_db)],
):
    """Delete a curated example PR from a repository (org:admin only)."""
    caller, org = auth_ctx
    use_case = ReviewExamplesUseCase(
        examples_repo=SqlAlchemyReviewExamplesRepository(db),
        repository_repo=SqlAlchemyRepositoryRepository(db),
        github_gateway=GitHubService(
            app_id=settings.GITHUB_APP_ID,
            private_key=settings.GITHUB_APP_PRIVATE_KEY,
        ),
        audit_log_repo=SqlAlchemyAuditLogRepository(db),
    )
    try:
        await use_case.delete_example(
            org_id=org.id,
            repo_id=repo_id,
            example_id=example_id,
            actor_id=caller.user_id,
        )
    except NotFoundError as exc:
        raise HTTPException(status_code=404, detail=exc.message) from exc

    await db.commit()
    return Response(status_code=204)


@router.get("/{repo_id}/review-preferences")
async def list_repository_review_preferences(
    repo_id: uuid.UUID,
    caller: Annotated[ClerkUserContext, Depends(get_current_clerk_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
    status: Annotated[str | None, Query()] = None,
    limit: Annotated[int, Query(ge=1, le=100)] = 50,
    offset: Annotated[int, Query(ge=0)] = 0,
):
    """List learned feedback preferences for a repository (any org member)."""
    org = await resolve_caller_org(caller, db)
    use_case = ReviewFeedbackUseCase(
        feedback_repo=SqlAlchemyReviewFeedbackRepository(db),
        repository_repo=SqlAlchemyRepositoryRepository(db),
        audit_log_repo=SqlAlchemyAuditLogRepository(db),
    )
    page = (offset // limit) + 1
    try:
        prefs, total = await use_case.list_preferences(
            org.id, repo_id, status=status, page=page, page_size=limit
        )
    except NotFoundError as exc:
        raise HTTPException(status_code=404, detail=exc.message) from exc
    except ValidationError as exc:
        raise HTTPException(status_code=422, detail=exc.message) from exc

    return {
        "items": [_to_pref_response(p) for p in prefs],
        "total": total,
        "limit": limit,
        "offset": offset,
    }


@router.patch(
    "/{repo_id}/review-preferences/{pref_id}",
    response_model=LearnedPreferenceResponse,
)
async def update_repository_review_preference(
    repo_id: uuid.UUID,
    pref_id: uuid.UUID,
    payload: LearnedPreferenceUpdateRequest,
    auth_ctx: Annotated[
        tuple[ClerkUserContext, Organization], Depends(require_org_admin)
    ],
    db: Annotated[AsyncSession, Depends(get_db)],
):
    """Update learned preference status or instruction (org:admin only)."""
    caller, org = auth_ctx
    use_case = ReviewFeedbackUseCase(
        feedback_repo=SqlAlchemyReviewFeedbackRepository(db),
        repository_repo=SqlAlchemyRepositoryRepository(db),
        audit_log_repo=SqlAlchemyAuditLogRepository(db),
    )
    try:
        updated = await use_case.update_preference_admin(
            org_id=org.id,
            repo_id=repo_id,
            pref_id=pref_id,
            actor_id=caller.user_id,
            status=payload.status,
            instruction=payload.instruction,
        )
    except NotFoundError as exc:
        raise HTTPException(status_code=404, detail=exc.message) from exc
    except ValidationError as exc:
        raise HTTPException(status_code=422, detail=exc.message) from exc

    await db.commit()
    return _to_pref_response(updated)
