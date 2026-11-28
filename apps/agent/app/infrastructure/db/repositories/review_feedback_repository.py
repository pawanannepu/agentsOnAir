"""SQLAlchemy implementation of ReviewFeedbackRepository."""

import uuid
from datetime import UTC, datetime

from sqlalchemy import func, select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.application.ports.review_feedback_repository import ReviewFeedbackRepository
from app.domain.entities.pr_review_finding import PRReviewFinding
from app.domain.entities.pull_request_review import PullRequestReview
from app.domain.entities.review_feedback import (
    ReviewFindingFeedback,
    ReviewLearnedPreference,
)
from app.domain.exceptions import NotFoundError
from app.infrastructure.db.base import uuid7
from app.infrastructure.db.models.pr_review_finding import PRReviewFindingModel
from app.infrastructure.db.models.pull_request_review import PullRequestReviewModel
from app.infrastructure.db.models.repository import RepositoryModel
from app.infrastructure.db.models.review_finding_feedback import (
    ReviewFindingFeedbackModel,
)
from app.infrastructure.db.models.review_learned_preference import (
    ReviewLearnedPreferenceModel,
)
from app.infrastructure.db.repositories.pr_review_repository import (
    _finding_to_entity,
    _review_to_entity,
)


def _feedback_to_entity(model: ReviewFindingFeedbackModel) -> ReviewFindingFeedback:
    return ReviewFindingFeedback(
        id=model.id,
        org_id=model.org_id,
        repo_id=model.repo_id,
        finding_id=model.finding_id,
        feedback_type=model.feedback_type,
        source=model.source,
        reason=model.reason,
        remember_preference=model.remember_preference,
        actor_id=model.actor_id,
        github_event_id=model.github_event_id,
        created_at=model.created_at,
    )


def _preference_to_entity(
    model: ReviewLearnedPreferenceModel,
) -> ReviewLearnedPreference:
    return ReviewLearnedPreference(
        id=model.id,
        org_id=model.org_id,
        repo_id=model.repo_id,
        rule_id=model.rule_id,
        source_feedback_id=model.source_feedback_id,
        pattern_key=model.pattern_key,
        instruction=model.instruction,
        dismiss_count=model.dismiss_count,
        accept_count=model.accept_count,
        consecutive_dismissals=model.consecutive_dismissals,
        status=model.status,
        last_feedback_at=model.last_feedback_at,
        created_at=model.created_at,
        updated_at=model.updated_at,
    )


