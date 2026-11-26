"""Pull Request Reviews API endpoints."""

import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.dependencies.auth import get_current_clerk_user, resolve_caller_org
from app.core.clerk_auth import ClerkUserContext
from app.core.config import settings
from app.domain.exceptions import ConflictError, NotFoundError
from app.infrastructure.db.repositories.pr_review_repository import (
    SqlAlchemyPRReviewRepository,
)
from app.infrastructure.db.repositories.repository_repository import (
    SqlAlchemyRepositoryRepository,
)
from app.infrastructure.db.session import get_db
from app.infrastructure.github.github_service import GitHubService

router = APIRouter()


class TriggerReviewRequest(BaseModel):
    org_id: uuid.UUID | None = None


class ReviewFindingResponse(BaseModel):
    id: uuid.UUID
    file_path: str
    line_number: int
    start_line: int | None = None
    side: str
    severity: str
    category: str
    title: str
    message: str
    suggested_patch: str | None = None
    github_comment_id: int | None = None
    status: str


class PRReviewSummaryResponse(BaseModel):
    id: uuid.UUID
    org_id: uuid.UUID
    repo_id: uuid.UUID
    pr_number: int
    pr_title: str
    pr_author: str
    head_commit_sha: str
    base_commit_sha: str
    status: str
    verdict: str | None = None
    summary: str | None = None
    github_review_id: int | None = None
    context_token_count: int
    model_name: str
    execution_duration_ms: int | None = None
    error_message: str | None = None
    created_at: str | None = None


class PRReviewDetailResponse(PRReviewSummaryResponse):
    findings: list[ReviewFindingResponse] = Field(default_factory=list)


@router.post(
    "/repos/{repo_id}/pulls/{pr_number}/reviews",
    response_model=dict,
)
async def trigger_pr_review(
    repo_id: uuid.UUID,
    pr_number: int,
    db: Annotated[AsyncSession, Depends(get_db)],
    caller: Annotated[ClerkUserContext, Depends(get_current_clerk_user)],
    payload: TriggerReviewRequest | None = None,
):
    """Trigger a full repository context code review for a pull request."""
    org = await resolve_caller_org(
        caller,
        db,
        requested_org_id=payload.org_id if payload else None,
    )
    repo_repo = SqlAlchemyRepositoryRepository(db)
    try:
        repo = await repo_repo.get_by_id(org.id, repo_id)
    except NotFoundError as exc:
        raise HTTPException(status_code=404, detail="Repository not found") from exc

    pr_review_repo = SqlAlchemyPRReviewRepository(db)
    active = await pr_review_repo.find_active_by_repo_and_pr(repo_id, pr_number)
    if active:
        raise HTTPException(
            status_code=409,
            detail=f"An active review already exists for PR #{pr_number}",
        )

    # Fetch PR details from GitHub
    github_service = GitHubService(
        app_id=settings.GITHUB_APP_ID,
        private_key=settings.GITHUB_APP_PRIVATE_KEY,
    )
    token = await github_service.get_installation_token(repo.github_installation_id)
    pr_info = await github_service.get_pull_request(repo.full_name, pr_number, token)

    try:
        review = await pr_review_repo.create_review(
            org_id=org.id,
            repo_id=repo_id,
            pr_number=pr_number,
            pr_title=pr_info.get("title", f"PR #{pr_number}"),
            pr_author=pr_info.get("user", {}).get("login", "unknown"),
            head_commit_sha=pr_info.get("head", {}).get("sha", ""),
            base_commit_sha=pr_info.get("base", {}).get("sha", ""),
            model_name="claude-3-5-sonnet",
        )
    except ConflictError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc

    return {
        "id": str(review.id),
        "status": review.status,
        "pr_number": review.pr_number,
    }


@router.get(
    "/repos/{repo_id}/pulls/{pr_number}/reviews",
    response_model=dict,
)
async def list_pr_reviews(
    repo_id: uuid.UUID,
    pr_number: int,
    db: Annotated[AsyncSession, Depends(get_db)],
    caller: Annotated[ClerkUserContext, Depends(get_current_clerk_user)],
    org_id: Annotated[uuid.UUID | None, Query()] = None,
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
):
    """List historical reviews for a pull request."""
    org = await resolve_caller_org(caller, db, requested_org_id=org_id)
    pr_review_repo = SqlAlchemyPRReviewRepository(db)
    reviews, total = await pr_review_repo.list_by_repo_and_pr(
        org_id=org.id,
        repo_id=repo_id,
        pr_number=pr_number,
        page=page,
        page_size=page_size,
    )

    items = [
        PRReviewSummaryResponse(
            id=r.id,
            org_id=r.org_id,
            repo_id=r.repo_id,
            pr_number=r.pr_number,
            pr_title=r.pr_title,
            pr_author=r.pr_author,
            head_commit_sha=r.head_commit_sha,
            base_commit_sha=r.base_commit_sha,
            status=r.status,
            verdict=r.verdict,
            summary=r.summary,
            github_review_id=r.github_review_id,
            context_token_count=r.context_token_count,
            model_name=r.model_name,
            execution_duration_ms=r.execution_duration_ms,
            error_message=r.error_message,
            created_at=r.created_at.isoformat() if r.created_at else None,
        )
        for r in reviews
    ]

    return {
        "items": items,
        "total": total,
        "page": page,
        "page_size": page_size,
    }


@router.get(
    "/reviews/{review_id}",
    response_model=PRReviewDetailResponse,
)
async def get_pr_review_detail(
    review_id: uuid.UUID,
    db: Annotated[AsyncSession, Depends(get_db)],
    caller: Annotated[ClerkUserContext, Depends(get_current_clerk_user)],
    org_id: Annotated[uuid.UUID | None, Query()] = None,
):
    """Retrieve PR review details and structured findings."""
    org = await resolve_caller_org(caller, db, requested_org_id=org_id)
    pr_review_repo = SqlAlchemyPRReviewRepository(db)
    try:
        review = await pr_review_repo.get_by_id(org.id, review_id)
    except NotFoundError as exc:
        raise HTTPException(status_code=404, detail="Review not found") from exc

    findings, _ = await pr_review_repo.list_findings(review_id, page=1, page_size=100)

    findings_res = [
        ReviewFindingResponse(
            id=f.id,
            file_path=f.file_path,
            line_number=f.line_number,
            start_line=f.start_line,
            side=f.side,
            severity=f.severity,
            category=f.category,
            title=f.title,
            message=f.message,
            suggested_patch=f.suggested_patch,
            github_comment_id=f.github_comment_id,
            status=f.status,
        )
        for f in findings
    ]

    return PRReviewDetailResponse(
        id=review.id,
        org_id=review.org_id,
        repo_id=review.repo_id,
        pr_number=review.pr_number,
        pr_title=review.pr_title,
        pr_author=review.pr_author,
        head_commit_sha=review.head_commit_sha,
        base_commit_sha=review.base_commit_sha,
        status=review.status,
        verdict=review.verdict,
        summary=review.summary,
        github_review_id=review.github_review_id,
        context_token_count=review.context_token_count,
        model_name=review.model_name,
        execution_duration_ms=review.execution_duration_ms,
        error_message=review.error_message,
        created_at=review.created_at.isoformat() if review.created_at else None,
        findings=findings_res,
    )
