"""Repository port protocol for finding feedback and learned preferences."""

import uuid
from datetime import datetime
from typing import Protocol

from app.domain.entities.pr_review_finding import PRReviewFinding
from app.domain.entities.pull_request_review import PullRequestReview
from app.domain.entities.review_feedback import (
    ReviewFindingFeedback,
    ReviewLearnedPreference,
)


class ReviewFeedbackRepository(Protocol):
    """Port interface for review finding feedback and learned preferences."""

    async def get_finding_with_review(
        self, org_id: uuid.UUID, finding_id: uuid.UUID
    ) -> tuple[PRReviewFinding, PullRequestReview]:
        """Load a finding and its parent PR review scoped to org_id."""
        ...

    async def find_finding_by_github_comment_id(
        self, repo_id: uuid.UUID, github_comment_id: int
    ) -> tuple[PRReviewFinding, PullRequestReview] | None:
        """Locate a finding by its GitHub inline comment ID within a repository."""
        ...

    async def record_feedback_event(
        self,
        org_id: uuid.UUID,
        repo_id: uuid.UUID,
        finding_id: uuid.UUID,
        feedback_type: str,
        source: str,
        reason: str | None,
        remember_preference: bool,
        actor_id: str,
        github_event_id: str | None = None,
    ) -> tuple[ReviewFindingFeedback | None, bool]:
        """Append feedback event; returns `(event, True)` if new or `(None, False)`."""
        ...

    async def update_finding_feedback_state(
        self,
        finding_id: uuid.UUID,
        feedback_state: str,
        status: str,
    ) -> PRReviewFinding:
        """Persist updated feedback_state and status on a finding."""
        ...

    async def get_preference_with_feedback(
        self,
        org_id: uuid.UUID,
        repo_id: uuid.UUID,
        pattern_key: str,
        *,
        for_update: bool = False,
    ) -> tuple[ReviewLearnedPreference, ReviewFindingFeedback | None] | None:
        """Load learned preference for (repo_id, pattern_key), optionally with lock."""
        ...

    async def upsert_preference(
        self,
        org_id: uuid.UUID,
        repo_id: uuid.UUID,
        rule_id: uuid.UUID | None,
        source_feedback_id: uuid.UUID | None,
        pattern_key: str,
        instruction: str,
        dismiss_count: int,
        accept_count: int,
        consecutive_dismissals: int,
        status: str,
        last_feedback_at: datetime,
    ) -> ReviewLearnedPreference:
        """Create or update a repository learned preference row."""
        ...

    async def list_preferences_for_repo(
        self,
        org_id: uuid.UUID,
        repo_id: uuid.UUID,
        status: str | None = None,
        page: int = 1,
        page_size: int = 50,
    ) -> tuple[list[tuple[ReviewLearnedPreference, ReviewFindingFeedback | None]], int]:
        """List learned preferences for a repository with optional status filter."""
        ...

    async def get_preference_by_id(
        self,
        org_id: uuid.UUID,
        repo_id: uuid.UUID,
        pref_id: uuid.UUID,
    ) -> ReviewLearnedPreference:
        """Fetch a learned preference scoped to org and repository."""
        ...

    async def update_preference_admin(
        self,
        org_id: uuid.UUID,
        repo_id: uuid.UUID,
        pref_id: uuid.UUID,
        status: str,
        consecutive_dismissals: int,
        instruction: str | None = None,
    ) -> ReviewLearnedPreference:
        """Admin update of preference status, consecutive_dismissals, & instruction."""
        ...
