"""Integration tests for GitHub webhook ingestion and task endpoints (AC-1)."""

import hashlib
import hmac
import json
import random
import uuid

import pytest
from httpx import AsyncClient
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.infrastructure.db.repositories.organization_repository import (
    SqlAlchemyOrganizationRepository,
)
from app.infrastructure.db.repositories.repository_repository import (
    SqlAlchemyRepositoryRepository,
)


def _sign_payload(
    payload_bytes: bytes, secret: str = settings.GITHUB_WEBHOOK_SECRET
) -> str:
    sig = hmac.new(secret.encode("utf-8"), payload_bytes, hashlib.sha256).hexdigest()
    return f"sha256={sig}"


@pytest.mark.asyncio
async def test_webhook_invalid_signature(client: AsyncClient):
    """Verify invalid webhook signature returns 401 Unauthorized (AC-1)."""
    payload = json.dumps({"action": "opened"}).encode("utf-8")
    response = await client.post(
        "/api/v1/webhooks/github",
        content=payload,
        headers={
            "X-GitHub-Event": "issues",
            "X-Hub-Signature-256": "sha256=invalid_hex_digest",
            "Content-Type": "application/json",
        },
    )
    assert response.status_code == 401
    assert "Invalid webhook signature" in response.json()["detail"]


@pytest.mark.asyncio
async def test_webhook_unhandled_event_returns_200_ignored(client: AsyncClient):
    """Verify unhandled webhook events return 200 OK with ignored status (AC-1)."""
    payload = json.dumps({"action": "unsupported_action"}).encode("utf-8")
    sig = _sign_payload(payload)

    response = await client.post(
        "/api/v1/webhooks/github",
        content=payload,
        headers={
            "X-GitHub-Event": "push",
            "X-Hub-Signature-256": sig,
            "Content-Type": "application/json",
        },
    )
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "ignored"
    assert "unhandled" in data["reason"]


@pytest.mark.asyncio
async def test_webhook_issues_opened_happy_path_and_duplicate(
    client: AsyncClient, db_session: AsyncSession
):
    """Verify issues.opened creates task, and repeat is ignored as duplicate (AC-1)."""
    org_repo = SqlAlchemyOrganizationRepository(db_session)
    repo_repo = SqlAlchemyRepositoryRepository(db_session)

    org = await org_repo.create_or_update(
        clerk_org_id=f"org_{uuid.uuid4().hex[:12]}",
        name="Webhook Test Org",
        slug=f"wh-org-{uuid.uuid4().hex[:8]}",
    )
    github_repo_id = random.randint(10000000, 89999999)
    repo = await repo_repo.create(
        org_id=org.id,
        github_repo_id=github_repo_id,
        github_installation_id=54321,
        name="test-webhook-repo",
        full_name="test-org/test-webhook-repo",
    )
    await db_session.commit()

    issue_number = 101
    webhook_data = {
        "action": "opened",
        "issue": {
            "number": issue_number,
            "title": "Add caching layer",
            "body": "Please add Redis cache to users endpoint",
            "html_url": f"https://github.com/test-org/test-webhook-repo/issues/{issue_number}",
        },
        "repository": {
            "id": github_repo_id,
            "default_branch": "main",
        },
        "sender": {"login": "octocat"},
    }
    payload_bytes = json.dumps(webhook_data).encode("utf-8")
    sig = _sign_payload(payload_bytes)

    try:
        # 1. First delivery should queue task
        response1 = await client.post(
            "/api/v1/webhooks/github",
            content=payload_bytes,
            headers={
                "X-GitHub-Event": "issues",
                "X-Hub-Signature-256": sig,
                "X-GitHub-Delivery": "delivery-1",
                "Content-Type": "application/json",
            },
        )
        assert response1.status_code == 200
        data1 = response1.json()
        assert data1["status"] == "queued"
        assert "task_id" in data1
        task_id = data1["task_id"]

        # 2. Second delivery for same issue while active should return 200 OK ignored
        response2 = await client.post(
            "/api/v1/webhooks/github",
            content=payload_bytes,
            headers={
                "X-GitHub-Event": "issues",
                "X-Hub-Signature-256": sig,
                "X-GitHub-Delivery": "delivery-2",
                "Content-Type": "application/json",
            },
        )
        assert response2.status_code == 200
        data2 = response2.json()
        assert data2["status"] == "ignored"
        assert data2["reason"] == "active_task_already_exists"
        assert data2["task_id"] == task_id

        # 3. Verify task details endpoint
        task_res = await client.get(f"/api/v1/tasks/{task_id}?org_id={org.id}")
        assert task_res.status_code == 200
        task_detail = task_res.json()
        assert task_detail["id"] == task_id
        assert task_detail["title"] == f"Fix issue #{issue_number}: Add caching layer"
        assert task_detail["status"] == "queued"
        assert task_detail["base_branch"] == "main"
        assert "agentsonair/task-" in task_detail["branch_name"]
    finally:
        await db_session.execute(
            text("DELETE FROM tasks WHERE repo_id = :rid"), {"rid": repo.id}
        )
        await db_session.execute(
            text("DELETE FROM repositories WHERE id = :rid"), {"rid": repo.id}
        )
        await db_session.execute(
            text("DELETE FROM organizations WHERE id = :oid"), {"oid": org.id}
        )
        await db_session.commit()


