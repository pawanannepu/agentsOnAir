"""ARQ background worker functions for task resumption and interruption watchdogs."""

import gzip
import logging
import uuid
from datetime import UTC, datetime
from typing import Any

from arq.connections import RedisSettings
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.application.ports.event_streamer import EventStreamer
from app.core.config import settings
from app.infrastructure.db.models.sandbox_run import SandboxRunModel
from app.infrastructure.db.models.task import TaskModel
from app.infrastructure.db.models.task_approval import TaskApprovalModel
from app.infrastructure.db.models.task_run import TaskRunModel
from app.infrastructure.db.repositories.audit_log_repository import (
    SqlAlchemyAuditLogRepository,
)
from app.infrastructure.db.repositories.task_transcript_repository import (
    SqlAlchemyTaskTranscriptRepository,
)
from app.infrastructure.db.session import async_session_factory
from app.infrastructure.events.redis_streamer import get_event_streamer
from app.infrastructure.sandbox.factory import get_sandbox_provider
from app.infrastructure.sandbox.registry import SandboxRegistry, get_sandbox_registry

logger = logging.getLogger(__name__)


async def handle_interruption_timeout(
    db: AsyncSession,
    org_id: uuid.UUID,
    task_id: uuid.UUID,
    expected_expires_at: datetime | None = None,
    *,
    event_streamer: EventStreamer | None = None,
    sandbox_registry: SandboxRegistry | None = None,
) -> bool:
    """Expire an awaiting_input task (approval or clarification) atomically."""
    stmt = (
        select(TaskModel)
        .where(
            TaskModel.id == task_id,
            TaskModel.org_id == org_id,
            TaskModel.deleted_at.is_(None),
        )
        .with_for_update()
    )
    task_model = (await db.execute(stmt)).scalar_one_or_none()
    if not task_model or task_model.status != "awaiting_input":
        return False

    if (
        expected_expires_at is not None
        and task_model.interruption_expires_at is not None
        and abs(
            (task_model.interruption_expires_at - expected_expires_at).total_seconds()
        )
        > 5
    ):
        return False

    now = datetime.now(UTC)
    is_approval = task_model.interruption_type == "approval"
    failure_reason = "approval_expired" if is_approval else "interruption_timeout"

    # Atomically claim any pending approval row before failing the task
    if is_approval:
        exp_stmt = (
            update(TaskApprovalModel)
            .where(
                TaskApprovalModel.task_id == task_id,
                TaskApprovalModel.org_id == org_id,
                TaskApprovalModel.status == "pending",
            )
            .values(status="expired", decided_at=now)
            .returning(TaskApprovalModel.id)
        )
        expired_approval_id = (await db.execute(exp_stmt)).scalar_one_or_none()
        if expired_approval_id is None:
            return False

    task_model.status = "failed"
    task_model.interruption_prompt = None
    task_model.interruption_type = None
    task_model.interruption_options = None
    task_model.interruption_expires_at = None
    task_model.updated_at = now

    run_stmt = (
        select(TaskRunModel)
        .where(
            TaskRunModel.task_id == task_id,
            TaskRunModel.org_id == org_id,
        )
        .order_by(TaskRunModel.run_number.desc())
    )
    run_model = (await db.execute(run_stmt)).scalars().first()
    if run_model and run_model.status not in ("completed", "failed", "cancelled"):
        run_model.status = "failed"
        run_model.failure_reason = failure_reason
        run_model.version += 1
        run_model.completed_at = now
        run_model.updated_at = now

        sbx_stmt = select(SandboxRunModel).where(
            SandboxRunModel.task_run_id == run_model.id,
            SandboxRunModel.org_id == org_id,
        )
        sbx_model = (await db.execute(sbx_stmt)).scalar_one_or_none()
        if sbx_model and sbx_model.status == "active":
            sbx_model.status = "terminated"
            sbx_model.exit_code = 124
            sbx_model.terminated_at = now
            sbx_model.updated_at = now
            reg = sandbox_registry or get_sandbox_registry()
            await reg.terminate_if_present(sbx_model.sandbox_id)

    audit_repo = SqlAlchemyAuditLogRepository(db)
    await audit_repo.record_event(
        org_id=org_id,
        actor_type="system",
        actor_id="arq_watchdog",
        action="task_approval_expired" if is_approval else "task_interruption_expired",
        target_type="task",
        target_id=task_id,
        payload_after={"failure_reason": failure_reason, "reason": failure_reason},
    )

    streamer = event_streamer or get_event_streamer()
    await streamer.append_event(
        task_id,
        "task.status",
        {
            "status": "failed",
            "failure_reason": failure_reason,
            "reason": failure_reason,
        },
    )

    if run_model is not None:
        terminal_text, events_json, total_lines = await streamer.get_stream_transcript(
            task_id
        )
        compressed = gzip.compress(terminal_text.encode("utf-8"))
        transcript_repo = SqlAlchemyTaskTranscriptRepository(db)
        await transcript_repo.create_or_update(
            org_id=org_id,
            task_id=task_id,
            task_run_id=run_model.id,
            terminal_log=compressed,
            events_json=events_json,
            total_lines=total_lines,
        )

    await db.flush()
    return True


