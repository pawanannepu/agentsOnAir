"""Use cases for managing organization and repository review rules and overrides."""

import uuid

from app.application.ports.audit_log_repository import AuditLogRepository
from app.application.ports.repository_repository import RepositoryRepository
from app.application.ports.review_rules_repository import ReviewRulesRepository
from app.domain.entities.review_rule import (
    EffectiveReviewRule,
    ReviewRule,
    ReviewRuleOverride,
)
from app.domain.exceptions import ValidationError

VALID_SEVERITIES = frozenset({"critical", "major", "minor", "info"})
VALID_CATEGORIES = frozenset(
    {"security", "bug", "performance", "architecture", "style"}
)


def _validate_globs(path_globs: list[str] | None) -> list[str]:
    if path_globs is None:
        return ["**/*"]
    cleaned = [g.strip() for g in path_globs if isinstance(g, str) and g.strip()]
    if not cleaned:
        raise ValidationError("path_globs must contain at least one non-empty glob")
    return cleaned


def _validate_severity(severity: str) -> str:
    if severity not in VALID_SEVERITIES:
        raise ValidationError(
            f"Invalid severity '{severity}'; expected one of {sorted(VALID_SEVERITIES)}"
        )
    return severity


def _validate_category(category: str) -> str:
    if category not in VALID_CATEGORIES:
        raise ValidationError(
            f"Invalid category '{category}'; expected one of {sorted(VALID_CATEGORIES)}"
        )
    return category


def _rule_snapshot(rule: ReviewRule) -> dict:
    return {
        "id": str(rule.id),
        "org_id": str(rule.org_id),
        "repo_id": str(rule.repo_id) if rule.repo_id else None,
        "title": rule.title,
        "instruction": rule.instruction,
        "severity": rule.severity,
        "category": rule.category,
        "path_globs": rule.path_globs,
        "is_enabled": rule.is_enabled,
        "deleted_at": rule.deleted_at.isoformat() if rule.deleted_at else None,
    }


