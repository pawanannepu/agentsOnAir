"""Tests for Clerk webhooks, atomic sync, BAPI fallback, and org:admin guard."""

import asyncio
import base64
import json
import uuid
from datetime import UTC, datetime
from unittest.mock import AsyncMock, patch

import httpx
import pytest
from httpx import AsyncClient
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession
from svix.webhooks import Webhook

from app.core.config import settings
from app.infrastructure.db.models.audit_log import AuditLogModel
from app.infrastructure.db.models.organization import OrganizationModel
from app.infrastructure.db.models.repository import RepositoryModel
from app.infrastructure.db.models.task import TaskModel
from app.infrastructure.db.repositories.organization_repository import (
    SqlAlchemyOrganizationRepository,
)
from tests.clerk_test_helpers import generate_rsa_keypair, make_clerk_jwt

_PRIV_PEM, _PUB_PEM = generate_rsa_keypair()
_TEST_WHSEC = "whsec_" + base64.b64encode(b"0123456789abcdef0123456789abcdef").decode(
    "ascii"
)


def _sign_svix(payload_bytes: bytes, secret: str = _TEST_WHSEC) -> dict[str, str]:
    wh = Webhook(secret)
    msg_id = f"msg_{uuid.uuid4().hex[:16]}"
    now = datetime.now(UTC)
    sig = wh.sign(msg_id, now, payload_bytes.decode("utf-8"))
    return {
        "svix-id": msg_id,
        "svix-timestamp": str(int(now.timestamp())),
        "svix-signature": sig,
        "Content-Type": "application/json",
    }


@pytest.mark.asyncio
async def test_clerk_webhook_validation_errors(
    client: AsyncClient, monkeypatch: pytest.MonkeyPatch
):
    """Verify 503 unconfigured, 400 missing headers/JSON, 401 bad signature (AC-5)."""
    payload = json.dumps({"type": "organization.created", "data": {}}).encode("utf-8")

    # 1. Unconfigured signing secret -> 503
    monkeypatch.setattr(settings, "CLERK_WEBHOOK_SIGNING_SECRET", None)
    resp_503 = await client.post("/api/v1/webhooks/clerk", content=payload)
    assert resp_503.status_code == 503

    monkeypatch.setattr(settings, "CLERK_WEBHOOK_SIGNING_SECRET", _TEST_WHSEC)

    # 2. Missing Svix headers -> 400
    resp_400 = await client.post("/api/v1/webhooks/clerk", content=payload)
    assert resp_400.status_code == 400

    # 3. Tampered signature -> 401
    headers = _sign_svix(payload)
    headers["svix-signature"] = "v1,invalid_signature_value"
    resp_401 = await client.post(
        "/api/v1/webhooks/clerk", content=payload, headers=headers
    )
    assert resp_401.status_code == 401

    # 4. Malformed JSON with valid signature -> 400
    bad_json = b"{not-valid-json"
    bad_headers = _sign_svix(bad_json)
    resp_bad_json = await client.post(
        "/api/v1/webhooks/clerk", content=bad_json, headers=bad_headers
    )
    assert resp_bad_json.status_code == 400