async def interruption_timeout_watchdog(
    ctx: dict[str, Any],
    org_id_str: str,
    task_id_str: str,
    expected_expires_at_iso: str | None = None,
) -> bool:
    """ARQ delayed job expiring unanswered interrupts."""
    org_id = uuid.UUID(org_id_str)
    task_id = uuid.UUID(task_id_str)
    expected_dt = (
        datetime.fromisoformat(expected_expires_at_iso)
        if expected_expires_at_iso
        else None
    )
    async with async_session_factory() as db:
        expired = await handle_interruption_timeout(
            db,
            org_id,
            task_id,
            expected_expires_at=expected_dt,
        )
        await db.commit()
        return expired


async def resume_task_job(
    ctx: dict[str, Any],
    org_id_str: str,
    task_id_str: str,
    task_run_id_str: str | None = None,
    intervention_id_str: str | None = None,
    response: str | dict[str, Any] | None = None,
) -> dict[str, str]:
    """ARQ background job resuming an interrupted LangGraph task execution."""
    from app.application.use_cases.run_autonomous_loop import (
        RunAutonomousLoopUseCase,
    )
    from app.infrastructure.db.repositories.organization_repository import (
        SqlAlchemyOrganizationRepository,
    )
    from app.infrastructure.db.repositories.repository_repository import (
        SqlAlchemyRepositoryRepository,
    )
    from app.infrastructure.db.repositories.review_iteration_repository import (
        SqlAlchemyReviewIterationRepository,
    )
    from app.infrastructure.db.repositories.sandbox_run_repository import (
        SqlAlchemySandboxRunRepository,
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
    from app.infrastructure.db.repositories.task_run_repository import (
        SqlAlchemyTaskRunRepository,
    )
    from app.infrastructure.db.repositories.usage_repository import (
        SqlAlchemyUsageRepository,
    )
    from app.infrastructure.github.github_service import GitHubService
    from app.infrastructure.llm.agents import ForgeCoderAgent, ReviewerCriticAgent

    org_id = uuid.UUID(org_id_str)
    task_id = uuid.UUID(task_id_str)
    intervention_id = uuid.UUID(intervention_id_str) if intervention_id_str else None

    async with async_session_factory() as db:
        org_repo = SqlAlchemyOrganizationRepository(db)
        org = await org_repo.get_by_id(org_id)
        sandbox_provider = get_sandbox_provider(org.settings.get("sandbox_provider"))

        use_case = RunAutonomousLoopUseCase(
            task_repo=SqlAlchemyTaskRepository(db),
            task_run_repo=SqlAlchemyTaskRunRepository(db),
            sandbox_run_repo=SqlAlchemySandboxRunRepository(db),
            review_iteration_repo=SqlAlchemyReviewIterationRepository(db),
            audit_log_repo=SqlAlchemyAuditLogRepository(db),
            repository_repo=SqlAlchemyRepositoryRepository(db),
            sandbox_provider=sandbox_provider,
            github_gateway=GitHubService(
                app_id=settings.GITHUB_APP_ID,
                private_key=settings.GITHUB_APP_PRIVATE_KEY,
            ),
            forge_agent=ForgeCoderAgent(api_key=settings.ANTHROPIC_API_KEY),
            reviewer_critic=ReviewerCriticAgent(api_key=settings.ANTHROPIC_API_KEY),
            event_streamer=get_event_streamer(),
            task_transcript_repo=SqlAlchemyTaskTranscriptRepository(db),
            task_intervention_repo=SqlAlchemyTaskInterventionRepository(db),
            sandbox_registry=get_sandbox_registry(),
            organization_repo=org_repo,
            task_approval_repo=SqlAlchemyTaskApprovalRepository(db),
            usage_repo=SqlAlchemyUsageRepository(),
        )
        resumed = await use_case.resume(
            org_id=org_id,
            task_id=task_id,
            response=response if response is not None else "",
            intervention_id=intervention_id,
        )
        await db.commit()
        return {"task_id": str(resumed.id), "status": resumed.status}


class WorkerSettings:
    """ARQ worker configuration for agentsOnAir background execution."""

    functions = [resume_task_job, interruption_timeout_watchdog]
    redis_settings = RedisSettings.from_dsn(settings.REDIS_URL)
