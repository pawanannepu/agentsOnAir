"""SQLAlchemy usage repository with isolated per-call commits."""

import uuid
from collections.abc import Callable
from datetime import UTC, datetime

from sqlalchemy import select, update
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.application.ports.usage_repository import UsageRepository
from app.domain.entities.usage import OrgMonthlyUsage, UsageEvent, UsageRecordResult
from app.infrastructure.db import session as db_session_module
from app.infrastructure.db.base import uuid7
from app.infrastructure.db.models.org_monthly_usage import OrgMonthlyUsageModel
from app.infrastructure.db.models.task_run import TaskRunModel
from app.infrastructure.db.models.usage_event import UsageEventModel


class SqlAlchemyUsageRepository(UsageRepository):
    """Async SQLAlchemy adapter committing LLM usage in isolated transactions."""

    def __init__(
        self,
        session: AsyncSession | None = None,
        session_factory: Callable[[], AsyncSession] | None = None,
        isolated: bool = True,
    ) -> None:
        self._session = session
        self._session_factory = session_factory
        self._isolated = isolated

    def _get_session_factory(self) -> Callable[[], AsyncSession]:
        if self._session_factory is not None:
            return self._session_factory
        return db_session_module.async_session_factory

    async def _write_usage(
        self,
        db: AsyncSession,
        *,
        org_id: uuid.UUID,
        provider: str,
        model: str,
        operation_type: str,
        prompt_tokens: int,
        completion_tokens: int,
        estimated_cost_cents: int,
        billing_month: str,
        task_id: uuid.UUID | None,
        task_run_id: uuid.UUID | None,
        pr_review_id: uuid.UUID | None,
        now: datetime,
    ) -> UsageRecordResult:
        total_tokens = prompt_tokens + completion_tokens
        event_model = UsageEventModel(
            id=uuid7(),
            org_id=org_id,
            task_id=task_id,
            task_run_id=task_run_id,
            pr_review_id=pr_review_id,
            provider=provider,
            model=model,
            operation_type=operation_type,
            prompt_tokens=prompt_tokens,
            completion_tokens=completion_tokens,
            estimated_cost_cents=estimated_cost_cents,
            created_at=now,
        )
        db.add(event_model)

        run_tokens = 0
        run_cost_cents = 0
        if task_run_id is not None:
            run_stmt = (
                update(TaskRunModel)
                .where(
                    TaskRunModel.id == task_run_id,
                    TaskRunModel.org_id == org_id,
                )
                .values(
                    prompt_tokens=TaskRunModel.prompt_tokens + prompt_tokens,
                    completion_tokens=TaskRunModel.completion_tokens
                    + completion_tokens,
                    tokens_used=TaskRunModel.tokens_used + total_tokens,
                    estimated_cost_cents=(
                        TaskRunModel.estimated_cost_cents + estimated_cost_cents
                    ),
                    updated_at=now,
                )
                .returning(
                    TaskRunModel.tokens_used,
                    TaskRunModel.estimated_cost_cents,
                )
            )
            row = (await db.execute(run_stmt)).first()
            if row is not None:
                run_tokens = int(row[0])
                run_cost_cents = int(row[1])

        upsert_stmt = (
            pg_insert(OrgMonthlyUsageModel)
            .values(
                id=uuid7(),
                org_id=org_id,
                billing_month=billing_month,
                total_tokens=total_tokens,
                total_cost_cents=estimated_cost_cents,
                updated_at=now,
            )
            .on_conflict_do_update(
                index_elements=[
                    OrgMonthlyUsageModel.org_id,
                    OrgMonthlyUsageModel.billing_month,
                ],
                set_={
                    "total_tokens": OrgMonthlyUsageModel.total_tokens + total_tokens,
                    "total_cost_cents": (
                        OrgMonthlyUsageModel.total_cost_cents + estimated_cost_cents
                    ),
                    "updated_at": now,
                },
            )
            .returning(
                OrgMonthlyUsageModel.total_tokens,
                OrgMonthlyUsageModel.total_cost_cents,
            )
        )
        monthly_row = (await db.execute(upsert_stmt)).one()
        org_tokens = int(monthly_row[0])
        org_cost_cents = int(monthly_row[1])

        return UsageRecordResult(
            event=UsageEvent(
                id=event_model.id,
                org_id=org_id,
                task_id=task_id,
                task_run_id=task_run_id,
                pr_review_id=pr_review_id,
                provider=provider,
                model=model,
                operation_type=operation_type,
                prompt_tokens=prompt_tokens,
                completion_tokens=completion_tokens,
                estimated_cost_cents=estimated_cost_cents,
                created_at=now,
            ),
            task_run_tokens_used=run_tokens,
            task_run_cost_cents=run_cost_cents,
            org_month_tokens=org_tokens,
            org_month_cost_cents=org_cost_cents,
        )

    async def record_usage_isolated(
        self,
        org_id: uuid.UUID,
        provider: str,
        model: str,
        operation_type: str,
        prompt_tokens: int,
        completion_tokens: int,
        estimated_cost_cents: int,
        billing_month: str,
        task_id: uuid.UUID | None = None,
        task_run_id: uuid.UUID | None = None,
        pr_review_id: uuid.UUID | None = None,
    ) -> UsageRecordResult:
        now = datetime.now(UTC)
        if self._session is not None and not self._isolated:
            result = await self._write_usage(
                self._session,
                org_id=org_id,
                provider=provider,
                model=model,
                operation_type=operation_type,
                prompt_tokens=prompt_tokens,
                completion_tokens=completion_tokens,
                estimated_cost_cents=estimated_cost_cents,
                billing_month=billing_month,
                task_id=task_id,
                task_run_id=task_run_id,
                pr_review_id=pr_review_id,
                now=now,
            )
            await self._session.flush()
            return result

        factory = self._get_session_factory()
        async with factory() as iso_session:
            result = await self._write_usage(
                iso_session,
                org_id=org_id,
                provider=provider,
                model=model,
                operation_type=operation_type,
                prompt_tokens=prompt_tokens,
                completion_tokens=completion_tokens,
                estimated_cost_cents=estimated_cost_cents,
                billing_month=billing_month,
                task_id=task_id,
                task_run_id=task_run_id,
                pr_review_id=pr_review_id,
                now=now,
            )
            await iso_session.commit()
            return result

    async def get_org_monthly_usage(
        self, org_id: uuid.UUID, billing_month: str
    ) -> OrgMonthlyUsage:
        stmt = select(OrgMonthlyUsageModel).where(
            OrgMonthlyUsageModel.org_id == org_id,
            OrgMonthlyUsageModel.billing_month == billing_month,
        )
        if self._session is not None:
            model = (await self._session.execute(stmt)).scalar_one_or_none()
        else:
            factory = self._get_session_factory()
            async with factory() as iso_session:
                model = (await iso_session.execute(stmt)).scalar_one_or_none()

        if model is None:
            return OrgMonthlyUsage(
                org_id=org_id,
                billing_month=billing_month,
                total_tokens=0,
                total_cost_cents=0,
            )
        return OrgMonthlyUsage(
            org_id=model.org_id,
            billing_month=model.billing_month,
            total_tokens=int(model.total_tokens),
            total_cost_cents=int(model.total_cost_cents),
            updated_at=model.updated_at,
        )

    async def get_task_run_usage(
        self, org_id: uuid.UUID, task_run_id: uuid.UUID
    ) -> tuple[int, int]:
        stmt = select(
            TaskRunModel.tokens_used, TaskRunModel.estimated_cost_cents
        ).where(
            TaskRunModel.org_id == org_id,
            TaskRunModel.id == task_run_id,
        )
        if self._session is not None:
            row = (await self._session.execute(stmt)).first()
        else:
            factory = self._get_session_factory()
            async with factory() as iso_session:
                row = (await iso_session.execute(stmt)).first()
        if row is None:
            return 0, 0
        return int(row[0]), int(row[1])