@pytest.mark.asyncio
async def test_clerk_webhook_lifecycle_and_non_resurrection(
    client: AsyncClient, db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
):
    """Verify created/updated/deleted lifecycle, idempotency, and audit logs (AC-5)."""
    monkeypatch.setattr(settings, "CLERK_WEBHOOK_SIGNING_SECRET", _TEST_WHSEC)
    clerk_org_id = f"org_wh_{uuid.uuid4().hex[:12]}"
    slug = f"wh-slug-{uuid.uuid4().hex[:8]}"

    # 1. organization.created -> creates org + audit log
    create_payload = json.dumps(
        {
            "type": "organization.created",
            "data": {
                "id": clerk_org_id,
                "name": "Acme Corp",
                "slug": slug,
                "created_by": "user_creator_1",
            },
        }
    ).encode("utf-8")
    res_create = await client.post(
        "/api/v1/webhooks/clerk",
        content=create_payload,
        headers=_sign_svix(create_payload),
    )
    assert res_create.status_code == 200
    create_body = res_create.json()
    assert create_body["status"] == "processed"
    assert create_body["org_id"] is not None
    created_org_uuid = uuid.UUID(create_body["org_id"])

    # Duplicate created with same fields -> no duplicate audit log
    res_dup = await client.post(
        "/api/v1/webhooks/clerk",
        content=create_payload,
        headers=_sign_svix(create_payload),
    )
    assert res_dup.status_code == 200

    # 2. organization.updated -> updates name
    update_payload = json.dumps(
        {
            "type": "organization.updated",
            "data": {
                "id": clerk_org_id,
                "name": "Acme Corporation",
                "slug": slug,
                "created_by": "user_editor_1",
            },
        }
    ).encode("utf-8")
    res_update = await client.post(
        "/api/v1/webhooks/clerk",
        content=update_payload,
        headers=_sign_svix(update_payload),
    )
    assert res_update.status_code == 200
    assert res_update.json()["status"] == "processed"

    # 3. organization.deleted -> soft deletes and keeps audit_logs
    delete_payload = json.dumps(
        {
            "type": "organization.deleted",
            "data": {"id": clerk_org_id, "deleted": True},
        }
    ).encode("utf-8")
    res_delete = await client.post(
        "/api/v1/webhooks/clerk",
        content=delete_payload,
        headers=_sign_svix(delete_payload),
    )
    assert res_delete.status_code == 200
    assert res_delete.json()["status"] == "processed"

    # Repeat deletion -> idempotent ignored
    res_delete_2 = await client.post(
        "/api/v1/webhooks/clerk",
        content=delete_payload,
        headers=_sign_svix(delete_payload),
    )
    assert res_delete_2.status_code == 200
    assert res_delete_2.json() == {"status": "ignored", "org_id": None}

    # 4. Delayed organization.updated must NOT resurrect soft-deleted row
    stale_update_payload = json.dumps(
        {
            "type": "organization.updated",
            "data": {
                "id": clerk_org_id,
                "name": "Resurrected Acme",
                "slug": slug,
            },
        }
    ).encode("utf-8")
    res_stale = await client.post(
        "/api/v1/webhooks/clerk",
        content=stale_update_payload,
        headers=_sign_svix(stale_update_payload),
    )
    assert res_stale.status_code == 200
    assert res_stale.json() == {"status": "ignored", "org_id": None}

    # Verify DB state and audit log actions (append-only rows remain intact)
    db_session.expire_all()
    org_row = (
        await db_session.execute(
            select(OrganizationModel).where(OrganizationModel.id == created_org_uuid)
        )
    ).scalar_one()
    assert org_row.deleted_at is not None
    assert org_row.name == "Acme Corporation"

    audit_rows = (
        (
            await db_session.execute(
                select(AuditLogModel)
                .where(AuditLogModel.org_id == created_org_uuid)
                .order_by(AuditLogModel.created_at.asc())
            )
        )
        .scalars()
        .all()
    )
    actions = [a.action for a in audit_rows]
    assert actions == [
        "organization.created",
        "organization.updated",
        "organization.deleted",
    ]


@pytest.mark.asyncio
async def test_concurrent_atomic_org_upserts(db_session: AsyncSession):
    """Verify concurrent ON CONFLICT upserts share one organization row."""
    clerk_org_id = f"org_conc_{uuid.uuid4().hex[:12]}"
    slug = f"conc-slug-{uuid.uuid4().hex[:8]}"
    repo = SqlAlchemyOrganizationRepository(db_session)

    org1 = await repo.create_or_update(
        clerk_org_id=clerk_org_id,
        name="Concurrent One",
        slug=slug,
    )
    await db_session.commit()

    try:
        from sqlalchemy.ext.asyncio import (
            AsyncSession as _AS,
        )
        from sqlalchemy.ext.asyncio import (
            async_sessionmaker,
            create_async_engine,
        )
        from sqlalchemy.pool import NullPool

        engine = create_async_engine(settings.DATABASE_URL, poolclass=NullPool)
        factory = async_sessionmaker(bind=engine, class_=_AS, expire_on_commit=False)

        async def _upsert(label: str) -> uuid.UUID:
            async with factory() as s:
                r = SqlAlchemyOrganizationRepository(s)
                o = await r.create_or_update(
                    clerk_org_id=clerk_org_id,
                    name=label,
                    slug=slug,
                )
                await s.commit()
                return o.id

        try:
            ids = await asyncio.gather(_upsert("Concurrent A"), _upsert("Concurrent B"))
            assert ids[0] == org1.id
            assert ids[1] == org1.id
        finally:
            await engine.dispose()
    finally:
        await db_session.execute(
            text("DELETE FROM organizations WHERE id = :oid"), {"oid": org1.id}
        )
        await db_session.commit()