class ReviewRulesUseCase:
    """Orchestrates CRUD for org/repo review rules and overrides with audits."""

    def __init__(
        self,
        rules_repo: ReviewRulesRepository,
        repository_repo: RepositoryRepository,
        audit_log_repo: AuditLogRepository,
    ) -> None:
        self._rules_repo = rules_repo
        self._repository_repo = repository_repo
        self._audit_log_repo = audit_log_repo

    async def list_org_rules(
        self, org_id: uuid.UUID, page: int = 1, page_size: int = 50
    ) -> tuple[list[ReviewRule], int]:
        return await self._rules_repo.list_org_rules(
            org_id, page=page, page_size=page_size
        )

    async def create_org_rule(
        self,
        org_id: uuid.UUID,
        actor_id: str,
        title: str,
        instruction: str,
        severity: str,
        category: str,
        path_globs: list[str] | None = None,
        is_enabled: bool = True,
    ) -> ReviewRule:
        clean_title = title.strip()
        clean_inst = instruction.strip()
        if not clean_title or not clean_inst:
            raise ValidationError("title and instruction must be non-empty")
        globs = _validate_globs(path_globs)
        sev = _validate_severity(severity)
        cat = _validate_category(category)

        created = await self._rules_repo.create_org_rule(
            org_id=org_id,
            title=clean_title,
            instruction=clean_inst,
            severity=sev,
            category=cat,
            path_globs=globs,
            is_enabled=is_enabled,
            created_by=actor_id,
        )
        await self._audit_log_repo.record_event(
            org_id=org_id,
            actor_type="user",
            actor_id=actor_id,
            action="review_rule.created",
            target_type="review_rule",
            target_id=created.id,
            payload_after=_rule_snapshot(created),
        )
        return created

    async def update_org_rule(
        self,
        org_id: uuid.UUID,
        rule_id: uuid.UUID,
        actor_id: str,
        *,
        title: str | None = None,
        instruction: str | None = None,
        severity: str | None = None,
        category: str | None = None,
        path_globs: list[str] | None = None,
        is_enabled: bool | None = None,
    ) -> ReviewRule:
        before = await self._rules_repo.get_rule(org_id, rule_id)
        if before.repo_id is not None:
            raise ValidationError(
                "Rule belongs to a repository, not organization defaults"
            )

        clean_title = title.strip() if title is not None else None
        clean_inst = instruction.strip() if instruction is not None else None
        if clean_title is not None and not clean_title:
            raise ValidationError("title must be non-empty")
        if clean_inst is not None and not clean_inst:
            raise ValidationError("instruction must be non-empty")
        globs = _validate_globs(path_globs) if path_globs is not None else None
        sev = _validate_severity(severity) if severity is not None else None
        cat = _validate_category(category) if category is not None else None

        updated = await self._rules_repo.update_rule(
            org_id,
            rule_id,
            require_org_default=True,
            title=clean_title,
            instruction=clean_inst,
            severity=sev,
            category=cat,
            path_globs=globs,
            is_enabled=is_enabled,
        )
        await self._audit_log_repo.record_event(
            org_id=org_id,
            actor_type="user",
            actor_id=actor_id,
            action="review_rule.updated",
            target_type="review_rule",
            target_id=updated.id,
            payload_before=_rule_snapshot(before),
            payload_after=_rule_snapshot(updated),
        )
        return updated

    async def delete_org_rule(
        self, org_id: uuid.UUID, rule_id: uuid.UUID, actor_id: str
    ) -> None:
        before = await self._rules_repo.get_rule(org_id, rule_id)
        if before.repo_id is not None:
            raise ValidationError(
                "Rule belongs to a repository, not organization defaults"
            )
        deleted = await self._rules_repo.soft_delete_rule(
            org_id, rule_id, require_org_default=True
        )
        await self._audit_log_repo.record_event(
            org_id=org_id,
            actor_type="user",
            actor_id=actor_id,
            action="review_rule.deleted",
            target_type="review_rule",
            target_id=deleted.id,
            payload_before=_rule_snapshot(before),
            payload_after=_rule_snapshot(deleted),
        )

    async def list_repo_rules(
        self, org_id: uuid.UUID, repo_id: uuid.UUID
    ) -> list[EffectiveReviewRule]:
        await self._repository_repo.get_by_id(org_id, repo_id)
        return await self._rules_repo.list_repo_rules_with_overrides(org_id, repo_id)

    async def create_repo_rule(
        self,
        org_id: uuid.UUID,
        repo_id: uuid.UUID,
        actor_id: str,
        title: str,
        instruction: str,
        severity: str,
        category: str,
        path_globs: list[str] | None = None,
        is_enabled: bool = True,
    ) -> ReviewRule:
        await self._repository_repo.get_by_id(org_id, repo_id)
        clean_title = title.strip()
        clean_inst = instruction.strip()
        if not clean_title or not clean_inst:
            raise ValidationError("title and instruction must be non-empty")
        globs = _validate_globs(path_globs)
        sev = _validate_severity(severity)
        cat = _validate_category(category)

        created = await self._rules_repo.create_repo_rule(
            org_id=org_id,
            repo_id=repo_id,
            title=clean_title,
            instruction=clean_inst,
            severity=sev,
            category=cat,
            path_globs=globs,
            is_enabled=is_enabled,
            created_by=actor_id,
        )
        await self._audit_log_repo.record_event(
            org_id=org_id,
            actor_type="user",
            actor_id=actor_id,
            action="review_rule.created",
            target_type="review_rule",
            target_id=created.id,
            payload_after=_rule_snapshot(created),
        )
        return created

    async def update_repo_rule(
        self,
        org_id: uuid.UUID,
        repo_id: uuid.UUID,
        rule_id: uuid.UUID,
        actor_id: str,
        *,
        title: str | None = None,
        instruction: str | None = None,
        severity: str | None = None,
        category: str | None = None,
        path_globs: list[str] | None = None,
        is_enabled: bool | None = None,
    ) -> ReviewRule:
        await self._repository_repo.get_by_id(org_id, repo_id)
        before = await self._rules_repo.get_rule(org_id, rule_id)
        if before.repo_id != repo_id:
            raise ValidationError("Rule does not belong to this repository")

        clean_title = title.strip() if title is not None else None
        clean_inst = instruction.strip() if instruction is not None else None
        if clean_title is not None and not clean_title:
            raise ValidationError("title must be non-empty")
        if clean_inst is not None and not clean_inst:
            raise ValidationError("instruction must be non-empty")
        globs = _validate_globs(path_globs) if path_globs is not None else None
        sev = _validate_severity(severity) if severity is not None else None
        cat = _validate_category(category) if category is not None else None

        updated = await self._rules_repo.update_rule(
            org_id,
            rule_id,
            expected_repo_id=repo_id,
            title=clean_title,
            instruction=clean_inst,
            severity=sev,
            category=cat,
            path_globs=globs,
            is_enabled=is_enabled,
        )
        await self._audit_log_repo.record_event(
            org_id=org_id,
            actor_type="user",
            actor_id=actor_id,
            action="review_rule.updated",
            target_type="review_rule",
            target_id=updated.id,
            payload_before=_rule_snapshot(before),
            payload_after=_rule_snapshot(updated),
        )
        return updated

    async def delete_repo_rule(
        self,
        org_id: uuid.UUID,
        repo_id: uuid.UUID,
        rule_id: uuid.UUID,
        actor_id: str,
    ) -> None:
        await self._repository_repo.get_by_id(org_id, repo_id)
        before = await self._rules_repo.get_rule(org_id, rule_id)
        if before.repo_id != repo_id:
            raise ValidationError("Rule does not belong to this repository")
        deleted = await self._rules_repo.soft_delete_rule(
            org_id, rule_id, expected_repo_id=repo_id
        )
        await self._audit_log_repo.record_event(
            org_id=org_id,
            actor_type="user",
            actor_id=actor_id,
            action="review_rule.deleted",
            target_type="review_rule",
            target_id=deleted.id,
            payload_before=_rule_snapshot(before),
            payload_after=_rule_snapshot(deleted),
        )

    async def upsert_rule_override(
        self,
        org_id: uuid.UUID,
        repo_id: uuid.UUID,
        rule_id: uuid.UUID,
        actor_id: str,
        *,
        is_enabled: bool | None = None,
        severity_override: str | None = None,
    ) -> tuple[ReviewRuleOverride | None, EffectiveReviewRule]:
        await self._repository_repo.get_by_id(org_id, repo_id)
        if severity_override is not None:
            _validate_severity(severity_override)

        before_ov = await self._rules_repo.get_override(org_id, repo_id, rule_id)
        before_payload = (
            {
                "is_enabled": before_ov.is_enabled,
                "severity_override": before_ov.severity_override,
            }
            if before_ov is not None
            else None
        )

        override, effective = await self._rules_repo.upsert_override(
            org_id=org_id,
            repo_id=repo_id,
            rule_id=rule_id,
            is_enabled=is_enabled,
            severity_override=severity_override,
            updated_by=actor_id,
        )
        await self._audit_log_repo.record_event(
            org_id=org_id,
            actor_type="user",
            actor_id=actor_id,
            action="review_rule_override.updated",
            target_type="review_rule_override",
            target_id=override.id if override is not None else rule_id,
            payload_before=before_payload,
            payload_after={
                "repo_id": str(repo_id),
                "rule_id": str(rule_id),
                "is_enabled": override.is_enabled if override else None,
                "severity_override": override.severity_override if override else None,
                "cleared": override is None,
            },
        )
        return override, effective
