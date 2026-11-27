"""Tasks, streaming, interventions, and approval gate API endpoints."""

import gzip
import json
import uuid
from datetime import UTC, datetime
from typing import Annotated, Any, Literal

from fastapi import APIRouter, Depends, Header, HTTPException, Query, Request
from pydantic import BaseModel, Field
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession
from sse_starlette.event import ServerSentEvent
from sse_starlette.sse import EventSourceResponse

from app.api.dependencies.auth import (
    authorize_task_org,
    get_current_clerk_user,
    require_org_admin,
    resolve_caller_org,
)
from app.core.clerk_auth import ClerkUserContext
from app.domain.entities.organization import Organization
from app.domain.exceptions import ConcurrencyError, NotFoundError
from app.domain.services.policy_evaluator import PolicyEvaluator
from app.infrastructure.db.models.repository import RepositoryModel
from app.infrastructure.db.models.sandbox_run import SandboxRunModel
from app.infrastructure.db.models.task_run import TaskRunModel
from app.infrastructure.db.repositories.audit_log_repository import (
    SqlAlchemyAuditLogRepository,
)
from app.infrastructure.db.repositories.review_iteration_repository import (
    SqlAlchemyReviewIterationRepository,
)
from app.infrastructure.db.repositories.task_approval_repository import (
    SqlAlchemyTaskApprovalRepository,
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
    tokens_used: int = 0
    estimated_cost_cents: int = 0
    paused_seconds: int = 0
    review_iterations: list[ReviewIterationResponse] = Field(default_factory=list)


class PendingApprovalResponse(BaseModel):
    approval_id: uuid.UUID
    risk_category: str
    action_type: str
    action_summary: str
    action_payload: dict[str, Any]
    expires_at: str


class BudgetSummaryResponse(BaseModel):
    task_cost_cents: int
    max_task_cost_cents: int
    tokens_used: int
    partial_diff: str | None = None


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
    pending_approval: PendingApprovalResponse | None = None
    budget_summary: BudgetSummaryResponse | None = None
    runs: list[TaskRunResponse] = Field(default_factory=list)


class InterveneRequest(BaseModel):
    message: str = Field(..., min_length=1)
    action_type: str = Field("guidance", pattern="^(guidance|abort)$")


class RespondRequest(BaseModel):
    response: str = Field(..., min_length=1)
    selected_option: str | None = None


class ApprovalDecisionRequest(BaseModel):
    decision: Literal["approved", "rejected"]
    note: str | None = None


class ApprovalDecisionResponse(BaseModel):
    approval_id: uuid.UUID
    status: str
    task_status: str


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
    """Retrieve task details, runs, pending approvals, and budget summary."""
    org, task = await authorize_task_org(
        task_id,
        caller,
        db,
        requested_org_id=org_id,
    )

    repo_stmt = select(RepositoryModel).where(
        RepositoryModel.id == task.repo_id,
        RepositoryModel.org_id == org.id,
    )
    repo_model = (await db.execute(repo_stmt)).scalar_one_or_none()
    repo_full_name = repo_model.full_name if repo_model else None
    effective_policy = PolicyEvaluator.merge_policy(
        org.settings,
        repo_model.config if repo_model else None,
    )

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
                tokens_used=run.tokens_used,
                estimated_cost_cents=run.estimated_cost_cents,
                paused_seconds=run.paused_seconds,
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

    approval_repo = SqlAlchemyTaskApprovalRepository(db)
    pending_approval_model = await approval_repo.get_pending_for_task(org.id, task.id)
    pending_approval = (
        PendingApprovalResponse(
            approval_id=pending_approval_model.id,
            risk_category=pending_approval_model.risk_category,
            action_type=pending_approval_model.action_type,
            action_summary=pending_approval_model.action_summary,
            action_payload=pending_approval_model.action_payload,
            expires_at=pending_approval_model.expires_at.isoformat(),
        )
        if pending_approval_model is not None
        else None
    )

    latest_run = runs_models[-1] if runs_models else None
    latest_cp = latest_run.checkpoint_state if latest_run else {}
    partial_diff = (
        latest_cp.get("partial_diff") if isinstance(latest_cp, dict) else None
    )
    budget_summary = BudgetSummaryResponse(
        task_cost_cents=latest_run.estimated_cost_cents if latest_run else 0,
        max_task_cost_cents=effective_policy.max_task_cost_cents,
        tokens_used=latest_run.tokens_used if latest_run else 0,
        partial_diff=partial_diff if isinstance(partial_diff, str) else None,
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
        pending_approval=pending_approval,
        budget_summary=budget_summary,
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
    org, task = await authorize_task_org(task_id, caller, db, requested_org_id=org_id)

    # Approval gates cannot be bypassed via /respond
    if task.interruption_type == "approval":
        raise HTTPException(
            status_code=409,
            detail=(
                "Approval gates require org:admin decision via "
                "/approvals/{approval_id}/decision"
            ),
        )

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


@router.post(
    "/{task_id}/approvals/{approval_id}/decision",
    response_model=ApprovalDecisionResponse,
)
async def decide_task_approval(
    task_id: uuid.UUID,
    approval_id: uuid.UUID,
    payload: ApprovalDecisionRequest,
    auth_ctx: Annotated[
        tuple[ClerkUserContext, Organization], Depends(require_org_admin)
    ],
    db: Annotated[AsyncSession, Depends(get_db)],
):
    """Submit org:admin approval or rejection for a pending risky action."""
    caller, org = auth_ctx
    _org, task = await authorize_task_org(task_id, caller, db, requested_org_id=org.id)

    approval_repo = SqlAlchemyTaskApprovalRepository(db)
    try:
        approval = await approval_repo.get_by_id(org.id, approval_id)
    except NotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc

    if approval.task_id != task.id:
        raise HTTPException(
            status_code=404,
            detail=f"Approval {approval_id} not found for task {task_id}",
        )

    # Optimistic concurrency guard on task_runs.version paired with claim
    run_stmt = (
        select(TaskRunModel)
        .where(
            TaskRunModel.id == approval.task_run_id,
            TaskRunModel.org_id == org.id,
        )
        .limit(1)
    )
    run_model = (await db.execute(run_stmt)).scalar_one_or_none()
    if run_model is None:
        raise HTTPException(status_code=404, detail="Associated task run not found")

    decided = await approval_repo.decide_atomic(
        org_id=org.id,
        task_id=task.id,
        approval_id=approval.id,
        decision=payload.decision,
        decided_by_clerk_user_id=caller.user_id,
        decision_note=payload.note,
    )
    if decided is None:
        raise HTTPException(
            status_code=409,
            detail="Approval has already been decided or expired",
        )

    now = datetime.now(UTC)
    expected_version = run_model.version
    version_stmt = (
        update(TaskRunModel)
        .where(
            TaskRunModel.id == run_model.id,
            TaskRunModel.version == expected_version,
        )
        .values(version=expected_version + 1, updated_at=now)
        .returning(TaskRunModel.id)
    )
    bumped = (await db.execute(version_stmt)).scalar_one_or_none()
    if bumped is None:
        await db.rollback()
        raise HTTPException(
            status_code=409,
            detail="Concurrent task run state transition detected",
        )

    task_repo = SqlAlchemyTaskRepository(db)
    audit_repo = SqlAlchemyAuditLogRepository(db)
    streamer = get_event_streamer()

    if payload.decision == "approved":
        try:
            await task_repo.claim_interruption(
                org.id, task.id, new_status="in_progress"
            )
        except ConcurrencyError as exc:
            await db.rollback()
            raise HTTPException(status_code=409, detail=str(exc)) from exc

        await audit_repo.record_event(
            org_id=org.id,
            actor_type="user",
            actor_id=caller.user_id,
            action="task_approval_approved",
            target_type="task_approval",
            target_id=approval.id,
            payload_after={
                "task_id": str(task.id),
                "decision": "approved",
                "note": payload.note,
                "action_hash": approval.action_hash,
            },
        )
        await streamer.append_event(
            task.id,
            "task.resumed",
            {
                "approval_id": str(approval.id),
                "decision": "approved",
            },
        )
        await db.commit()

        await get_task_queue().enqueue_resume_task(
            org_id=org.id,
            task_id=task.id,
            task_run_id=approval.task_run_id,
            response={"approval_id": str(approval.id), "decision": "approved"},
        )
        final_task_status = "in_progress"
    else:
        await task_repo.clear_interruption(org.id, task.id, new_status="failed")
        await db.execute(
            update(TaskRunModel)
            .where(TaskRunModel.id == run_model.id)
            .values(
                status="failed",
                failure_reason="approval_rejected",
                completed_at=now,
                updated_at=now,
            )
        )
        sbx_stmt = select(SandboxRunModel).where(
            SandboxRunModel.task_run_id == run_model.id,
            SandboxRunModel.org_id == org.id,
        )
        sbx_model = (await db.execute(sbx_stmt)).scalar_one_or_none()
        if sbx_model and sbx_model.status == "active":
            sbx_model.status = "terminated"
            sbx_model.terminated_at = now
            sbx_model.updated_at = now
            await get_sandbox_registry().terminate_if_present(sbx_model.sandbox_id)

        await audit_repo.record_event(
            org_id=org.id,
            actor_type="user",
            actor_id=caller.user_id,
            action="task_approval_rejected",
            target_type="task_approval",
            target_id=approval.id,
            payload_after={
                "task_id": str(task.id),
                "decision": "rejected",
                "note": payload.note,
                "failure_reason": "approval_rejected",
            },
        )
        await streamer.append_event(
            task.id,
            "task.status",
            {
                "status": "failed",
                "failure_reason": "approval_rejected",
                "reason": "approval_rejected",
            },
        )
        await db.commit()
        final_task_status = "failed"

    return ApprovalDecisionResponse(
        approval_id=approval.id,
        status=decided.status,
        task_status=final_task_status,
    )


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

    streamer = get_event_streamer()
    terminal_text, events, total_lines = await streamer.get_stream_transcript(task_id)
    return TranscriptResponse(
        task_id=task_id,
        terminal_log=terminal_text,
        events=events,
        total_lines=total_lines,
    )
