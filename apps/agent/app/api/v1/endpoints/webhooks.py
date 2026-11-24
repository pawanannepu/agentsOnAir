"""GitHub webhook receiver endpoint."""

from typing import Annotated

from fastapi import APIRouter, Depends, Header, HTTPException, Request
from sqlalchemy.ext.asyncio import AsyncSession

from app.application.use_cases.ingest_github_webhook import (
    IngestGitHubWebhookUseCase,
)
from app.core.config import settings
from app.domain.exceptions import WebhookSignatureError
from app.infrastructure.db.repositories.pr_review_repository import (
    SqlAlchemyPRReviewRepository,
)
from app.infrastructure.db.repositories.repository_repository import (
    SqlAlchemyRepositoryRepository,
)
from app.infrastructure.db.repositories.task_repository import (
    SqlAlchemyTaskRepository,
)
from app.infrastructure.db.session import get_db
from app.infrastructure.github.github_service import GitHubService

router = APIRouter()


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
    github_gateway = GitHubService(
        app_id=settings.GITHUB_APP_ID,
        private_key=settings.GITHUB_APP_PRIVATE_KEY,
    )
    use_case = IngestGitHubWebhookUseCase(
        repository_repo=repo_repo,
        task_repo=task_repo,
        pr_review_repo=pr_review_repo,
        github_gateway=github_gateway,
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
