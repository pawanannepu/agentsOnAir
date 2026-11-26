"""FastAPI authentication and tenant authorization dependencies."""

import uuid
from typing import Annotated

from fastapi import Depends, HTTPException, Request, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.ext.asyncio import AsyncSession

from app.application.use_cases.sync_organization import SyncOrganizationUseCase
from app.core.clerk_auth import ClerkUserContext, verify_clerk_jwt
from app.core.config import settings
from app.domain.entities.organization import Organization
from app.domain.entities.task import Task
from app.domain.exceptions import (
    AuthenticationError,
    ConfigurationError,
    ConflictError,
    ExternalServiceError,
    NotFoundError,
)
from app.infrastructure.clerk.clerk_gateway import HttpxClerkOrganizationGateway
from app.infrastructure.db import session as db_session_module
from app.infrastructure.db.repositories.audit_log_repository import (
    SqlAlchemyAuditLogRepository,
)
from app.infrastructure.db.repositories.organization_repository import (
    SqlAlchemyOrganizationRepository,
)
from app.infrastructure.db.repositories.task_repository import (
    SqlAlchemyTaskRepository,
)

bearer_scheme = HTTPBearer(auto_error=False)


def forbidden_error(code: str, message: str) -> HTTPException:
    """Build a structured HTTP 403 error payload discriminated by client UI."""
    return HTTPException(
        status_code=status.HTTP_403_FORBIDDEN,
        detail={"code": code, "message": message},
    )


async def sync_organization_isolated(
    *,
    clerk_org_id: str,
    actor_user_id: str,
) -> Organization:
    """Run Clerk Backend API sync in an isolated short lived committed session."""
    gateway = HttpxClerkOrganizationGateway(secret_key=settings.CLERK_SECRET_KEY)
    try:
        async with db_session_module.async_session_factory() as isolated_session:
            try:
                use_case = SyncOrganizationUseCase(
                    org_repo=SqlAlchemyOrganizationRepository(isolated_session),
                    audit_repo=SqlAlchemyAuditLogRepository(isolated_session),
                    clerk_gateway=gateway,
                )
                org = await use_case.sync_from_clerk_api(
                    clerk_org_id=clerk_org_id,
                    actor_user_id=actor_user_id,
                )
                await isolated_session.commit()
                return org
            except Exception:
                await isolated_session.rollback()
                raise
    except (NotFoundError, ConfigurationError) as exc:
        raise forbidden_error("org_inactive", exc.message) from exc
    except ConflictError as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={"code": "org_slug_conflict", "message": exc.message},
        ) from exc
    except ExternalServiceError as exc:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail={"code": "clerk_upstream_error", "message": exc.message},
        ) from exc


async def get_current_clerk_user(
    request: Request,
    credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(bearer_scheme)],
) -> ClerkUserContext:
    """Authenticate caller via Clerk Bearer JWT or __session cookie."""
    token: str | None = credentials.credentials if credentials else None
    if not token:
        token = request.cookies.get("__session")

    if not token:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Missing authentication token",
            headers={"WWW-Authenticate": "Bearer"},
        )

    try:
        return verify_clerk_jwt(
            token,
            jwt_key=settings.CLERK_JWT_KEY,
            issuer_url=settings.CLERK_ISSUER_URL,
        )
    except AuthenticationError as exc:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=exc.message,
            headers={"WWW-Authenticate": "Bearer"},
        ) from exc


async def resolve_caller_org(
    caller: ClerkUserContext,
    db: AsyncSession,
    *,
    requested_org_id: uuid.UUID | None = None,
) -> Organization:
    """Resolve active Organization from Clerk JWT, lazy syncing if absent."""
    if not caller.clerk_org_id:
        raise forbidden_error(
            "org_missing",
            "Active organization claim is required",
        )

    org_repo = SqlAlchemyOrganizationRepository(db)
    try:
        caller_org = await org_repo.get_by_clerk_id(caller.clerk_org_id)
    except NotFoundError:
        caller_org = await sync_organization_isolated(
            clerk_org_id=caller.clerk_org_id,
            actor_user_id=caller.user_id,
        )

    if requested_org_id is not None and caller_org.id != requested_org_id:
        raise forbidden_error(
            "org_mismatch",
            "Requested organization does not match authenticated token",
        )

    return caller_org


async def authorize_task_org(
    task_id: uuid.UUID,
    caller: ClerkUserContext,
    db: AsyncSession,
    requested_org_id: uuid.UUID | None = None,
) -> tuple[Organization, Task]:
    """Verify task existence (404) and caller organization ownership (403)."""
    task_repo = SqlAlchemyTaskRepository(db)
    try:
        task = await task_repo.get_by_id_unscoped(task_id)
    except NotFoundError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Task {task_id} not found",
        ) from exc

    caller_org = await resolve_caller_org(
        caller,
        db,
        requested_org_id=requested_org_id,
    )

    if task.org_id != caller_org.id:
        raise forbidden_error(
            "org_mismatch",
            "Task belongs to a different organization",
        )

    return caller_org, task


async def require_org_admin(
    caller: Annotated[ClerkUserContext, Depends(get_current_clerk_user)],
    db: Annotated[AsyncSession, Depends(db_session_module.get_db)],
) -> tuple[ClerkUserContext, Organization]:
    """Require an active organization and org:admin role on the Clerk JWT."""
    org = await resolve_caller_org(caller, db)
    if caller.org_role != "org:admin":
        raise forbidden_error(
            "org_admin_required",
            "Organization admin role (org:admin) is required",
        )
    return caller, org