@pytest.mark.asyncio
async def test_lazy_sync_and_explicit_sync_endpoints(
    client: AsyncClient, db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
):
    """Verify /organizations/sync, lazy sync, and 403/502 error mapping (AC-6)."""
    monkeypatch.setattr(settings, "CLERK_JWT_KEY", _PUB_PEM)
    monkeypatch.setattr(settings, "CLERK_SECRET_KEY", "sk_test_mock_secret_1234567890")

    # 1. Missing org claim -> 403 org_missing
    no_org_tok = make_clerk_jwt(_PRIV_PEM, user_id="user_no_org", clerk_org_id=None)
    res_missing = await client.post(
        "/api/v1/organizations/sync",
        headers={"Authorization": f"Bearer {no_org_tok}"},
    )
    assert res_missing.status_code == 403
    assert res_missing.json()["detail"]["code"] == "org_missing"

    # 2. Clerk BAPI 404 -> 403 org_inactive
    missing_clerk_id = f"org_missing_{uuid.uuid4().hex[:8]}"
    missing_tok = make_clerk_jwt(_PRIV_PEM, clerk_org_id=missing_clerk_id)

    mock_404_response = httpx.Response(404, json={"errors": [{"message": "Not found"}]})
    with patch("httpx.AsyncClient.get", new=AsyncMock(return_value=mock_404_response)):
        res_inactive = await client.post(
            "/api/v1/organizations/sync",
            headers={"Authorization": f"Bearer {missing_tok}"},
        )
    assert res_inactive.status_code == 403
    assert res_inactive.json()["detail"]["code"] == "org_inactive"

    # 3. Unconfigured CLERK_SECRET_KEY -> 403 org_inactive
    monkeypatch.setattr(settings, "CLERK_SECRET_KEY", None)
    res_unconf = await client.post(
        "/api/v1/organizations/sync",
        headers={"Authorization": f"Bearer {missing_tok}"},
    )
    assert res_unconf.status_code == 403
    assert res_unconf.json()["detail"]["code"] == "org_inactive"

    # 4. Clerk BAPI 500 -> 502 Bad Gateway
    monkeypatch.setattr(settings, "CLERK_SECRET_KEY", "sk_test_mock_secret_1234567890")
    mock_500_response = httpx.Response(500, json={"error": "upstream"})
    with patch("httpx.AsyncClient.get", new=AsyncMock(return_value=mock_500_response)):
        res_502 = await client.post(
            "/api/v1/organizations/sync",
            headers={"Authorization": f"Bearer {missing_tok}"},
        )
    assert res_502.status_code == 502

    # 5. Clerk BAPI 200 -> atomic upsert + audit log
    synced_clerk_id = f"org_sync_{uuid.uuid4().hex[:10]}"
    synced_slug = f"synced-{uuid.uuid4().hex[:8]}"
    sync_tok = make_clerk_jwt(
        _PRIV_PEM, user_id="user_sync_actor", clerk_org_id=synced_clerk_id
    )
    mock_200_response = httpx.Response(
        200,
        json={"id": synced_clerk_id, "name": "Synced Org", "slug": synced_slug},
    )

    with patch("httpx.AsyncClient.get", new=AsyncMock(return_value=mock_200_response)):
        res_ok = await client.post(
            "/api/v1/organizations/sync",
            headers={"Authorization": f"Bearer {sync_tok}"},
        )
    assert res_ok.status_code == 200
    body = res_ok.json()
    assert body["clerk_org_id"] == synced_clerk_id
    assert body["name"] == "Synced Org"
    assert body["slug"] == synced_slug
    synced_org_id = uuid.UUID(body["id"])

    audit_rows = (
        (
            await db_session.execute(
                select(AuditLogModel).where(AuditLogModel.org_id == synced_org_id)
            )
        )
        .scalars()
        .all()
    )
    assert len(audit_rows) == 1
    assert audit_rows[0].action == "organization.synced"
    assert audit_rows[0].actor_type == "user"
    assert audit_rows[0].actor_id == "user_sync_actor"


