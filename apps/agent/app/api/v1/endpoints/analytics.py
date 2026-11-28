"""Organization analytics overview API endpoint."""

import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.dependencies.auth import get_current_clerk_user, resolve_caller_org
from app.application.services.analytics_service import AnalyticsService
from app.core.clerk_auth import ClerkUserContext
from app.domain.exceptions import NotFoundError
from app.infrastructure.db.session import get_db

router = APIRouter()


@router.get("/overview")
async def get_analytics_overview(
    caller: Annotated[ClerkUserContext, Depends(get_current_clerk_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
    days: Annotated[int, Query()] = 30,
    repo_id: Annotated[uuid.UUID | None, Query()] = None,
    org_id: Annotated[uuid.UUID | None, Query()] = None,
):
    """Compute organization-scoped quality, turnaround, and cost analytics."""
    if days not in (7, 30, 90):
        raise HTTPException(
            status_code=422,
            detail="Invalid days parameter; expected 7, 30, or 90",
        )

    org = await resolve_caller_org(caller, db, requested_org_id=org_id)
    service = AnalyticsService(db)
    try:
        return await service.get_overview(org.id, days=days, repo_id=repo_id)
    except NotFoundError as exc:
        raise HTTPException(status_code=404, detail=exc.message) from exc
