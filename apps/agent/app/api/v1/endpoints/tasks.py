"""Tasks API endpoints."""

import gzip
import json
import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, Header, HTTPException, Query, Request
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sse_starlette.event import ServerSentEvent
from sse_starlette.sse import EventSourceResponse

from app.api.dependencies.auth import (
    authorize_task_org,
    get_current_clerk_user,
    resolve_caller_org,
)
from app.core.clerk_auth import ClerkUserContext
from app.domain.exceptions import ConcurrencyError, NotFoundError
from app.infrastructure.db.models.repository import RepositoryModel
from app.infrastructure.db.models.sandbox_run import SandboxRunModel
from app.infrastructure.db.models.task_run import TaskRunModel
from app.infrastructure.db.repositories.audit_log_repository import (
    SqlAlchemyAuditLogRepository,
)
from app.infrastructure.db.repositories.review_iteration_repository import (
    SqlAlchemyReviewIterationRepository,
)
from app.infrastructure.db.repositories.task_intervention_repository import (
    SqlAlchemyTaskInterventionRepository,
)
from app.infrastructure.db.repositories.task_repository import (
    SqlAlchemyTaskRepository,
)
from app.infrastructure.db.repositories.task_transcript_repository import (
    SqlAlchemyTaskTranscriptRepository,
)
from app.infrastructure.db.session import get_db
from app.infrastructure.events.redis_streamer import get_event_streamer
from app.infrastructure.queue.arq_queue import get_task_queue
from app.infrastructure.sandbox.registry import get_sandbox_registry

router = APIRouter()


class CreateTaskRequest(BaseModel):
    org_id: uuid.UUID | None = None
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
    repo_full_name: str | None = None
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
    interruption_prompt: str | None = None
    interruption_type: str | None = None
    interruption_options: list | dict | None = None
    interruption_expires_at: str | None = None
    runs: list[TaskRunResponse] = Field(default_factory=list)


class InterveneRequest(BaseModel):
    message: str = Field(..., min_length=1)
    action_type: str = Field("guidance", pattern="^(guidance|abort)$")


class RespondRequest(BaseModel):
    response: str = Field(..., min_length=1)
    selected_option: str | None = None


class AbortRequest(BaseModel):
    reason: str = "Aborted by operator"


class TranscriptResponse(BaseModel):
    task_id: uuid.UUID
    terminal_log: str
    events: list[dict]
    total_lines: int


@router.post("", response_model=dict)
async def create_task(
    payload: CreateTaskRequest,
    db: Annotated[AsyncSession, Depends(get_db)],
    caller: Annotated[ClerkUserContext, Depends(get_current_clerk_user)],
):
    """Create a new autonomous task."""
    org = await resolve_caller_org(caller, db, requested_org_id=payload.org_id)

    repo_stmt = select(RepositoryModel).where(
        RepositoryModel.id == payload.repo_id,
        RepositoryModel.org_id == org.id,
        RepositoryModel.deleted_at.is_(None),
    )
    repo = (await db.execute(repo_stmt)).scalar_one_or_none()
    if not repo:
        raise HTTPException(status_code=404, detail="Repository not found")

    task_repo = SqlAlchemyTaskRepository(db)
    task = await task_repo.create_task(
        org_id=org.id,
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
    db: Annotated[AsyncSession, Depends(get_db)],
    caller: Annotated[ClerkUserContext, Depends(get_current_clerk_user)],
    org_id: Annotated[uuid.UUID | None, Query()] = None,
):
    """Retrieve task details, runs, and review iterations."""
    org, task = await authorize_task_org(
        task_id,
        caller,
        db,
        requested_org_id=org_id,
    )

    repo_stmt = select(RepositoryModel.full_name).where(
        RepositoryModel.id == task.repo_id,
        RepositoryModel.org_id == org.id,
    )
    repo_full_name = (await db.execute(repo_stmt)).scalar_one_or_none()

    # Fetch runs
    runs_stmt = (
        select(TaskRunModel)
        .where(
            TaskRunModel.task_id == task_id,
            TaskRunModel.org_id == org.id,
        )
        .order_by(TaskRunModel.run_number.asc())
    )
    runs_models = (await db.execute(runs_stmt)).scalars().all()

    review_repo = SqlAlchemyReviewIterationRepository(db)
    runs_data: list[TaskRunResponse] = []
    for run in runs_models:
        iterations = await review_repo.list_by_task_run_id(org.id, run.id)
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
        repo_full_name=repo_full_name,
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
        interruption_prompt=task.interruption_prompt,
        interruption_type=task.interruption_type,
        interruption_options=task.interruption_options,
        interruption_expires_at=(
            task.interruption_expires_at.isoformat()
            if task.interruption_expires_at
            else None
        ),
        runs=runs_data,
    )


