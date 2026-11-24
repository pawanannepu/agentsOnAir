"""PullRequestReview domain entity."""

import uuid
from dataclasses import dataclass
from datetime import datetime


@dataclass(slots=True)
class PullRequestReview:
    """Code review of an external or internal pull request."""

    id: uuid.UUID
    org_id: uuid.UUID
    repo_id: uuid.UUID
    task_id: uuid.UUID | None
    pr_number: int
    pr_title: str
    pr_author: str
    head_commit_sha: str
    base_commit_sha: str
    status: str  # pending, analyzing, reviewing, posting, completed, failed
    verdict: str | None  # approved, changes_requested, comment
    summary: str | None
    github_review_id: int | None
    context_token_count: int
    model_name: str
    execution_duration_ms: int | None
    error_message: str | None
    created_at: datetime | None = None
    updated_at: datetime | None = None