@pytest.mark.asyncio
async def test_require_org_admin_and_settings_persistence(
    client: AsyncClient, db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
):
    """Verify PATCH /organizations/settings checks org:admin and saves JSONB (AC-4)."""
    monkeypatch.setattr(settings, "CLERK_JWT_KEY", _PUB_PEM)
    org_repo = SqlAlchemyOrganizationRepository(db_session)
    org = await org_repo.create_or_update(
        clerk_org_id=f"org_settings_{uuid.uuid4().hex[:10]}",
        name="Settings Org",
        slug=f"settings-{uuid.uuid4().hex[:8]}",
    )
    await db_session.commit()

    member_tok = make_clerk_jwt(
        _PRIV_PEM,
        user_id="user_member_1",
        clerk_org_id=org.clerk_org_id,
        org_role="org:member",
    )
    admin_tok = make_clerk_jwt(
        _PRIV_PEM,
        user_id="user_admin_1",
        clerk_org_id=org.clerk_org_id,
        org_role="org:admin",
    )

    # 1. org:member -> 403 org_admin_required
    res_member = await client.patch(
        "/api/v1/organizations/settings",
        headers={"Authorization": f"Bearer {member_tok}"},
        json={"sandbox_provider": "docker", "timeout_minutes": 15},
    )
    assert res_member.status_code == 403
    assert res_member.json()["detail"]["code"] == "org_admin_required"

    # 2. org:admin -> 200 + persisted + audit log
    res_admin = await client.patch(
        "/api/v1/organizations/settings",
        headers={"Authorization": f"Bearer {admin_tok}"},
        json={"sandbox_provider": "docker", "timeout_minutes": 15},
    )
    assert res_admin.status_code == 200
    data = res_admin.json()
    assert data["settings"]["sandbox_provider"] == "docker"
    assert data["settings"]["timeout_minutes"] == 15

    # 3. Validation error -> 422
    res_invalid = await client.patch(
        "/api/v1/organizations/settings",
        headers={"Authorization": f"Bearer {admin_tok}"},
        json={"timeout_minutes": 0},
    )
    assert res_invalid.status_code == 422


@pytest.mark.asyncio
async def test_authorize_task_org_lazy_sync_on_task_get(
    client: AsyncClient, db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
):
    """Verify authorize_task_org lazy syncs missing org without ?org_id= (AC-6)."""
    monkeypatch.setattr(settings, "CLERK_JWT_KEY", _PUB_PEM)
    monkeypatch.setattr(settings, "CLERK_SECRET_KEY", "sk_test_mock_secret_1234567890")

    org_id = uuid.uuid4()
    repo_id = uuid.uuid4()
    task_id = uuid.uuid4()
    clerk_org_id = f"org_lazy_{org_id.hex[:10]}"
    slug = f"lazy-{org_id.hex[:8]}"

    # Seed soft-deleted org with child repo & task to trigger lazy sync
    org = OrganizationModel(
        id=org_id,
        clerk_org_id=clerk_org_id,
        name="Soft Deleted Org",
        slug=slug,
        deleted_at=datetime.now(UTC),
    )
    db_session.add(org)
    repo = RepositoryModel(
        id=repo_id,
        org_id=org_id,
        github_repo_id=55667788,
        github_installation_id=12345,
        name="lazy-repo",
        full_name="lazy/repo",
    )
    db_session.add(repo)
    task = TaskModel(
        id=task_id,
        org_id=org_id,
        repo_id=repo_id,
        title="Lazy Sync Task",
        description="Verify lazy sync on GET /tasks/{id}",
        status="queued",
        trigger_type="manual_console",
    )
    db_session.add(task)
    await db_session.commit()

    tok = make_clerk_jwt(_PRIV_PEM, user_id="user_lazy_1", clerk_org_id=clerk_org_id)
    orig_get = httpx.AsyncClient.get

    async def _selective_get(
        self: httpx.AsyncClient, url: str | httpx.URL, *args: object, **kwargs: object
    ) -> httpx.Response:
        if str(url).startswith("https://api.clerk.com"):
            return httpx.Response(
                200,
                json={"id": clerk_org_id, "name": "Reactivated Org", "slug": slug},
            )
        return await orig_get(self, url, *args, **kwargs)  # type: ignore[arg-type]

    with patch("httpx.AsyncClient.get", new=_selective_get):
        res = await client.get(
            f"/api/v1/tasks/{task_id}",
            headers={"Authorization": f"Bearer {tok}"},
        )
    assert res.status_code == 200
    assert res.json()["id"] == str(task_id)
    assert res.json()["org_id"] == str(org_id)
