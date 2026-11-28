"""GitHub and Clerk webhook receiver endpoints."""

import json
from typing import Annotated

from fastapi import APIRouter, Depends, Header, HTTPException, Request
from sqlalchemy.ext.asyncio import AsyncSession
from svix.webhooks import Webhook, WebhookVerificationError

from app.application.use_cases.ingest_github_webhook import (
    IngestGitHubWebhookUseCase,
)
from app.application.use_cases.sync_organization import SyncOrganizationUseCase
from app.core.config import settings
from app.domain.exceptions import (
    ConflictError,
    ValidationError,
    WebhookSignatureError,
)
from app.infrastructure.db.repositories.audit_log_repository import (
    SqlAlchemyAuditLogRepository,
)
from app.infrastructure.db.repositories.organization_repository import (
    SqlAlchemyOrganizationRepository,
)
from app.infrastructure.db.repositories.pr_review_repository import (
    SqlAlchemyPRReviewRepository,
)
from app.infrastructure.db.repositories.repository_repository import (
    SqlAlchemyRepositoryRepository,
)
from app.infrastructure.db.repositories.review_feedback_repository import (
    SqlAlchemyReviewFeedbackRepository,
)
from app.infrastructure.db.repositories.task_repository import (
    SqlAlchemyTaskRepository,
)
from app.infrastructure.db.session import get_db
from app.infrastructure.github.github_service import GitHubService

router = APIRouter()

PLACEHOLDER_WEBHOOK_SECRETS = {"whsec_placeholder", ""}


@router.post("/github")
async def handle_github_webhook(
    request: Request,
    x_github_event: Annotated[str | None, Header(alias="X-GitHub-Event")] = None,
    x_hub_signature_256: Annotated[
        str | None, Header(alias="X-Hub-Signature-256")
    ] = None,
    x_github_delivery: Annotated[str | None, Header(alias="X-GitHub-Delivery")] = None,
    db: Annotated[AsyncSession, Depends(get_db)] = None,  # type: ignore[assignment]
):
    """Handle incoming GitHub App webhooks."""
    payload_bytes = await request.body()

    repo_repo = SqlAlchemyRepositoryRepository(db)
    task_repo = SqlAlchemyTaskRepository(db)
    pr_review_repo = SqlAlchemyPRReviewRepository(db)
    review_feedback_repo = SqlAlchemyReviewFeedbackRepository(db)
    github_gateway = GitHubService(
        app_id=settings.GITHUB_APP_ID,
        private_key=settings.GITHUB_APP_PRIVATE_KEY,
    )
    use_case = IngestGitHubWebhookUseCase(
        repository_repo=repo_repo,
        task_repo=task_repo,
        pr_review_repo=pr_review_repo,
        github_gateway=github_gateway,
        review_feedback_repo=review_feedback_repo,
    )

    try:
        result = await use_case.execute(
            event_type=x_github_event,
            delivery_id=x_github_delivery,
            payload_bytes=payload_bytes,
            signature_header=x_hub_signature_256,
            webhook_secret=settings.GITHUB_WEBHOOK_SECRET,
        )
    except WebhookSignatureError as exc:
        raise HTTPException(status_code=401, detail=str(exc)) from exc

    response_data: dict[str, str | None] = {"status": result.status}
    if result.task_id:
        response_data["task_id"] = result.task_id
    if result.review_id:
        response_data["review_id"] = result.review_id
    if result.reason:
        response_data["reason"] = result.reason

    return response_data


@router.post("/clerk")
async def handle_clerk_webhook(
    request: Request,
    svix_id: Annotated[str | None, Header(alias="svix-id")] = None,
    svix_timestamp: Annotated[str | None, Header(alias="svix-timestamp")] = None,
    svix_signature: Annotated[str | None, Header(alias="svix-signature")] = None,
    db: Annotated[AsyncSession, Depends(get_db)] = None,  # type: ignore[assignment]
):
    """Handle incoming Clerk organization lifecycle webhooks verified via Svix."""
    signing_secret = (settings.CLERK_WEBHOOK_SIGNING_SECRET or "").strip()
    if not signing_secret or signing_secret in PLACEHOLDER_WEBHOOK_SECRETS:
        raise HTTPException(
            status_code=503,
            detail="Clerk webhook signing secret is not configured",
        )

    if not svix_id or not svix_timestamp or not svix_signature:
        raise HTTPException(
            status_code=400,
            detail="Missing required Svix verification headers",
        )

    payload_bytes = await request.body()
    svix_headers = {
        "svix-id": svix_id,
        "svix-timestamp": svix_timestamp,
        "svix-signature": svix_signature,
    }

    try:
        Webhook(signing_secret).verify(payload_bytes, svix_headers)
    except WebhookVerificationError as exc:
        raise HTTPException(
            status_code=401,
            detail="Invalid or expired Clerk webhook signature",
        ) from exc

    try:
        payload = json.loads(payload_bytes)
    except (ValueError, UnicodeDecodeError) as exc:
        raise HTTPException(status_code=400, detail="Malformed JSON payload") from exc

    if not isinstance(payload, dict):
        raise HTTPException(status_code=400, detail="Invalid Clerk webhook payload")

    event_type = payload.get("type")
    event_data = payload.get("data")
    if not isinstance(event_type, str) or not isinstance(event_data, dict):
        raise HTTPException(
            status_code=400,
            detail="Clerk webhook payload must contain 'type' and 'data' fields",
        )

    org_repo = SqlAlchemyOrganizationRepository(db)
    audit_repo = SqlAlchemyAuditLogRepository(db)
    use_case = SyncOrganizationUseCase(org_repo=org_repo, audit_repo=audit_repo)

    try:
        result = await use_case.sync_from_webhook(
            event_type=event_type,
            data=event_data,
        )
    except ValidationError as exc:
        raise HTTPException(status_code=400, detail=exc.message) from exc
    except ConflictError as exc:
        raise HTTPException(status_code=409, detail=exc.message) from exc

    await db.commit()
    return {
        "status": result.status,
        "org_id": str(result.org_id) if result.org_id else None,
    }
