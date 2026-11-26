"""Use case for synchronizing Clerk organizations into PostgreSQL."""

import uuid
from dataclasses import dataclass
from typing import Any

from app.application.ports.audit_log_repository import AuditLogRepository
from app.application.ports.clerk_gateway import ClerkOrganizationGateway
from app.application.ports.organization_repository import OrganizationRepository
from app.domain.entities.organization import Organization
from app.domain.exceptions import ValidationError


@dataclass(frozen=True, slots=True)
class SyncWebhookResult:
    """Outcome of processing a Clerk organization webhook event."""

    status: str
    org_id: uuid.UUID | None = None


def _org_snapshot(org: Organization | None) -> dict[str, Any] | None:
    if org is None:
        return None
    return {
        "clerk_org_id": org.clerk_org_id,
        "name": org.name,
        "slug": org.slug,
        "deleted_at": org.deleted_at.isoformat() if org.deleted_at else None,
    }


def _fallback_slug(clerk_org_id: str, raw_slug: Any) -> str:
    if isinstance(raw_slug, str) and raw_slug.strip():
        return raw_slug.strip()
    return f"org-{clerk_org_id.lower()}"


class SyncOrganizationUseCase:
    """Synchronizes Clerk organization lifecycle events and BAPI lookups."""

    def __init__(
        self,
        org_repo: OrganizationRepository,
        audit_repo: AuditLogRepository,
        clerk_gateway: ClerkOrganizationGateway | None = None,
    ) -> None:
        self._org_repo = org_repo
        self._audit_repo = audit_repo
        self._clerk_gateway = clerk_gateway

    async def sync_from_webhook(
        self,
        *,
        event_type: str,
        data: dict[str, Any],
    ) -> SyncWebhookResult:
        """Apply a verified Clerk organization webhook event atomically."""
        if event_type not in (
            "organization.created",
            "organization.updated",
            "organization.deleted",
        ):
            return SyncWebhookResult(status="ignored", org_id=None)

        clerk_org_id = data.get("id")
        if not isinstance(clerk_org_id, str) or not clerk_org_id.strip():
            raise ValidationError("Clerk organization event missing valid 'data.id'")
        clerk_org_id = clerk_org_id.strip()

        actor_id_raw = data.get("created_by")
        actor_id = (
            actor_id_raw.strip()
            if isinstance(actor_id_raw, str) and actor_id_raw.strip()
            else "clerk_webhook"
        )

        before = await self._org_repo.get_by_clerk_id_including_deleted(clerk_org_id)
        before_snapshot = _org_snapshot(before)

        if event_type == "organization.deleted":
            deleted_org = await self._org_repo.soft_delete_by_clerk_id(clerk_org_id)
            if deleted_org is None:
                return SyncWebhookResult(status="ignored", org_id=None)
            after_snapshot = _org_snapshot(deleted_org)
            await self._audit_repo.record_event(
                org_id=deleted_org.id,
                actor_type="clerk_webhook",
                actor_id=actor_id,
                action="organization.deleted",
                target_type="organization",
                target_id=deleted_org.id,
                payload_before=before_snapshot,
                payload_after=after_snapshot,
            )
            return SyncWebhookResult(status="processed", org_id=deleted_org.id)

        raw_name = data.get("name")
        if not isinstance(raw_name, str) or not raw_name.strip():
            raise ValidationError("Clerk organization event missing valid 'data.name'")
        name = raw_name.strip()
        slug = _fallback_slug(clerk_org_id, data.get("slug"))

        if event_type == "organization.created":
            org = await self._org_repo.create_or_update(
                clerk_org_id=clerk_org_id,
                name=name,
                slug=slug,
            )
        else:
            if before is not None and before.deleted_at is not None:
                return SyncWebhookResult(status="ignored", org_id=None)
            org_maybe = await self._org_repo.create_or_update_if_active(
                clerk_org_id=clerk_org_id,
                name=name,
                slug=slug,
            )
            if org_maybe is None:
                return SyncWebhookResult(status="ignored", org_id=None)
            org = org_maybe

        after_snapshot = _org_snapshot(org)
        if before_snapshot != after_snapshot:
            await self._audit_repo.record_event(
                org_id=org.id,
                actor_type="clerk_webhook",
                actor_id=actor_id,
                action=event_type,
                target_type="organization",
                target_id=org.id,
                payload_before=before_snapshot,
                payload_after=after_snapshot,
            )

        return SyncWebhookResult(status="processed", org_id=org.id)

    async def sync_from_clerk_api(
        self,
        *,
        clerk_org_id: str,
        actor_user_id: str,
    ) -> Organization:
        """Fetch org metadata from Clerk Backend API and upsert atomically."""
        if self._clerk_gateway is None:
            raise ValueError("ClerkOrganizationGateway is required for API sync")

        info = await self._clerk_gateway.get_organization(clerk_org_id)
        before = await self._org_repo.get_by_clerk_id_including_deleted(
            info.clerk_org_id
        )
        before_snapshot = _org_snapshot(before)

        org = await self._org_repo.create_or_update(
            clerk_org_id=info.clerk_org_id,
            name=info.name,
            slug=info.slug,
        )
        after_snapshot = _org_snapshot(org)

        if before_snapshot != after_snapshot:
            await self._audit_repo.record_event(
                org_id=org.id,
                actor_type="user",
                actor_id=actor_user_id,
                action="organization.synced",
                target_type="organization",
                target_id=org.id,
                payload_before=before_snapshot,
                payload_after=after_snapshot,
            )

        return org
