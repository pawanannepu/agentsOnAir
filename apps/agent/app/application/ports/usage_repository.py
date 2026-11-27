"""Usage telemetry and monthly spend repository port protocol."""

import uuid
from typing import Protocol

from app.domain.entities.usage import OrgMonthlyUsage, UsageRecordResult


class UsageRepository(Protocol):
    """Repository port for append-only usage events and monthly spend aggregation."""

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
        """Persist usage event, update task_runs, and upsert org_monthly_usage."""
        ...

    async def get_org_monthly_usage(
        self, org_id: uuid.UUID, billing_month: str
    ) -> OrgMonthlyUsage:
        """Return aggregated token and cost totals for (org_id, billing_month)."""
        ...

    async def get_task_run_usage(
        self, org_id: uuid.UUID, task_run_id: uuid.UUID
    ) -> tuple[int, int]:
        """Return (tokens_used, estimated_cost_cents) for a task run."""
        ...