@router.get("/{task_id}/events")
async def stream_task_events(
    task_id: uuid.UUID,
    request: Request,
    db: Annotated[AsyncSession, Depends(get_db)],
    caller: Annotated[ClerkUserContext, Depends(get_current_clerk_user)],
    org_id: Annotated[uuid.UUID | None, Query()] = None,
    last_event_id: Annotated[str | None, Header(alias="Last-Event-ID")] = None,
    follow: Annotated[
        bool, Query(description="Follow live events or drain existing events")
    ] = True,
):
    """Server Sent Events stream of execution telemetry and agent decisions."""
    _org, task = await authorize_task_org(task_id, caller, db, requested_org_id=org_id)

    streamer = get_event_streamer()

    async def event_generator():
        cursor = last_event_id or "0-0"

        # If task is terminal at connection time,
        # yield remaining events and exit
        if task.status in ("completed", "failed", "cancelled"):
            remaining = await streamer.read_events(
                task_id, last_event_id=cursor, count=500, block_ms=0
            )
            for eid, etype, edata, ets in remaining:
                payload = json.dumps(
                    {
                        "event_id": eid,
                        "task_id": str(task_id),
                        "timestamp": ets,
                        **edata,
                    }
                )
                yield ServerSentEvent(data=payload, event=etype, id=eid)
            # Send terminal status event
            terminal_payload = json.dumps(
                {
                    "task_id": str(task_id),
                    "status": task.status,
                }
            )
            yield ServerSentEvent(data=terminal_payload, event="task.status")
            return

        while True:
            events = await streamer.read_events(
                task_id, last_event_id=cursor, count=50, block_ms=1000 if follow else 0
            )
            if events:
                for eid, etype, edata, ets in events:
                    payload = json.dumps(
                        {
                            "event_id": eid,
                            "task_id": str(task_id),
                            "timestamp": ets,
                            **edata,
                        }
                    )
                    yield ServerSentEvent(data=payload, event=etype, id=eid)
                    cursor = eid
                    if etype == "task.status" and edata.get("status") in (
                        "completed",
                        "failed",
                        "cancelled",
                    ):
                        return
            elif not follow:
                return

    return EventSourceResponse(event_generator(), ping=15)


@router.post("/{task_id}/intervene", response_model=dict)
async def intervene_task(
    task_id: uuid.UUID,
    payload: InterveneRequest,
    db: Annotated[AsyncSession, Depends(get_db)],
    caller: Annotated[ClerkUserContext, Depends(get_current_clerk_user)],
    org_id: Annotated[uuid.UUID | None, Query()] = None,
):
    """Submit developer guidance during task execution."""
    org, task = await authorize_task_org(task_id, caller, db, requested_org_id=org_id)

    if task.status in ("completed", "failed", "cancelled"):
        raise HTTPException(
            status_code=409, detail=f"Task is already terminal: {task.status}"
        )

    intervention_repo = SqlAlchemyTaskInterventionRepository(db)
    audit_repo = SqlAlchemyAuditLogRepository(db)

    intervention = await intervention_repo.create(
        org_id=org.id,
        task_id=task_id,
        clerk_user_id=caller.user_id,
        intervention_type=payload.action_type,
        payload={"message": payload.message},
    )

    await audit_repo.record_event(
        org_id=org.id,
        actor_type="user",
        actor_id=caller.user_id,
        action="task_intervention_submitted",
        target_type="task",
        target_id=task_id,
        payload_after={"message": payload.message, "action_type": payload.action_type},
    )

    streamer = get_event_streamer()
    await streamer.append_event(
        task_id,
        "task.step",
        {
            "node": "human_intervention",
            "action": payload.action_type,
            "message": payload.message,
            "user_id": caller.user_id,
        },
    )

    await db.commit()
    return {"intervention_id": str(intervention.id), "status": "queued"}


@router.post("/{task_id}/respond", response_model=dict)
async def respond_to_interruption(
    task_id: uuid.UUID,
    payload: RespondRequest,
    db: Annotated[AsyncSession, Depends(get_db)],
    caller: Annotated[ClerkUserContext, Depends(get_current_clerk_user)],
    org_id: Annotated[uuid.UUID | None, Query()] = None,
):
    """Respond to an agent clarification request with optimistic concurrency."""
    org, _task = await authorize_task_org(task_id, caller, db, requested_org_id=org_id)

    task_repo = SqlAlchemyTaskRepository(db)
    try:
        _claimed, prompt_snapshot = await task_repo.claim_interruption(
            org.id, task_id, new_status="in_progress"
        )
    except NotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ConcurrencyError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc

    intervention_repo = SqlAlchemyTaskInterventionRepository(db)
    audit_repo = SqlAlchemyAuditLogRepository(db)

    intervention = await intervention_repo.create(
        org_id=org.id,
        task_id=task_id,
        clerk_user_id=caller.user_id,
        intervention_type="clarification_response",
        prompt_snapshot=prompt_snapshot,
        payload={
            "response": payload.response,
            "selected_option": payload.selected_option,
        },
    )

    await audit_repo.record_event(
        org_id=org.id,
        actor_type="user",
        actor_id=caller.user_id,
        action="task_interruption_answered",
        target_type="task",
        target_id=task_id,
        payload_after={
            "response": payload.response,
            "selected_option": payload.selected_option,
            "prompt_snapshot": prompt_snapshot,
        },
    )

    streamer = get_event_streamer()
    await streamer.append_event(
        task_id,
        "task.resumed",
        {
            "intervention_id": str(intervention.id),
            "response": payload.response,
            "selected_option": payload.selected_option,
        },
    )

    await db.commit()

    await get_task_queue().enqueue_resume_task(
        org_id=org.id,
        task_id=task_id,
        intervention_id=intervention.id,
        response=payload.response,
    )

    return {"intervention_id": str(intervention.id), "status": "accepted"}


