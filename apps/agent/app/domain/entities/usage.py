"""Usage telemetry and monthly spend domain entities."""

import uuid
from dataclasses import dataclass
from datetime import datetime


@dataclass(slots=True)
class UsageEvent:
    """Immutable token and cost event for a single LLM call."""

    id: uuid.UUID
    org_id: uuid.UUID
    provider: str
    model: str
    operation_type: str
    prompt_tokens: int
    completion_tokens: int
    estimated_cost_cents: int
    task_id: uuid.UUID | None = None
    task_run_id: uuid.UUID | None = None
    pr_review_id: uuid.UUID | None = None
    created_at: datetime | None = None


@dataclass(slots=True)
class OrgMonthlyUsage:
    """Aggregated organization spend and token consumption for a UTC billing month."""

    org_id: uuid.UUID
    billing_month: str
    total_tokens: int = 0
    total_cost_cents: int = 0
    updated_at: datetime | None = None


@dataclass(slots=True)
class UsageRecordResult:
    """Updated counters returned after recording an isolated usage transaction."""

    event: UsageEvent
    task_run_tokens_used: int
    task_run_cost_cents: int
    org_month_tokens: int
    org_month_cost_cents: int
