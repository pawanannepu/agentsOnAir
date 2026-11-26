"""Task domain entity."""

import uuid
from dataclasses import dataclass, field
from datetime import datetime


@dataclass(slots=True)
class Task:
    """Agent task entity representing requested work."""

    id: uuid.UUID
    org_id: uuid.UUID
    repo_id: uuid.UUID
    title: str
    description: str
    trigger_type: str
    status: str = "queued"
    trigger_metadata: dict = field(default_factory=dict)
    base_branch: str = "main"
    branch_name: str | None = None
    pr_number: int | None = None
    pr_url: str | None = None
    head_commit_sha: str | None = None
    pr_review_status: str | None = None
    created_by_clerk_user_id: str | None = None
    interruption_prompt: str | None = None
    interruption_type: str | None = None
    interruption_options: list | dict | None = None
    interruption_expires_at: datetime | None = None
    created_at: datetime | None = None
    updated_at: datetime | None = None
    deleted_at: datetime | None = None
