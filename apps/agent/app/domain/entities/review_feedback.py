"""Review finding feedback and learned preference domain entities."""

import uuid
from dataclasses import dataclass
from datetime import datetime


@dataclass(slots=True)
class ReviewFindingFeedback:
    """Append-only developer feedback event on a PR review finding."""

    id: uuid.UUID
    org_id: uuid.UUID
    repo_id: uuid.UUID
    finding_id: uuid.UUID
    feedback_type: str  # accepted, dismissed
    source: str  # console, github_thread_resolved, github_comment_reply
    reason: str | None
    remember_preference: bool
    actor_id: str
    github_event_id: str | None = None
    created_at: datetime | None = None


@dataclass(slots=True)
class ReviewLearnedPreference:
    """Repository-scoped learned pattern preference with dampening/suppression state."""

    id: uuid.UUID
    org_id: uuid.UUID
    repo_id: uuid.UUID
    rule_id: uuid.UUID | None
    source_feedback_id: uuid.UUID | None
    pattern_key: str
    instruction: str
    dismiss_count: int = 0
    accept_count: int = 0
    consecutive_dismissals: int = 0
    status: str = "active"  # active, dampened, suppressed
    last_feedback_at: datetime | None = None
    created_at: datetime | None = None
    updated_at: datetime | None = None
