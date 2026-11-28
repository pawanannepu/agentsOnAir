"""PRReviewFinding domain entity."""

import uuid
from dataclasses import dataclass
from datetime import datetime


@dataclass(slots=True)
class PRReviewFinding:
    """Individual finding from a pull request code review."""

    id: uuid.UUID
    review_id: uuid.UUID
    file_path: str
    start_line: int | None
    line_number: int
    side: str  # LEFT, RIGHT
    severity: str  # critical, major, minor, info
    category: str  # security, bug, performance, architecture, style
    title: str
    message: str
    suggested_patch: str | None
    github_comment_id: int | None
    status: str  # open, resolved, outdated, dismissed
    rule_id: uuid.UUID | None = None
    feedback_state: str = "none"  # none, accepted, dismissed
    created_at: datetime | None = None
