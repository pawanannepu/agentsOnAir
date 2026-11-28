"""Use cases for recording finding feedback and managing learned preferences."""

import uuid
from dataclasses import dataclass
from datetime import UTC, datetime

from app.application.ports.audit_log_repository import AuditLogRepository
from app.application.ports.repository_repository import RepositoryRepository
from app.application.ports.review_feedback_repository import ReviewFeedbackRepository
from app.application.services.review_context_service import (
    AUTO_DEFAULT_PREF_PREFIX,
    ReviewContextService,
)
from app.core.redaction import redact_credentials
from app.domain.entities.pr_review_finding import PRReviewFinding
from app.domain.entities.review_feedback import ReviewLearnedPreference
from app.domain.exceptions import ValidationError


@dataclass(slots=True)
class FeedbackResult:
    """Result of applying or deduplicating developer feedback on a finding."""

    finding: PRReviewFinding
    learned_preference: ReviewLearnedPreference | None
    applied: bool
    deduplicated: bool = False


class ReviewFeedbackUseCase:
    """Handles finding feedback state transitions, idempotency, and dampening."""

    def __init__(
        self,
        feedback_repo: ReviewFeedbackRepository,
        repository_repo: RepositoryRepository | None = None,
        audit_log_repo: AuditLogRepository | None = None,
    ) -> None:
        self._feedback_repo = feedback_repo
        self._repository_repo = repository_repo
        self._audit_log_repo = audit_log_repo

    async def submit_feedback(
        self,
        org_id: uuid.UUID,
        finding_id: uuid.UUID,
        feedback_type: str,
        source: str,
        actor_id: str,
        *,
        reason: str | None = None,
        remember_preference: bool = False,
        github_event_id: str | None = None,
    ) -> FeedbackResult:
        if feedback_type not in ("accepted", "dismissed"):
            raise ValidationError("feedback_type must be 'accepted' or 'dismissed'")
        if source not in ("console", "github_thread_resolved", "github_comment_reply"):
            raise ValidationError("Invalid feedback source")

        finding, review = await self._feedback_repo.get_finding_with_review(
            org_id, finding_id
        )
        clean_reason = (
            redact_credentials(reason.strip()) if reason and reason.strip() else None
        )

        fb_event, inserted = await self._feedback_repo.record_feedback_event(
            org_id=org_id,
            repo_id=review.repo_id,
            finding_id=finding.id,
            feedback_type=feedback_type,
            source=source,
            reason=clean_reason,
            remember_preference=remember_preference,
            actor_id=actor_id,
            github_event_id=github_event_id,
        )
        if not inserted:
            # Duplicate github_event_id delivery -> idempotent no-op
            pattern_key = ReviewContextService.compute_pattern_key(
                finding.rule_id, finding.category, finding.file_path
            )
            existing_pair = await self._feedback_repo.get_preference_with_feedback(
                org_id, review.repo_id, pattern_key
            )
            return FeedbackResult(
                finding=finding,
                learned_preference=existing_pair[0] if existing_pair else None,
                applied=False,
                deduplicated=True,
            )

        pattern_key = ReviewContextService.compute_pattern_key(
            finding.rule_id, finding.category, finding.file_path
        )
        existing_pair = await self._feedback_repo.get_preference_with_feedback(
            org_id, review.repo_id, pattern_key, for_update=True
        )
        existing_pref = existing_pair[0] if existing_pair else None
        existing_src_fb = existing_pair[1] if existing_pair else None

        # Idempotent on repeated identical feedback for the same finding_id
        if finding.feedback_state == feedback_type:
            return FeedbackResult(
                finding=finding,
                learned_preference=existing_pref,
                applied=False,
                deduplicated=True,
            )

        now = datetime.now(UTC)
        next_finding_status = "resolved" if feedback_type == "accepted" else "dismissed"
        updated_finding = await self._feedback_repo.update_finding_feedback_state(
            finding.id,
            feedback_state=feedback_type,
            status=next_finding_status,
        )

        dismiss_count = existing_pref.dismiss_count if existing_pref else 0
        accept_count = existing_pref.accept_count if existing_pref else 0
        consecutive_dismissals = (
            existing_pref.consecutive_dismissals if existing_pref else 0
        )

        if feedback_type == "dismissed":
            dismiss_count += 1
            consecutive_dismissals += 1
            if consecutive_dismissals >= 3:
                next_status = "suppressed"
            elif consecutive_dismissals == 2:
                next_status = "dampened"
            else:
                next_status = "active"

            if clean_reason:
                instruction = clean_reason
                source_fb_id = fb_event.id if fb_event else None
            elif remember_preference:
                instruction = (
                    f"Avoid reporting '{finding.title}' for pattern {pattern_key} "
                    "unless clearly critical."
                )
                source_fb_id = fb_event.id if fb_event else None
            elif existing_pref is not None and (
                (
                    existing_src_fb is not None
                    and (
                        existing_src_fb.remember_preference
                        or bool(existing_src_fb.reason)
                    )
                )
                or not existing_pref.instruction.startswith(AUTO_DEFAULT_PREF_PREFIX)
            ):
                instruction = existing_pref.instruction
                source_fb_id = existing_pref.source_feedback_id
            else:
                instruction = (
                    f"{AUTO_DEFAULT_PREF_PREFIX} {finding.title} ({pattern_key})"
                )
                source_fb_id = fb_event.id if fb_event else None
        else:
            accept_count += 1
            consecutive_dismissals = 0
            next_status = "active"
            if existing_pref is not None:
                instruction = existing_pref.instruction
                source_fb_id = existing_pref.source_feedback_id
            else:
                instruction = (
                    f"{AUTO_DEFAULT_PREF_PREFIX} {finding.title} ({pattern_key})"
                )
                source_fb_id = fb_event.id if fb_event else None

        pref = await self._feedback_repo.upsert_preference(
            org_id=org_id,
            repo_id=review.repo_id,
            rule_id=finding.rule_id,
            source_feedback_id=source_fb_id,
            pattern_key=pattern_key,
            instruction=instruction,
            dismiss_count=dismiss_count,
            accept_count=accept_count,
            consecutive_dismissals=consecutive_dismissals,
            status=next_status,
            last_feedback_at=now,
        )

        return FeedbackResult(
            finding=updated_finding,
            learned_preference=pref,
            applied=True,
            deduplicated=False,
        )

    async def reset_finding_unresolved(
        self,
        org_id: uuid.UUID,
        finding_id: uuid.UUID,
    ) -> PRReviewFinding:
        """Reset a finding back to `feedback_state = 'none'` and `status = 'open'`."""
        finding, _review = await self._feedback_repo.get_finding_with_review(
            org_id, finding_id
        )
        return await self._feedback_repo.update_finding_feedback_state(
            finding.id,
            feedback_state="none",
            status="open",
        )

    async def list_preferences(
        self,
        org_id: uuid.UUID,
        repo_id: uuid.UUID,
        status: str | None = None,
        page: int = 1,
        page_size: int = 50,
    ) -> tuple[list[ReviewLearnedPreference], int]:
        if status is not None and status not in ("active", "dampened", "suppressed"):
            raise ValidationError("Invalid status filter")
        pairs, total = await self._feedback_repo.list_preferences_for_repo(
            org_id, repo_id, status=status, page=page, page_size=page_size
        )
        return [p for p, _fb in pairs], total

    async def update_preference_admin(
        self,
        org_id: uuid.UUID,
        repo_id: uuid.UUID,
        pref_id: uuid.UUID,
        actor_id: str,
        *,
        status: str,
        instruction: str | None = None,
    ) -> ReviewLearnedPreference:
        if status not in ("active", "dampened", "suppressed"):
            raise ValidationError(
                "status must be 'active', 'dampened', or 'suppressed'"
            )
        if self._repository_repo is not None:
            await self._repository_repo.get_by_id(org_id, repo_id)

        before = await self._feedback_repo.get_preference_by_id(
            org_id, repo_id, pref_id
        )
        if status == "active":
            next_consecutive = 0
        elif status == "dampened":
            next_consecutive = 2
        else:
            next_consecutive = max(3, before.consecutive_dismissals)

        clean_inst = (
            redact_credentials(instruction.strip())
            if instruction is not None and instruction.strip()
            else None
        )
        if instruction is not None and not clean_inst:
            raise ValidationError("instruction must not be empty")

        updated = await self._feedback_repo.update_preference_admin(
            org_id=org_id,
            repo_id=repo_id,
            pref_id=pref_id,
            status=status,
            consecutive_dismissals=next_consecutive,
            instruction=clean_inst,
        )
        if self._audit_log_repo is not None:
            await self._audit_log_repo.record_event(
                org_id=org_id,
                actor_type="user",
                actor_id=actor_id,
                action="review_preference.updated",
                target_type="review_learned_preference",
                target_id=updated.id,
                payload_before={
                    "status": before.status,
                    "consecutive_dismissals": before.consecutive_dismissals,
                    "instruction": before.instruction,
                },
                payload_after={
                    "status": updated.status,
                    "consecutive_dismissals": updated.consecutive_dismissals,
                    "instruction": updated.instruction,
                },
            )
        return updated
