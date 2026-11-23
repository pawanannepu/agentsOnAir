"""ReviewIteration domain entity."""

import uuid
from dataclasses import dataclass, field
from datetime import datetime


@dataclass(slots=True)
class ReviewIteration:
    """Review iteration entity tracking reviewer evaluations and findings."""

    id: uuid.UUID
    org_id: uuid.UUID
    task_run_id: uuid.UUID
    cycle_number: int
    verdict: str  # approved, changes_requested
    summary: str
    findings: list[dict] = field(default_factory=list)
    blocking_count: int = 0
    non_blocking_count: int = 0
    diff_snapshot: str | None = None
    created_at: datetime | None = None
