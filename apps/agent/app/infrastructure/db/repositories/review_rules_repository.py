"""SQLAlchemy implementation of ReviewRulesRepository."""

import uuid
from datetime import UTC, datetime

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.application.ports.review_rules_repository import ReviewRulesRepository
from app.domain.entities.review_rule import (
    EffectiveReviewRule,
    ReviewRule,
    ReviewRuleOverride,
)
from app.domain.exceptions import NotFoundError, ValidationError
from app.infrastructure.db.models.organization import OrganizationModel
from app.infrastructure.db.models.repository import RepositoryModel
from app.infrastructure.db.models.review_rule import ReviewRuleModel
from app.infrastructure.db.models.review_rule_override import ReviewRuleOverrideModel

MAX_ACTIVE_RULES_PER_REPO = 25


def _rule_to_entity(model: ReviewRuleModel) -> ReviewRule:
    return ReviewRule(
        id=model.id,
        org_id=model.org_id,
        repo_id=model.repo_id,
        title=model.title,
        instruction=model.instruction,
        severity=model.severity,
        category=model.category,
        path_globs=list(model.path_globs or ["**/*"]),
        is_enabled=model.is_enabled,
        created_by=model.created_by,
        deleted_at=model.deleted_at,
        created_at=model.created_at,
        updated_at=model.updated_at,
    )


def _override_to_entity(model: ReviewRuleOverrideModel) -> ReviewRuleOverride:
    return ReviewRuleOverride(
        id=model.id,
        org_id=model.org_id,
        repo_id=model.repo_id,
        rule_id=model.rule_id,
        is_enabled=model.is_enabled,
        severity_override=model.severity_override,
        updated_by=model.updated_by,
        updated_at=model.updated_at,
    )


def _merge_effective(
    rule: ReviewRuleModel, override: ReviewRuleOverrideModel | None
) -> EffectiveReviewRule:
    eff_enabled = (
        override.is_enabled
        if override is not None and override.is_enabled is not None
        else rule.is_enabled
    )
    eff_severity = (
        override.severity_override
        if override is not None and override.severity_override is not None
        else rule.severity
    )
    return EffectiveReviewRule(
        id=rule.id,
        org_id=rule.org_id,
        repo_id=rule.repo_id,
        scope="org" if rule.repo_id is None else "repo",
        title=rule.title,
        instruction=rule.instruction,
        base_severity=rule.severity,
        severity=eff_severity,
        category=rule.category,
        path_globs=list(rule.path_globs or ["**/*"]),
        base_is_enabled=rule.is_enabled,
        is_enabled=eff_enabled,
        has_override=override is not None,
        override_is_enabled=override.is_enabled if override is not None else None,
        override_severity=override.severity_override if override is not None else None,
        created_by=rule.created_by,
        created_at=rule.created_at,
        updated_at=rule.updated_at,
    )