class SqlAlchemyReviewFeedbackRepository(ReviewFeedbackRepository):
    """Async SQLAlchemy adapter for finding feedback and learned preferences."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def get_finding_with_review(
        self, org_id: uuid.UUID, finding_id: uuid.UUID
    ) -> tuple[PRReviewFinding, PullRequestReview]:
        stmt = (
            select(PRReviewFindingModel, PullRequestReviewModel)
            .join(
                PullRequestReviewModel,
                PRReviewFindingModel.review_id == PullRequestReviewModel.id,
            )
            .where(
                PRReviewFindingModel.id == finding_id,
                PullRequestReviewModel.org_id == org_id,
            )
        )
        row = (await self._session.execute(stmt)).first()
        if row is None:
            raise NotFoundError(f"Finding {finding_id} not found in organization")
        finding_model, review_model = row
        return _finding_to_entity(finding_model), _review_to_entity(review_model)

    async def find_finding_by_github_comment_id(
        self, repo_id: uuid.UUID, github_comment_id: int
    ) -> tuple[PRReviewFinding, PullRequestReview] | None:
        stmt = (
            select(PRReviewFindingModel, PullRequestReviewModel)
            .join(
                PullRequestReviewModel,
                PRReviewFindingModel.review_id == PullRequestReviewModel.id,
            )
            .where(
                PullRequestReviewModel.repo_id == repo_id,
                PRReviewFindingModel.github_comment_id == github_comment_id,
            )
            .order_by(PRReviewFindingModel.created_at.desc())
            .limit(1)
        )
        row = (await self._session.execute(stmt)).first()
        if row is None:
            return None
        finding_model, review_model = row
        return _finding_to_entity(finding_model), _review_to_entity(review_model)

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
        event_id = uuid7()
        now = datetime.now(UTC)

        if github_event_id is not None:
            stmt = (
                pg_insert(ReviewFindingFeedbackModel)
                .values(
                    id=event_id,
                    org_id=org_id,
                    repo_id=repo_id,
                    finding_id=finding_id,
                    feedback_type=feedback_type,
                    source=source,
                    reason=reason,
                    remember_preference=remember_preference,
                    actor_id=actor_id,
                    github_event_id=github_event_id,
                    created_at=now,
                )
                .on_conflict_do_nothing(
                    index_elements=["github_event_id"],
                    index_where=ReviewFindingFeedbackModel.github_event_id.is_not(None),
                )
                .returning(ReviewFindingFeedbackModel)
            )
            inserted = (await self._session.execute(stmt)).scalar_one_or_none()
            if inserted is None:
                return None, False
            await self._session.flush()
            return _feedback_to_entity(inserted), True

        model = ReviewFindingFeedbackModel(
            id=event_id,
            org_id=org_id,
            repo_id=repo_id,
            finding_id=finding_id,
            feedback_type=feedback_type,
            source=source,
            reason=reason,
            remember_preference=remember_preference,
            actor_id=actor_id,
            github_event_id=None,
            created_at=now,
        )
        self._session.add(model)
        await self._session.flush()
        return _feedback_to_entity(model), True

    async def update_finding_feedback_state(
        self,
        finding_id: uuid.UUID,
        feedback_state: str,
        status: str,
    ) -> PRReviewFinding:
        stmt = select(PRReviewFindingModel).where(PRReviewFindingModel.id == finding_id)
        model = (await self._session.execute(stmt)).scalar_one_or_none()
        if model is None:
            raise NotFoundError(f"Finding {finding_id} not found")
        model.feedback_state = feedback_state
        model.status = status
        await self._session.flush()
        return _finding_to_entity(model)

    async def get_preference_with_feedback(
        self,
        org_id: uuid.UUID,
        repo_id: uuid.UUID,
        pattern_key: str,
        *,
        for_update: bool = False,
    ) -> tuple[ReviewLearnedPreference, ReviewFindingFeedback | None] | None:
        stmt = select(ReviewLearnedPreferenceModel).where(
            ReviewLearnedPreferenceModel.org_id == org_id,
            ReviewLearnedPreferenceModel.repo_id == repo_id,
            ReviewLearnedPreferenceModel.pattern_key == pattern_key,
        )
        if for_update:
            stmt = stmt.with_for_update()
        pref_model = (await self._session.execute(stmt)).scalar_one_or_none()
        if pref_model is None:
            return None

        fb_entity: ReviewFindingFeedback | None = None
        if pref_model.source_feedback_id is not None:
            fb_stmt = select(ReviewFindingFeedbackModel).where(
                ReviewFindingFeedbackModel.id == pref_model.source_feedback_id
            )
            fb_model = (await self._session.execute(fb_stmt)).scalar_one_or_none()
            if fb_model is not None:
                fb_entity = _feedback_to_entity(fb_model)
        return _preference_to_entity(pref_model), fb_entity

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
        stmt = (
            select(ReviewLearnedPreferenceModel)
            .where(
                ReviewLearnedPreferenceModel.repo_id == repo_id,
                ReviewLearnedPreferenceModel.pattern_key == pattern_key,
            )
            .with_for_update()
        )
        model = (await self._session.execute(stmt)).scalar_one_or_none()
        if model is None:
            model = ReviewLearnedPreferenceModel(
                org_id=org_id,
                repo_id=repo_id,
                rule_id=rule_id,
                source_feedback_id=source_feedback_id,
                pattern_key=pattern_key,
                instruction=instruction,
                dismiss_count=dismiss_count,
                accept_count=accept_count,
                consecutive_dismissals=consecutive_dismissals,
                status=status,
                last_feedback_at=last_feedback_at,
            )
            self._session.add(model)
        else:
            if rule_id is not None:
                model.rule_id = rule_id
            if source_feedback_id is not None:
                model.source_feedback_id = source_feedback_id
            model.instruction = instruction
            model.dismiss_count = dismiss_count
            model.accept_count = accept_count
            model.consecutive_dismissals = consecutive_dismissals
            model.status = status
            model.last_feedback_at = last_feedback_at
            model.updated_at = datetime.now(UTC)

        await self._session.flush()
        return _preference_to_entity(model)

    async def list_preferences_for_repo(
        self,
        org_id: uuid.UUID,
        repo_id: uuid.UUID,
        status: str | None = None,
        page: int = 1,
        page_size: int = 50,
    ) -> tuple[list[tuple[ReviewLearnedPreference, ReviewFindingFeedback | None]], int]:
        repo_stmt = select(RepositoryModel.id).where(
            RepositoryModel.id == repo_id,
            RepositoryModel.org_id == org_id,
            RepositoryModel.deleted_at.is_(None),
        )
        if (await self._session.execute(repo_stmt)).scalar_one_or_none() is None:
            raise NotFoundError(f"Repository {repo_id} not found in organization")

        filters = [
            ReviewLearnedPreferenceModel.org_id == org_id,
            ReviewLearnedPreferenceModel.repo_id == repo_id,
        ]
        if status is not None:
            filters.append(ReviewLearnedPreferenceModel.status == status)

        count_stmt = select(func.count(ReviewLearnedPreferenceModel.id)).where(*filters)
        total = int((await self._session.execute(count_stmt)).scalar_one())

        offset = max(0, (page - 1) * page_size)
        stmt = (
            select(ReviewLearnedPreferenceModel, ReviewFindingFeedbackModel)
            .outerjoin(
                ReviewFindingFeedbackModel,
                ReviewLearnedPreferenceModel.source_feedback_id
                == ReviewFindingFeedbackModel.id,
            )
            .where(*filters)
            .order_by(ReviewLearnedPreferenceModel.updated_at.desc())
            .offset(offset)
            .limit(page_size)
        )
        rows = (await self._session.execute(stmt)).all()
        items = [
            (
                _preference_to_entity(pref),
                _feedback_to_entity(fb) if fb is not None else None,
            )
            for pref, fb in rows
        ]
        return items, total

    async def get_preference_by_id(
        self,
        org_id: uuid.UUID,
        repo_id: uuid.UUID,
        pref_id: uuid.UUID,
    ) -> ReviewLearnedPreference:
        stmt = select(ReviewLearnedPreferenceModel).where(
            ReviewLearnedPreferenceModel.id == pref_id,
            ReviewLearnedPreferenceModel.org_id == org_id,
            ReviewLearnedPreferenceModel.repo_id == repo_id,
        )
        model = (await self._session.execute(stmt)).scalar_one_or_none()
        if model is None:
            raise NotFoundError(f"Learned preference {pref_id} not found")
        return _preference_to_entity(model)

    async def update_preference_admin(
        self,
        org_id: uuid.UUID,
        repo_id: uuid.UUID,
        pref_id: uuid.UUID,
        status: str,
        consecutive_dismissals: int,
        instruction: str | None = None,
    ) -> ReviewLearnedPreference:
        stmt = select(ReviewLearnedPreferenceModel).where(
            ReviewLearnedPreferenceModel.id == pref_id,
            ReviewLearnedPreferenceModel.org_id == org_id,
            ReviewLearnedPreferenceModel.repo_id == repo_id,
        )
        model = (await self._session.execute(stmt)).scalar_one_or_none()
        if model is None:
            raise NotFoundError(f"Learned preference {pref_id} not found")

        model.status = status
        model.consecutive_dismissals = consecutive_dismissals
        if instruction is not None:
            model.instruction = instruction
        model.updated_at = datetime.now(UTC)
        await self._session.flush()
        return _preference_to_entity(model)