@router.post("/{task_id}/abort", response_model=dict)
async def abort_task(
    task_id: uuid.UUID,
    payload: AbortRequest,
    db: Annotated[AsyncSession, Depends(get_db)],
    caller: Annotated[ClerkUserContext, Depends(get_current_clerk_user)],
    org_id: Annotated[uuid.UUID | None, Query()] = None,
):
    """Abort an active or paused task."""
    org, _task = await authorize_task_org(task_id, caller, db, requested_org_id=org_id)

    task_repo = SqlAlchemyTaskRepository(db)
    try:
        await task_repo.claim_abort(org.id, task_id)
    except NotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ConcurrencyError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc

    # Terminate any paused sandbox if the task was awaiting input
    run_stmt = (
        select(TaskRunModel)
        .where(
            TaskRunModel.task_id == task_id,
            TaskRunModel.org_id == org.id,
        )
        .order_by(TaskRunModel.run_number.desc())
        .limit(1)
    )
    run_model = (await db.execute(run_stmt)).scalar_one_or_none()
    if run_model is not None:
        sbx_stmt = select(SandboxRunModel).where(
            SandboxRunModel.task_run_id == run_model.id,
            SandboxRunModel.org_id == org.id,
        )
        sbx_model = (await db.execute(sbx_stmt)).scalar_one_or_none()
        if sbx_model and sbx_model.status == "active":
            sbx_model.status = "terminated"
            await get_sandbox_registry().terminate_if_present(sbx_model.sandbox_id)

    intervention_repo = SqlAlchemyTaskInterventionRepository(db)
    audit_repo = SqlAlchemyAuditLogRepository(db)

    await intervention_repo.create(
        org_id=org.id,
        task_id=task_id,
        clerk_user_id=caller.user_id,
        intervention_type="abort",
        payload={"reason": payload.reason},
    )

    await audit_repo.record_event(
        org_id=org.id,
        actor_type="user",
        actor_id=caller.user_id,
        action="task_aborted",
        target_type="task",
        target_id=task_id,
        payload_after={"reason": payload.reason},
    )

    streamer = get_event_streamer()
    await streamer.append_event(
        task_id,
        "task.status",
        {
            "status": "cancelled",
            "reason": payload.reason,
            "aborted_by": caller.user_id,
        },
    )

    await db.commit()
    return {"task_id": str(task_id), "status": "cancelled"}


@router.get("/{task_id}/transcript", response_model=TranscriptResponse)
async def get_task_transcript(
    task_id: uuid.UUID,
    db: Annotated[AsyncSession, Depends(get_db)],
    caller: Annotated[ClerkUserContext, Depends(get_current_clerk_user)],
    org_id: Annotated[uuid.UUID | None, Query()] = None,
    run_id: Annotated[uuid.UUID | None, Query()] = None,
):
    """Retrieve historical archived transcript or in flight accumulated logs."""
    org, _task = await authorize_task_org(task_id, caller, db, requested_org_id=org_id)

    transcript_repo = SqlAlchemyTaskTranscriptRepository(db)
    archived = await transcript_repo.get_by_task(org.id, task_id, task_run_id=run_id)

    if archived:
        try:
            terminal_text = gzip.decompress(archived.terminal_log).decode("utf-8")
        except Exception:
            terminal_text = archived.terminal_log.decode("utf-8", errors="replace")
        return TranscriptResponse(
            task_id=task_id,
            terminal_log=terminal_text,
            events=archived.events_json,
            total_lines=archived.total_lines,
        )

    # In flight fallback from Redis Stream
    streamer = get_event_streamer()
    terminal_text, events, total_lines = await streamer.get_stream_transcript(task_id)
    return TranscriptResponse(
        task_id=task_id,
        terminal_log=terminal_text,
        events=events,
        total_lines=total_lines,
    )