class SqlAlchemyReviewRulesRepository(ReviewRulesRepository):
    """Async SQLAlchemy adapter for review rules and per-repo overrides."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def _lock_org_and_repos(self, org_id: uuid.UUID) -> list[RepositoryModel]:
        org_stmt = (
            select(OrganizationModel)
            .where(
                OrganizationModel.id == org_id,
                OrganizationModel.deleted_at.is_(None),
            )
            .with_for_update()
        )
        org_model = (await self._session.execute(org_stmt)).scalar_one_or_none()
        if org_model is None:
            raise NotFoundError(f"Organization {org_id} not found")

        repos_stmt = (
            select(RepositoryModel)
            .where(
                RepositoryModel.org_id == org_id,
                RepositoryModel.deleted_at.is_(None),
            )
            .order_by(RepositoryModel.id.asc())
            .with_for_update()
        )
        return list((await self._session.execute(repos_stmt)).scalars().all())

    async def _lock_repo(
        self, org_id: uuid.UUID, repo_id: uuid.UUID
    ) -> RepositoryModel:
        stmt = (
            select(RepositoryModel)
            .where(
                RepositoryModel.id == repo_id,
                RepositoryModel.org_id == org_id,
                RepositoryModel.deleted_at.is_(None),
            )
            .with_for_update()
        )
        repo = (await self._session.execute(stmt)).scalar_one_or_none()
        if repo is None:
            raise NotFoundError(f"Repository {repo_id} not found in organization")
        return repo

    async def _count_active_merged_for_repo(
        self,
        org_id: uuid.UUID,
        repo_id: uuid.UUID,
        *,
        override_rule_id: uuid.UUID | None = None,
        override_effective_enabled: bool | None = None,
        extra_active_delta: int = 0,
    ) -> int:
        org_rules_stmt = select(ReviewRuleModel).where(
            ReviewRuleModel.org_id == org_id,
            ReviewRuleModel.repo_id.is_(None),
            ReviewRuleModel.deleted_at.is_(None),
        )
        org_rules = (await self._session.execute(org_rules_stmt)).scalars().all()

        repo_rules_stmt = select(ReviewRuleModel).where(
            ReviewRuleModel.org_id == org_id,
            ReviewRuleModel.repo_id == repo_id,
            ReviewRuleModel.deleted_at.is_(None),
        )
        repo_rules = (await self._session.execute(repo_rules_stmt)).scalars().all()

        overrides_stmt = select(ReviewRuleOverrideModel).where(
            ReviewRuleOverrideModel.org_id == org_id,
            ReviewRuleOverrideModel.repo_id == repo_id,
        )
        overrides = {
            ov.rule_id: ov
            for ov in (await self._session.execute(overrides_stmt)).scalars().all()
        }

        active_count = 0
        for rule in org_rules:
            if override_rule_id is not None and rule.id == override_rule_id:
                eff = (
                    override_effective_enabled
                    if override_effective_enabled is not None
                    else rule.is_enabled
                )
            else:
                ov = overrides.get(rule.id)
                eff = (
                    ov.is_enabled
                    if ov is not None and ov.is_enabled is not None
                    else rule.is_enabled
                )
            if eff:
                active_count += 1

        for rule in repo_rules:
            if override_rule_id is not None and rule.id == override_rule_id:
                eff = (
                    override_effective_enabled
                    if override_effective_enabled is not None
                    else rule.is_enabled
                )
            else:
                eff = rule.is_enabled
            if eff:
                active_count += 1

        return active_count + extra_active_delta

    async def list_org_rules(
        self,
        org_id: uuid.UUID,
        page: int = 1,
        page_size: int = 50,
    ) -> tuple[list[ReviewRule], int]:
        count_stmt = select(func.count(ReviewRuleModel.id)).where(
            ReviewRuleModel.org_id == org_id,
            ReviewRuleModel.repo_id.is_(None),
            ReviewRuleModel.deleted_at.is_(None),
        )
        total = int((await self._session.execute(count_stmt)).scalar_one())

        offset = max(0, (page - 1) * page_size)
        stmt = (
            select(ReviewRuleModel)
            .where(
                ReviewRuleModel.org_id == org_id,
                ReviewRuleModel.repo_id.is_(None),
                ReviewRuleModel.deleted_at.is_(None),
            )
            .order_by(ReviewRuleModel.created_at.asc())
            .offset(offset)
            .limit(page_size)
        )
        models = (await self._session.execute(stmt)).scalars().all()
        return [_rule_to_entity(m) for m in models], total

    async def get_rule(self, org_id: uuid.UUID, rule_id: uuid.UUID) -> ReviewRule:
        stmt = select(ReviewRuleModel).where(
            ReviewRuleModel.id == rule_id,
            ReviewRuleModel.org_id == org_id,
            ReviewRuleModel.deleted_at.is_(None),
        )
        model = (await self._session.execute(stmt)).scalar_one_or_none()
        if model is None:
            raise NotFoundError(f"Review rule {rule_id} not found")
        return _rule_to_entity(model)

    async def create_org_rule(
        self,
        org_id: uuid.UUID,
        title: str,
        instruction: str,
        severity: str,
        category: str,
        path_globs: list[str],
        is_enabled: bool,
        created_by: str,
    ) -> ReviewRule:
        repos = await self._lock_org_and_repos(org_id)
        if is_enabled:
            for repo in repos:
                # Check if repo has an override? A new rule has no override yet,
                # so creating an enabled org rule adds +1 active rule to every repo.
                count = await self._count_active_merged_for_repo(
                    org_id, repo.id, extra_active_delta=1
                )
                if count > MAX_ACTIVE_RULES_PER_REPO:
                    raise ValidationError(
                        f"Org rule exceeds the {MAX_ACTIVE_RULES_PER_REPO} "
                        f"active rule limit for repository '{repo.full_name}'"
                    )

        model = ReviewRuleModel(
            org_id=org_id,
            repo_id=None,
            title=title,
            instruction=instruction,
            severity=severity,
            category=category,
            path_globs=path_globs,
            is_enabled=is_enabled,
            created_by=created_by,
        )
        self._session.add(model)
        await self._session.flush()
        return _rule_to_entity(model)

    async def create_repo_rule(
        self,
        org_id: uuid.UUID,
        repo_id: uuid.UUID,
        title: str,
        instruction: str,
        severity: str,
        category: str,
        path_globs: list[str],
        is_enabled: bool,
        created_by: str,
    ) -> ReviewRule:
        await self._lock_repo(org_id, repo_id)
        if is_enabled:
            count = await self._count_active_merged_for_repo(
                org_id, repo_id, extra_active_delta=1
            )
            if count > MAX_ACTIVE_RULES_PER_REPO:
                raise ValidationError(
                    f"Repository reached the maximum of {MAX_ACTIVE_RULES_PER_REPO} "
                    "active review rules"
                )

        model = ReviewRuleModel(
            org_id=org_id,
            repo_id=repo_id,
            title=title,
            instruction=instruction,
            severity=severity,
            category=category,
            path_globs=path_globs,
            is_enabled=is_enabled,
            created_by=created_by,
        )
        self._session.add(model)
        await self._session.flush()
        return _rule_to_entity(model)

    async def update_rule(
        self,
        org_id: uuid.UUID,
        rule_id: uuid.UUID,
        *,
        expected_repo_id: uuid.UUID | None = None,
        require_org_default: bool = False,
        title: str | None = None,
        instruction: str | None = None,
        severity: str | None = None,
        category: str | None = None,
        path_globs: list[str] | None = None,
        is_enabled: bool | None = None,
    ) -> ReviewRule:
        stmt = select(ReviewRuleModel).where(
            ReviewRuleModel.id == rule_id,
            ReviewRuleModel.org_id == org_id,
            ReviewRuleModel.deleted_at.is_(None),
        )
        if require_org_default:
            stmt = stmt.where(ReviewRuleModel.repo_id.is_(None))
        elif expected_repo_id is not None:
            stmt = stmt.where(ReviewRuleModel.repo_id == expected_repo_id)

        model = (await self._session.execute(stmt)).scalar_one_or_none()
        if model is None:
            raise NotFoundError(f"Review rule {rule_id} not found")

        if model.repo_id is None:
            repos = await self._lock_org_and_repos(org_id)
            if is_enabled is True and not model.is_enabled:
                for repo in repos:
                    ov_stmt = select(ReviewRuleOverrideModel).where(
                        ReviewRuleOverrideModel.repo_id == repo.id,
                        ReviewRuleOverrideModel.rule_id == model.id,
                    )
                    ov = (await self._session.execute(ov_stmt)).scalar_one_or_none()
                    eff = (
                        ov.is_enabled
                        if ov is not None and ov.is_enabled is not None
                        else True
                    )
                    count = await self._count_active_merged_for_repo(
                        org_id,
                        repo.id,
                        override_rule_id=model.id,
                        override_effective_enabled=eff,
                    )
                    if count > MAX_ACTIVE_RULES_PER_REPO:
                        raise ValidationError(
                            f"Enabling this organization rule exceeds the "
                            f"{MAX_ACTIVE_RULES_PER_REPO} active rule limit for "
                            f"repository '{repo.full_name}'"
                        )
        else:
            await self._lock_repo(org_id, model.repo_id)
            if is_enabled is True and not model.is_enabled:
                count = await self._count_active_merged_for_repo(
                    org_id,
                    model.repo_id,
                    override_rule_id=model.id,
                    override_effective_enabled=True,
                )
                if count > MAX_ACTIVE_RULES_PER_REPO:
                    raise ValidationError(
                        f"Enabling this rule exceeds the {MAX_ACTIVE_RULES_PER_REPO} "
                        "active rule limit for this repository"
                    )

        if title is not None:
            model.title = title
        if instruction is not None:
            model.instruction = instruction
        if severity is not None:
            model.severity = severity
        if category is not None:
            model.category = category
        if path_globs is not None:
            model.path_globs = path_globs
        if is_enabled is not None:
            model.is_enabled = is_enabled
        model.updated_at = datetime.now(UTC)
        await self._session.flush()
        return _rule_to_entity(model)

    async def soft_delete_rule(
        self,
        org_id: uuid.UUID,
        rule_id: uuid.UUID,
        *,
        expected_repo_id: uuid.UUID | None = None,
        require_org_default: bool = False,
    ) -> ReviewRule:
        stmt = select(ReviewRuleModel).where(
            ReviewRuleModel.id == rule_id,
            ReviewRuleModel.org_id == org_id,
            ReviewRuleModel.deleted_at.is_(None),
        )
        if require_org_default:
            stmt = stmt.where(ReviewRuleModel.repo_id.is_(None))
        elif expected_repo_id is not None:
            stmt = stmt.where(ReviewRuleModel.repo_id == expected_repo_id)

        model = (await self._session.execute(stmt)).scalar_one_or_none()
        if model is None:
            raise NotFoundError(f"Review rule {rule_id} not found")

        model.deleted_at = datetime.now(UTC)
        model.updated_at = datetime.now(UTC)
        await self._session.flush()
        return _rule_to_entity(model)

    async def list_repo_rules_with_overrides(
        self,
        org_id: uuid.UUID,
        repo_id: uuid.UUID,
    ) -> list[EffectiveReviewRule]:
        repo_stmt = select(RepositoryModel.id).where(
            RepositoryModel.id == repo_id,
            RepositoryModel.org_id == org_id,
            RepositoryModel.deleted_at.is_(None),
        )
        if (await self._session.execute(repo_stmt)).scalar_one_or_none() is None:
            raise NotFoundError(f"Repository {repo_id} not found in organization")

        org_rules_stmt = (
            select(ReviewRuleModel)
            .where(
                ReviewRuleModel.org_id == org_id,
                ReviewRuleModel.repo_id.is_(None),
                ReviewRuleModel.deleted_at.is_(None),
            )
            .order_by(ReviewRuleModel.created_at.asc())
        )
        org_rules = (await self._session.execute(org_rules_stmt)).scalars().all()

        repo_rules_stmt = (
            select(ReviewRuleModel)
            .where(
                ReviewRuleModel.org_id == org_id,
                ReviewRuleModel.repo_id == repo_id,
                ReviewRuleModel.deleted_at.is_(None),
            )
            .order_by(ReviewRuleModel.created_at.asc())
        )
        repo_rules = (await self._session.execute(repo_rules_stmt)).scalars().all()

        overrides_stmt = select(ReviewRuleOverrideModel).where(
            ReviewRuleOverrideModel.org_id == org_id,
            ReviewRuleOverrideModel.repo_id == repo_id,
        )
        overrides = {
            ov.rule_id: ov
            for ov in (await self._session.execute(overrides_stmt)).scalars().all()
        }

        merged: list[EffectiveReviewRule] = []
        for rule in repo_rules:
            merged.append(_merge_effective(rule, None))
        for rule in org_rules:
            merged.append(_merge_effective(rule, overrides.get(rule.id)))
        return merged

    async def get_override(
        self,
        org_id: uuid.UUID,
        repo_id: uuid.UUID,
        rule_id: uuid.UUID,
    ) -> ReviewRuleOverride | None:
        stmt = select(ReviewRuleOverrideModel).where(
            ReviewRuleOverrideModel.org_id == org_id,
            ReviewRuleOverrideModel.repo_id == repo_id,
            ReviewRuleOverrideModel.rule_id == rule_id,
        )
        model = (await self._session.execute(stmt)).scalar_one_or_none()
        return _override_to_entity(model) if model is not None else None

    async def upsert_override(
        self,
        org_id: uuid.UUID,
        repo_id: uuid.UUID,
        rule_id: uuid.UUID,
        is_enabled: bool | None,
        severity_override: str | None,
        updated_by: str,
    ) -> tuple[ReviewRuleOverride | None, EffectiveReviewRule]:
        await self._lock_repo(org_id, repo_id)

        rule_stmt = select(ReviewRuleModel).where(
            ReviewRuleModel.id == rule_id,
            ReviewRuleModel.org_id == org_id,
            ReviewRuleModel.deleted_at.is_(None),
        )
        rule_model = (await self._session.execute(rule_stmt)).scalar_one_or_none()
        if rule_model is None:
            raise NotFoundError(f"Review rule {rule_id} not found")
        if rule_model.repo_id is not None:
            raise ValidationError(
                "Overrides may only target organization default rules"
            )

        desired_enabled = (
            is_enabled if is_enabled is not None else rule_model.is_enabled
        )
        if desired_enabled:
            count = await self._count_active_merged_for_repo(
                org_id,
                repo_id,
                override_rule_id=rule_model.id,
                override_effective_enabled=True,
            )
            if count > MAX_ACTIVE_RULES_PER_REPO:
                raise ValidationError(
                    f"Enabling this rule exceeds the {MAX_ACTIVE_RULES_PER_REPO} "
                    "active rule limit for this repository"
                )

        existing_stmt = select(ReviewRuleOverrideModel).where(
            ReviewRuleOverrideModel.repo_id == repo_id,
            ReviewRuleOverrideModel.rule_id == rule_id,
        )
        existing = (await self._session.execute(existing_stmt)).scalar_one_or_none()

        if is_enabled is None and severity_override is None:
            if existing is not None:
                await self._session.delete(existing)
                await self._session.flush()
            return None, _merge_effective(rule_model, None)

        if existing is None:
            ov = ReviewRuleOverrideModel(
                org_id=org_id,
                repo_id=repo_id,
                rule_id=rule_id,
                is_enabled=is_enabled,
                severity_override=severity_override,
                updated_by=updated_by,
            )
            self._session.add(ov)
            await self._session.flush()
            return _override_to_entity(ov), _merge_effective(rule_model, ov)

        existing.is_enabled = is_enabled
        existing.severity_override = severity_override
        existing.updated_by = updated_by
        existing.updated_at = datetime.now(UTC)
        await self._session.flush()
        return _override_to_entity(existing), _merge_effective(rule_model, existing)
