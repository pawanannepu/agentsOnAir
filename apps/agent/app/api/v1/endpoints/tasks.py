"""Tasks API endpoints."""

import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.domain.exceptions import NotFoundError
from app.infrastructure.db.models.repository import RepositoryModel
from app.infrastructure.db.models.task_run import TaskRunModel
from app.infrastructure.db.repositories.review_iteration_repository import (
    SqlAlchemyReviewIterationRepository,
)
from app.infrastructure.db.repositories.task_repository import (
    SqlAlchemyTaskRepository,
)
from app.infrastructure.db.session import get_db

router = APIRouter()


class CreateTaskRequest(BaseModel):
    org_id: uuid.UUID
    repo_id: uuid.UUID
    title: str = Field(..., min_length=1, max_length=255)
    description: str
    base_branch: str = "main"


class ReviewIterationResponse(BaseModel):
    id: uuid.UUID
    cycle_number: int
    verdict: str
    summary: str
    findings: list[dict]
    blocking_count: int
    non_blocking_count: int
    diff_snapshot: str | None = None
    created_at: str | None = None


class TaskRunResponse(BaseModel):
    id: uuid.UUID
    run_number: int
    status: str
    failure_reason: str | None = None
    review_iterations: list[ReviewIterationResponse] = Field(default_factory=list)


class TaskDetailResponse(BaseModel):
    id: uuid.UUID
    org_id: uuid.UUID
    repo_id: uuid.UUID
    title: str
    description: str
    status: str
    trigger_type: str
    base_branch: str
    branch_name: str | None = None
    pr_number: int | None = None
    pr_url: str | None = None
    head_commit_sha: str | None = None
    pr_review_status: str | None = None
    runs: list[TaskRunResponse] = Field(default_factory=list)


@router.post("", response_model=dict)
async def create_task(
    payload: CreateTaskRequest,
    db: Annotated[AsyncSession, Depends(get_db)],
):
    """Create a new autonomous task."""
    repo_stmt = select(RepositoryModel).where(
        RepositoryModel.id == payload.repo_id,
        RepositoryModel.org_id == payload.org_id,
        RepositoryModel.deleted_at.is_(None),
    )
    repo = (await db.execute(repo_stmt)).scalar_one_or_none()
    if not repo:
        raise HTTPException(status_code=404, detail="Repository not found")

    task_repo = SqlAlchemyTaskRepository(db)
    task = await task_repo.create_task(
        org_id=payload.org_id,
        repo_id=payload.repo_id,
        title=payload.title,
        description=payload.description,
        trigger_type="manual_console",
        base_branch=payload.base_branch,
    )
    return {"id": str(task.id), "status": task.status}


@router.get("/{task_id}", response_model=TaskDetailResponse)
async def get_task(
    task_id: uuid.UUID,
    org_id: Annotated[uuid.UUID, Query(...)],
    db: Annotated[AsyncSession, Depends(get_db)],
):
    """Retrieve task details, runs, and review iterations."""
    task_repo = SqlAlchemyTaskRepository(db)
    try:
        task = await task_repo.get_by_id(org_id, task_id)
    except NotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc

    # Fetch runs
    runs_stmt = (
        select(TaskRunModel)
        .where(
            TaskRunModel.task_id == task_id,
            TaskRunModel.org_id == org_id,
        )
        .order_by(TaskRunModel.run_number.asc())
    )
    runs_models = (await db.execute(runs_stmt)).scalars().all()

    review_repo = SqlAlchemyReviewIterationRepository(db)
    runs_data: list[TaskRunResponse] = []
    for run in runs_models:
        iterations = await review_repo.list_by_task_run_id(org_id, run.id)
        runs_data.append(
            TaskRunResponse(
                id=run.id,
                run_number=run.run_number,
                status=run.status,
                failure_reason=run.failure_reason,
                review_iterations=[
                    ReviewIterationResponse(
                        id=it.id,
                        cycle_number=it.cycle_number,
                        verdict=it.verdict,
                        summary=it.summary,
                        findings=it.findings,
                        blocking_count=it.blocking_count,
                        non_blocking_count=it.non_blocking_count,
                        diff_snapshot=it.diff_snapshot,
                        created_at=it.created_at.isoformat() if it.created_at else None,
                    )
                    for it in iterations
                ],
            )
        )

    return TaskDetailResponse(
        id=task.id,
        org_id=task.org_id,
        repo_id=task.repo_id,
        title=task.title,
        description=task.description,
        status=task.status,
        trigger_type=task.trigger_type,
        base_branch=task.base_branch,
        branch_name=task.branch_name,
        pr_number=task.pr_number,
        pr_url=task.pr_url,
        head_commit_sha=task.head_commit_sha,
        pr_review_status=task.pr_review_status,
        runs=runs_data,
    )
