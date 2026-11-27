"""Application service for LLM cost accounting and budget checks."""

import uuid
from datetime import UTC, datetime

from app.application.ports.usage_repository import UsageRepository
from app.core.pricing import estimate_cost_cents
from app.domain.entities.task_run import TaskRun
from app.domain.entities.usage import UsageRecordResult
from app.domain.services.policy_evaluator import EffectiveGuardrailPolicy


class UsageTracker:
    """Coordinates ceiling cent accounting, monthly caps, and runtime budgets."""

    def __init__(self, usage_repo: UsageRepository) -> None:
        self._usage_repo = usage_repo

    @staticmethod
    def current_billing_month(now: datetime | None = None) -> str:
        """Return UTC YYYY-MM billing month key."""
        ref = now or datetime.now(UTC)
        return ref.astimezone(UTC).strftime("%Y-%m")

    @staticmethod
    def get_remaining_active_seconds(
        task_run: TaskRun,
        policy: EffectiveGuardrailPolicy,
        now: datetime | None = None,
    ) -> float:
        """Compute remaining active execution seconds excluding paused_seconds."""
        ref_now = now or datetime.now(UTC)
        started_at = task_run.started_at or task_run.created_at or ref_now
        if started_at.tzinfo is None:
            started_at = started_at.replace(tzinfo=UTC)
        elapsed_wall = max(0.0, (ref_now - started_at).total_seconds())
        active_elapsed = max(0.0, elapsed_wall - max(0, task_run.paused_seconds))
        return float(policy.timeout_minutes * 60) - active_elapsed

    async def check_preflight(
        self,
        org_id: uuid.UUID,
        policy: EffectiveGuardrailPolicy,
        task_run: TaskRun | None = None,
        now: datetime | None = None,
    ) -> str | None:
        """Check task cost, monthly org cost, and active runtime before an LLM call."""
        if task_run is not None:
            if self.get_remaining_active_seconds(task_run, policy, now=now) <= 0:
                return "timeout_exceeded"
            if task_run.estimated_cost_cents >= policy.max_task_cost_cents:
                return "budget_exceeded"
            _, run_cost_cents = await self._usage_repo.get_task_run_usage(
                org_id, task_run.id
            )
            effective_run_cost = max(run_cost_cents, task_run.estimated_cost_cents)
            if effective_run_cost >= policy.max_task_cost_cents:
                return "budget_exceeded"

        month = self.current_billing_month(now)
        monthly = await self._usage_repo.get_org_monthly_usage(org_id, month)
        if monthly.total_cost_cents >= policy.max_monthly_org_cost_cents:
            return "budget_exceeded"

        return None

    async def record_call_and_check(
        self,
        org_id: uuid.UUID,
        provider: str,
        model: str,
        operation_type: str,
        prompt_tokens: int,
        completion_tokens: int,
        policy: EffectiveGuardrailPolicy,
        task_id: uuid.UUID | None = None,
        task_run: TaskRun | None = None,
        pr_review_id: uuid.UUID | None = None,
        now: datetime | None = None,
    ) -> tuple[UsageRecordResult, str | None]:
        """Record isolated usage and evaluate postflight budget/runtime caps."""
        cost_cents = estimate_cost_cents(model, prompt_tokens, completion_tokens)
        month = self.current_billing_month(now)
        result = await self._usage_repo.record_usage_isolated(
            org_id=org_id,
            provider=provider,
            model=model,
            operation_type=operation_type,
            prompt_tokens=prompt_tokens,
            completion_tokens=completion_tokens,
            estimated_cost_cents=cost_cents,
            billing_month=month,
            task_id=task_id,
            task_run_id=task_run.id if task_run is not None else None,
            pr_review_id=pr_review_id,
        )

        if task_run is not None:
            if result.task_run_cost_cents >= policy.max_task_cost_cents:
                return result, "budget_exceeded"
            if self.get_remaining_active_seconds(task_run, policy, now=now) <= 0:
                return result, "timeout_exceeded"

        if result.org_month_cost_cents >= policy.max_monthly_org_cost_cents:
            return result, "budget_exceeded"

        return result, None