@pytest.mark.asyncio
async def test_webhook_issues_labeled_and_comment(
    client: AsyncClient, db_session: AsyncSession
):
    """Verify labeled (agentsonair) and comment (@agentsonair) triggers (AC-1)."""
    org_repo = SqlAlchemyOrganizationRepository(db_session)
    repo_repo = SqlAlchemyRepositoryRepository(db_session)

    org = await org_repo.create_or_update(
        clerk_org_id=f"org_{uuid.uuid4().hex[:12]}",
        name="Label Test Org",
        slug=f"lbl-org-{uuid.uuid4().hex[:8]}",
    )
    github_repo_id = random.randint(90000000, 99999999)
    repo = await repo_repo.create(
        org_id=org.id,
        github_repo_id=github_repo_id,
        github_installation_id=65432,
        name="test-label-repo",
        full_name="test-org/test-label-repo",
    )
    await db_session.commit()

    try:
        # 1. Non-matching label should be ignored
        payload_bad_label = json.dumps(
            {
                "action": "labeled",
                "label": {"name": "bug"},
                "issue": {"number": 201, "title": "Some bug"},
                "repository": {"id": github_repo_id},
            }
        ).encode("utf-8")
        resp_bad = await client.post(
            "/api/v1/webhooks/github",
            content=payload_bad_label,
            headers={
                "X-GitHub-Event": "issues",
                "X-Hub-Signature-256": _sign_payload(payload_bad_label),
            },
        )
        assert resp_bad.status_code == 200
        assert resp_bad.json()["status"] == "ignored"

        # 2. Matching label "agentsonair" should queue task
        payload_good_label = json.dumps(
            {
                "action": "labeled",
                "label": {"name": "agentsonair"},
                "issue": {
                    "number": 202,
                    "title": "Important bug",
                    "body": "Details here",
                },
                "repository": {"id": github_repo_id},
            }
        ).encode("utf-8")
        resp_good = await client.post(
            "/api/v1/webhooks/github",
            content=payload_good_label,
            headers={
                "X-GitHub-Event": "issues",
                "X-Hub-Signature-256": _sign_payload(payload_good_label),
            },
        )
        assert resp_good.status_code == 200
        assert resp_good.json()["status"] == "queued"

        # 3. Comment without mention should be ignored
        payload_bad_comment = json.dumps(
            {
                "action": "created",
                "comment": {"body": "Just a normal comment"},
                "issue": {"number": 203, "title": "Normal issue"},
                "repository": {"id": github_repo_id},
            }
        ).encode("utf-8")
        resp_comm_bad = await client.post(
            "/api/v1/webhooks/github",
            content=payload_bad_comment,
            headers={
                "X-GitHub-Event": "issue_comment",
                "X-Hub-Signature-256": _sign_payload(payload_bad_comment),
            },
        )
        assert resp_comm_bad.status_code == 200
        assert resp_comm_bad.json()["status"] == "ignored"

        # 4. Comment with @agentsonair should queue task
        payload_good_comment = json.dumps(
            {
                "action": "created",
                "comment": {"body": "Hey @agentsonair please fix this"},
                "issue": {
                    "number": 204,
                    "title": "Need help issue",
                    "body": "Original issue",
                },
                "repository": {"id": github_repo_id},
                "sender": {"login": "dev_user"},
            }
        ).encode("utf-8")
        resp_comm_good = await client.post(
            "/api/v1/webhooks/github",
            content=payload_good_comment,
            headers={
                "X-GitHub-Event": "issue_comment",
                "X-Hub-Signature-256": _sign_payload(payload_good_comment),
            },
        )
        assert resp_comm_good.status_code == 200
        assert resp_comm_good.json()["status"] == "queued"
    finally:
        await db_session.execute(
            text("DELETE FROM tasks WHERE repo_id = :rid"), {"rid": repo.id}
        )
        await db_session.execute(
            text("DELETE FROM repositories WHERE id = :rid"), {"rid": repo.id}
        )
        await db_session.execute(
            text("DELETE FROM organizations WHERE id = :oid"), {"oid": org.id}
        )
        await db_session.commit()


@pytest.mark.asyncio
async def test_webhook_missing_signature_header_returns_401(client: AsyncClient):
    """Verify missing signature header returns 401 Unauthorized (AC-1)."""
    payload = json.dumps({"action": "opened"}).encode("utf-8")
    response = await client.post(
        "/api/v1/webhooks/github",
        content=payload,
        headers={
            "X-GitHub-Event": "issues",
            "Content-Type": "application/json",
        },
    )
    assert response.status_code == 401
    assert "Invalid webhook signature" in response.json()["detail"]


@pytest.mark.asyncio
async def test_webhook_untracked_repo_returns_200_ignored(client: AsyncClient):
    """Verify webhooks for untracked repositories return 200 OK ignored (AC-1)."""
    untracked_repo_id = 999999999
    payload = json.dumps(
        {
            "action": "opened",
            "issue": {"number": 501, "title": "Untracked issue"},
            "repository": {"id": untracked_repo_id, "default_branch": "main"},
            "sender": {"login": "octocat"},
        }
    ).encode("utf-8")
    sig = _sign_payload(payload)

    response = await client.post(
        "/api/v1/webhooks/github",
        content=payload,
        headers={
            "X-GitHub-Event": "issues",
            "X-Hub-Signature-256": sig,
            "Content-Type": "application/json",
        },
    )
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "ignored"
    assert data["reason"] == "repository_not_tracked"


@pytest.mark.asyncio
async def test_webhook_empty_payload_returns_200_ignored(client: AsyncClient):
    """Verify empty payloads return 200 OK ignored without error (AC-1)."""
    payload = b""
    sig = _sign_payload(payload)

    response = await client.post(
        "/api/v1/webhooks/github",
        content=payload,
        headers={
            "X-GitHub-Event": "issues",
            "X-Hub-Signature-256": sig,
            "Content-Type": "application/json",
        },
    )
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "ignored"
    assert "malformed_json_payload" in data["reason"]
