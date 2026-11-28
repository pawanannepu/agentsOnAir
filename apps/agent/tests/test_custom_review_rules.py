"""Comprehensive tests for Spec 0009: Custom review rules & feedback learning."""

import hashlib
import hmac
import json
import uuid
from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock

import httpx
import pytest
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.application.ports.model_gateway import (
    ForgeAgent,
    ForgeResult,
    ReviewerCritic,
    ReviewerResult,
)
from app.application.services.context_budget_allocator import ContextBudgetAllocator
from app.application.services.review_context_service import ReviewContextService
from app.application.services.sandbox_workspace import SandboxWorkspace
from app.application.services.symbol_indexer import SymbolCallGraph
from app.application.use_cases.ingest_github_webhook import IngestGitHubWebhookUseCase
from app.application.use_cases.review_examples import parse_example_pr_input
from app.application.use_cases.run_pr_review import RunPRReviewUseCase
from app.core.config import settings
from app.core.redaction import redact_credentials, sanitize_prompt_text
from app.domain.entities.review_example import ReviewExample
from app.domain.entities.review_feedback import ReviewLearnedPreference
from app.domain.entities.review_rule import EffectiveReviewRule
from app.domain.exceptions import ValidationError
from app.infrastructure.db.models.audit_log import AuditLogModel
from app.infrastructure.db.models.organization import OrganizationModel
from app.infrastructure.db.models.pr_review_finding import PRReviewFindingModel
from app.infrastructure.db.models.pull_request_review import PullRequestReviewModel
from app.infrastructure.db.models.repository import RepositoryModel
from app.infrastructure.db.models.review_example import ReviewExampleModel
from app.infrastructure.db.models.review_learned_preference import (
    ReviewLearnedPreferenceModel,
)
from app.infrastructure.db.models.review_rule import ReviewRuleModel
from app.infrastructure.db.models.review_rule_override import ReviewRuleOverrideModel
from app.infrastructure.db.models.task import TaskModel
from app.infrastructure.db.models.task_run import TaskRunModel
from app.infrastructure.db.models.usage_event import UsageEventModel
from app.infrastructure.db.repositories.pr_review_repository import (
    SqlAlchemyPRReviewRepository,
)
from app.infrastructure.db.repositories.repository_repository import (
    SqlAlchemyRepositoryRepository,
)
from app.infrastructure.db.repositories.review_feedback_repository import (
    SqlAlchemyReviewFeedbackRepository,
)
from app.infrastructure.db.repositories.task_repository import (
    SqlAlchemyTaskRepository,
)
from app.infrastructure.github.github_service import GitHubService
from app.infrastructure.github.review_publisher import GitHubReviewPublisher
from app.infrastructure.llm.agents import ReviewerCriticAgent
from app.infrastructure.llm.reviewer_node import CodeReviewAnalyzerNode
from app.infrastructure.llm.task_graph import (
    PostgresTaskCheckpointSaver,
    build_task_cycle_graph,
)
from tests.clerk_test_helpers import generate_rsa_keypair, make_clerk_jwt

_PRIV_PEM, _PUB_PEM = generate_rsa_keypair()


@pytest.fixture(autouse=True)
def _configure_clerk_key(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "CLERK_JWT_KEY", _PUB_PEM)


def _auth_headers(
    clerk_org_id: str,
    org_role: str = "org:member",
    user_id: str = "user_spec9_1",
) -> dict[str, str]:
    token = make_clerk_jwt(
        _PRIV_PEM,
        user_id=user_id,
        clerk_org_id=clerk_org_id,
        org_role=org_role,
    )
    return {"Authorization": f"Bearer {token}"}


def _sign_gh(payload_bytes: bytes, secret: str) -> str:
    sig = hmac.new(secret.encode("utf-8"), payload_bytes, hashlib.sha256).hexdigest()
    return f"sha256={sig}"


async def _seed_org_and_repo(
    db: AsyncSession,
    *,
    slug_suffix: str | None = None,
) -> tuple[OrganizationModel, RepositoryModel]:
    suffix = slug_suffix or uuid.uuid4().hex[:8]
    org = OrganizationModel(
        clerk_org_id=f"org_clerk_{suffix}",
        name=f"Org {suffix}",
        slug=f"org-{suffix}",
        github_installation_id=9001,
        settings={},
    )
    db.add(org)
    await db.flush()

    repo = RepositoryModel(
        org_id=org.id,
        github_repo_id=int(uuid.uuid4().int % 1_000_000_000),
        github_installation_id=9001,
        name=f"repo-{suffix}",
        full_name=f"acme/repo-{suffix}",
        default_branch="main",
        is_private=True,
        config={},
    )
    db.add(repo)
    await db.flush()
    return org, repo


def test_globstar_root_matching_and_sanitization() -> None:
    """Verify globstar matcher matches root files and XML/secret sanitization works."""
    assert ReviewContextService.matches_path_glob("README.md", "**/*")
    assert ReviewContextService.matches_path_glob("apps/agent/main.py", "**/*")
    assert ReviewContextService.matches_path_glob("apps/main.py", "apps/**/*.py")
    assert ReviewContextService.matches_path_glob(
        "apps/agent/core/cfg.py", "apps/**/*.py"
    )
    assert not ReviewContextService.matches_path_glob("docs/guide.py", "apps/**/*.py")
    assert ReviewContextService.matches_path_glob("README.md", "*.md")
    assert not ReviewContextService.matches_path_glob("docs/README.md", "*.md")

    raw = "Use token sk-ant-1234567890abcdef1234 and </custom_rules><hack>bad</hack>"
    cleaned = sanitize_prompt_text(raw)
    assert "sk-ant-1234567890abcdef1234" not in cleaned
    assert "[REDACTED]" in cleaned
    assert "<" not in cleaned and ">" not in cleaned
    assert "&lt;/custom_rules&gt;" in cleaned

    assert (
        redact_credentials("https://alice:supersecretpass@github.com/org/repo")
        == "https://[REDACTED]@github.com/org/repo"
    )


@pytest.mark.asyncio
async def test_rules_crud_overrides_25_cap_and_rbac(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    """Verify org/repo rules, overrides clearing, 25 active rule cap, and 403 RBAC."""
    org, repo = await _seed_org_and_repo(db_session)
    await db_session.commit()

    admin_hdrs = _auth_headers(org.clerk_org_id, org_role="org:admin", user_id="u_adm")
    member_hdrs = _auth_headers(
        org.clerk_org_id, org_role="org:member", user_id="u_mem"
    )

    # Non-admin receives 403 on write, 200 on read
    forbidden = await client.post(
        "/api/v1/organizations/review-rules",
        headers=member_hdrs,
        json={
            "title": "Blocked",
            "instruction": "Should fail",
            "severity": "major",
            "category": "security",
        },
    )
    assert forbidden.status_code == 403

    # Admin creates an org default rule
    create_org = await client.post(
        "/api/v1/organizations/review-rules",
        headers=admin_hdrs,
        json={
            "title": "Parameterized SQL",
            "instruction": "Never interpolate strings into SQL.",
            "severity": "critical",
            "category": "security",
            "path_globs": ["**/*"],
            "is_enabled": True,
        },
    )
    assert create_org.status_code == 201
    org_rule_id = create_org.json()["id"]

    # Validation error on empty path_globs
    bad_globs = await client.post(
        "/api/v1/organizations/review-rules",
        headers=admin_hdrs,
        json={
            "title": "Empty globs",
            "instruction": "Invalid",
            "severity": "minor",
            "category": "style",
            "path_globs": ["   "],
        },
    )
    assert bad_globs.status_code == 422

    # Admin overrides org rule severity for repo, then clears it
    put_ov = await client.put(
        f"/api/v1/repositories/{repo.id}/review-rules/{org_rule_id}/override",
        headers=admin_hdrs,
        json={"is_enabled": True, "severity_override": "minor"},
    )
    assert put_ov.status_code == 200
    assert put_ov.json()["cleared"] is False
    assert put_ov.json()["effective_rule"]["severity"] == "minor"

    clear_ov = await client.put(
        f"/api/v1/repositories/{repo.id}/review-rules/{org_rule_id}/override",
        headers=admin_hdrs,
        json={"is_enabled": None, "severity_override": None},
    )
    assert clear_ov.status_code == 200
    assert clear_ov.json()["cleared"] is True
    assert clear_ov.json()["effective_rule"]["severity"] == "critical"

    ov_rows = (
        (
            await db_session.execute(
                select(ReviewRuleOverrideModel).where(
                    ReviewRuleOverrideModel.repo_id == repo.id
                )
            )
        )
        .scalars()
        .all()
    )
    assert ov_rows == []

    # Seed 23 repo rules in bulk, then create 25th (1 org + 24 repo = 25) via HTTP
    db_session.add_all(
        [
            ReviewRuleModel(
                org_id=org.id,
                repo_id=repo.id,
                title=f"Repo rule {i}",
                instruction=f"Check convention {i}",
                severity="minor",
                category="architecture",
                path_globs=["**/*"],
                is_enabled=True,
                created_by="u_adm",
            )
            for i in range(23)
        ]
    )
    await db_session.commit()

    res_25 = await client.post(
        f"/api/v1/repositories/{repo.id}/review-rules",
        headers=admin_hdrs,
        json={
            "title": "Repo rule 24",
            "instruction": "Check convention 24",
            "severity": "minor",
            "category": "architecture",
        },
    )
    assert res_25.status_code == 201
    last_repo_rule_id = res_25.json()["id"]

    # 26th active rule fails with 422
    over_cap = await client.post(
        f"/api/v1/repositories/{repo.id}/review-rules",
        headers=admin_hdrs,
        json={
            "title": "Rule 26",
            "instruction": "Should hit cap",
            "severity": "minor",
            "category": "style",
        },
    )
    assert over_cap.status_code == 422

    # Soft deleting a rule frees a slot
    del_res = await client.delete(
        f"/api/v1/repositories/{repo.id}/review-rules/{last_repo_rule_id}",
        headers=admin_hdrs,
    )
    assert del_res.status_code == 204

    retry_res = await client.post(
        f"/api/v1/repositories/{repo.id}/review-rules",
        headers=admin_hdrs,
        json={
            "title": "Replacement rule",
            "instruction": "Now fits within 25 cap",
            "severity": "major",
            "category": "bug",
        },
    )
    assert retry_res.status_code == 201

    # Member can read merged repo rules
    member_read = await client.get(
        f"/api/v1/repositories/{repo.id}/review-rules",
        headers=member_hdrs,
    )
    assert member_read.status_code == 200
    assert member_read.json()["active_count"] == 25

    # Verify audit logs recorded
    audits = (
        (
            await db_session.execute(
                select(AuditLogModel.action).where(AuditLogModel.org_id == org.id)
            )
        )
        .scalars()
        .all()
    )
    assert "review_rule.created" in audits
    assert "review_rule_override.updated" in audits
    assert "review_rule.deleted" in audits


@pytest.mark.asyncio
async def test_example_prs_github_http_redaction_and_cap(
    client: AsyncClient, db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Verify GitHub HTTP PR fetch, mismatch 422, redaction, and 5-PR cap."""
    org, repo = await _seed_org_and_repo(db_session)
    await db_session.commit()
    admin_hdrs = _auth_headers(org.clerk_org_id, org_role="org:admin")

    big_body_lines = "\n".join(f"+line_{idx} = 'value_{idx}'" for idx in range(700))
    sample_diff = (
        "diff --git a/src/auth.py b/src/auth.py\n"
        "--- a/src/auth.py\n"
        "+++ b/src/auth.py\n"
        "@@ -1,3 +1,5 @@\n"
        "+API_KEY = 'ghp_abcdefghijklmnopqrstuvwxyz123456'\n"
        f"{big_body_lines}\n"
    )

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == f"/repos/{repo.full_name}/pulls/42":
            if "diff" in request.headers.get("Accept", ""):
                return httpx.Response(200, text=sample_diff)
            return httpx.Response(
                200,
                json={
                    "number": 42,
                    "title": "Clean auth refactor",
                    "html_url": f"https://github.com/{repo.full_name}/pull/42",
                    "base": {"repo": {"full_name": repo.full_name}},
                },
            )
        if request.url.path.endswith("/pulls/99"):
            return httpx.Response(
                200,
                json={
                    "number": 99,
                    "title": "Foreign repo PR",
                    "base": {"repo": {"full_name": "other/foreign-repo"}},
                },
            )
        if request.url.path.endswith("/pulls/100"):
            return httpx.Response(
                200,
                json={
                    "number": 100,
                    "title": "Simple PR",
                    "html_url": f"https://github.com/{repo.full_name}/pull/100",
                    "base": {"repo": {"full_name": repo.full_name}},
                },
            )
        if "diff" in request.headers.get("Accept", ""):
            return httpx.Response(
                200,
                text=(
                    "diff --git a/app.py b/app.py\n"
                    "--- a/app.py\n+++ b/app.py\n@@ -1 +1 @@\n+x=1\n"
                ),
            )
        m_num = int(request.url.path.rsplit("/", 1)[-1])
        return httpx.Response(
            200,
            json={
                "number": m_num,
                "title": f"PR {m_num}",
                "html_url": f"https://github.com/{repo.full_name}/pull/{m_num}",
                "base": {"repo": {"full_name": repo.full_name}},
            },
        )

    transport = httpx.MockTransport(handler)
    orig_init = GitHubService.__init__

    def _patched_init(self, app_id=None, private_key=None, **kwargs):
        orig_init(
            self,
            app_id=app_id,
            private_key=private_key,
            http_client=httpx.AsyncClient(transport=transport),
        )

    monkeypatch.setattr(GitHubService, "__init__", _patched_init)

    # Cross-repo URL rejected with 422
    bad_url = await client.post(
        f"/api/v1/repositories/{repo.id}/review-examples",
        headers=admin_hdrs,
        json={
            "pr_url": "https://github.com/other/repo/pull/99",
            "classification": "good",
            "guidance_note": "Wrong repo",
        },
    )
    assert bad_url.status_code == 422

    # Base repo mismatch from GitHub payload rejected with 422
    mismatch_pr = await client.post(
        f"/api/v1/repositories/{repo.id}/review-examples",
        headers=admin_hdrs,
        json={
            "pr_number": 99,
            "classification": "good",
            "guidance_note": "Mismatched base repo",
        },
    )
    assert mismatch_pr.status_code == 422

    # Valid PR #42 caches modified_files, redacts token, and caps <= 1500 tokens
    created = await client.post(
        f"/api/v1/repositories/{repo.id}/review-examples",
        headers=admin_hdrs,
        json={
            "pr_url": f"https://github.com/{repo.full_name}/pull/42",
            "classification": "good",
            "guidance_note": "Follow this pattern",
        },
    )
    assert created.status_code == 201
    ex = created.json()
    assert ex["modified_files"] == ["src/auth.py"]
    assert "ghp_abcdefghijklmnopqrstuvwxyz123456" not in (
        ex["cached_diff_summary"] or ""
    )
    assert "[REDACTED]" in (ex["cached_diff_summary"] or "")
    assert "+++ b/src/auth.py" in (ex["cached_diff_summary"] or "")
    assert ex["cached_token_count"] <= 1500

    # Refresh works
    refreshed = await client.post(
        f"/api/v1/repositories/{repo.id}/review-examples/{ex['id']}/refresh",
        headers=admin_hdrs,
    )
    assert refreshed.status_code == 200

    # 4 more examples hit cap of 5, 6th returns 422
    for pr_num in (101, 102, 103, 104):
        r = await client.post(
            f"/api/v1/repositories/{repo.id}/review-examples",
            headers=admin_hdrs,
            json={
                "pr_number": pr_num,
                "classification": "bad",
                "guidance_note": f"Avoid {pr_num}",
            },
        )
        assert r.status_code == 201

    sixth = await client.post(
        f"/api/v1/repositories/{repo.id}/review-examples",
        headers=admin_hdrs,
        json={
            "pr_number": 105,
            "classification": "good",
            "guidance_note": "Over 5 cap",
        },
    )
    assert sixth.status_code == 422


@pytest.mark.asyncio
async def test_feedback_learning_idempotency_webhooks_and_comment_backfill(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    """Verify comment ID backfill, feedback dampening/suppression, and webhooks."""
    org, repo = await _seed_org_and_repo(db_session)

    # Create a review + 4 findings on src/api.py
    review = PullRequestReviewModel(
        org_id=org.id,
        repo_id=repo.id,
        pr_number=77,
        pr_title="Add payments endpoint",
        pr_author="alice",
        head_commit_sha="a" * 40,
        base_commit_sha="b" * 40,
        status="completed",
        verdict="changes_requested",
        model_name="claude-sonnet-4",
        execution_duration_ms=1200,
    )
    db_session.add(review)
    await db_session.flush()

    findings: list[PRReviewFindingModel] = []
    for idx in range(4):
        f = PRReviewFindingModel(
            review_id=review.id,
            file_path="src/api.py",
            line_number=10 + idx,
            side="RIGHT",
            severity="major",
            category="style",
            title=f"Style nit {idx}",
            message=f"Consider formatting line {10 + idx}",
        )
        db_session.add(f)
        findings.append(f)
    await db_session.commit()

    # 1. Test GitHubReviewPublisher comment ID backfill via MockTransport
    diff_text = (
        "diff --git a/src/api.py b/src/api.py\n"
        "--- a/src/api.py\n"
        "+++ b/src/api.py\n"
        "@@ -9,5 +9,10 @@\n"
        "+line 10\n+line 11\n+line 12\n+line 13\n"
    )
    expected_body = f"**[MAJOR] {findings[0].title}**\n\n{findings[0].message}"

    def gh_handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/comments"):
            return httpx.Response(
                200,
                json=[
                    {
                        "id": 555001,
                        "path": "src/api.py",
                        "original_line": 10,
                        "body": expected_body,
                    }
                ],
            )
        return httpx.Response(404)

    gh = GitHubService(
        http_client=httpx.AsyncClient(transport=httpx.MockTransport(gh_handler))
    )
    publisher = GitHubReviewPublisher(gh)
    pr_review_repo = SqlAlchemyPRReviewRepository(db_session)
    pub_res = await publisher.publish(
        repo_full_name=repo.full_name,
        pr_number=77,
        head_commit_sha="a" * 40,
        verdict="comment",
        summary="Summary",
        findings=[
            {
                "id": findings[0].id,
                "file_path": "src/api.py",
                "line_number": 10,
                "severity": "major",
                "category": "style",
                "title": findings[0].title,
                "message": findings[0].message,
            }
        ],
        diff_text=diff_text,
        token="tok",
        pr_review_repo=pr_review_repo,
    )
    assert pub_res.comment_id_mappings == [(findings[0].id, 555001)]
    await db_session.commit()
    await db_session.refresh(findings[0])
    assert findings[0].github_comment_id == 555001

    # 2. Console feedback + idempotency + progression to dampened -> suppressed
    member_hdrs = _auth_headers(org.clerk_org_id, org_role="org:member")
    admin_hdrs = _auth_headers(org.clerk_org_id, org_role="org:admin")

    # Dismiss finding 0 twice -> count stays 1 (idempotent)
    r1 = await client.post(
        f"/api/v1/reviews/findings/{findings[0].id}/feedback",
        headers=member_hdrs,
        json={
            "feedback_type": "dismissed",
            "reason": "Team uses compact syntax",
            "remember_preference": True,
        },
    )
    assert r1.status_code == 200
    assert r1.json()["learned_preference"]["dismiss_count"] == 1
    assert r1.json()["learned_preference"]["status"] == "active"

    r1_dup = await client.post(
        f"/api/v1/reviews/findings/{findings[0].id}/feedback",
        headers=member_hdrs,
        json={"feedback_type": "dismissed"},
    )
    assert r1_dup.status_code == 200
    assert r1_dup.json()["deduplicated"] is True
    assert r1_dup.json()["learned_preference"]["dismiss_count"] == 1

    # Dismiss finding 1 -> consecutive_dismissals = 2 -> dampened
    r2 = await client.post(
        f"/api/v1/reviews/findings/{findings[1].id}/feedback",
        headers=member_hdrs,
        json={"feedback_type": "dismissed"},
    )
    assert r2.status_code == 200
    assert r2.json()["learned_preference"]["consecutive_dismissals"] == 2
    assert r2.json()["learned_preference"]["status"] == "dampened"

    # 3. GitHub reply webhook dismisses finding 2 -> streak 3 -> suppressed
    findings[2].github_comment_id = 555002
    await db_session.commit()

    ingest_uc = IngestGitHubWebhookUseCase(
        repository_repo=SqlAlchemyRepositoryRepository(db_session),
        task_repo=SqlAlchemyTaskRepository(db_session),
        pr_review_repo=pr_review_repo,
        review_feedback_repo=SqlAlchemyReviewFeedbackRepository(db_session),
    )

    deliv_suffix = uuid.uuid4().hex[:8]
    member_deliv_id = f"deliv-member-1-{deliv_suffix}"

    # Unauthorized NONE association ignored
    unauth_payload = json.dumps(
        {
            "action": "created",
            "repository": {"id": repo.github_repo_id},
            "sender": {"login": "outsider", "type": "User"},
            "comment": {
                "id": 888,
                "in_reply_to_id": 555002,
                "author_association": "NONE",
                "body": "dismiss this",
            },
        }
    ).encode()
    unauth_res = await ingest_uc.execute(
        event_type="pull_request_review_comment",
        delivery_id=f"deliv-unauth-1-{deliv_suffix}",
        payload_bytes=unauth_payload,
        signature_header=_sign_gh(unauth_payload, "sec"),
        webhook_secret="sec",
    )
    assert unauth_res.status == "ignored"
    assert unauth_res.reason == "unauthorized_author_association"

    # Authorized MEMBER reply with "False positive: intentional"
    auth_payload = json.dumps(
        {
            "action": "created",
            "repository": {"id": repo.github_repo_id},
            "sender": {"login": "teammate", "type": "User"},
            "comment": {
                "id": 889,
                "in_reply_to_id": 555002,
                "author_association": "MEMBER",
                "body": "False positive: intentional helper",
            },
        }
    ).encode()
    auth_res = await ingest_uc.execute(
        event_type="pull_request_review_comment",
        delivery_id=member_deliv_id,
        payload_bytes=auth_payload,
        signature_header=_sign_gh(auth_payload, "sec"),
        webhook_secret="sec",
    )
    assert auth_res.status == "processed"

    # Duplicate delivery ignored atomically
    dup_res = await ingest_uc.execute(
        event_type="pull_request_review_comment",
        delivery_id=member_deliv_id,
        payload_bytes=auth_payload,
        signature_header=_sign_gh(auth_payload, "sec"),
        webhook_secret="sec",
    )
    assert dup_res.status == "ignored"
    assert dup_res.reason == "duplicate_delivery"

    pref_row = (
        await db_session.execute(
            select(ReviewLearnedPreferenceModel).where(
                ReviewLearnedPreferenceModel.repo_id == repo.id,
                ReviewLearnedPreferenceModel.pattern_key == "style:src",
            )
        )
    ).scalar_one()
    assert pref_row.status == "suppressed"
    assert pref_row.consecutive_dismissals == 3

    # 4. Thread resolved -> accepted resets streak = 0, unresolved resets finding
    thread_resolved = json.dumps(
        {
            "action": "resolved",
            "repository": {"id": repo.github_repo_id},
            "sender": {
                "login": "maintainer",
                "type": "User",
                "author_association": "OWNER",
            },
            "thread": {"comments": [{"id": 555001}]},
        }
    ).encode()
    res_resolved = await ingest_uc.execute(
        event_type="pull_request_review_thread",
        delivery_id=f"deliv-thread-1-{deliv_suffix}",
        payload_bytes=thread_resolved,
        signature_header=_sign_gh(thread_resolved, "sec"),
        webhook_secret="sec",
    )
    assert res_resolved.status == "processed"
    await db_session.refresh(pref_row)
    assert pref_row.status == "active"
    assert pref_row.consecutive_dismissals == 0

    thread_unresolved = json.dumps(
        {
            "action": "unresolved",
            "repository": {"id": repo.github_repo_id},
            "sender": {
                "login": "maintainer",
                "type": "User",
                "author_association": "OWNER",
            },
            "thread": {"comments": [{"id": 555001}]},
        }
    ).encode()
    res_unresolved = await ingest_uc.execute(
        event_type="pull_request_review_thread",
        delivery_id=f"deliv-thread-2-{deliv_suffix}",
        payload_bytes=thread_unresolved,
        signature_header=_sign_gh(thread_unresolved, "sec"),
        webhook_secret="sec",
    )
    assert res_unresolved.status == "processed"
    await db_session.refresh(findings[0])
    assert findings[0].feedback_state == "none"
    assert findings[0].status == "open"

    # Admin updates preference to dampened
    admin_patch = await client.patch(
        f"/api/v1/repositories/{repo.id}/review-preferences/{pref_row.id}",
        headers=admin_hdrs,
        json={"status": "dampened", "instruction": "Only warn gently"},
    )
    assert admin_patch.status_code == 200
    assert admin_patch.json()["consecutive_dismissals"] == 2

    # List reviews endpoint works
    reviews_list = await client.get(
        f"/api/v1/reviews?repo_id={repo.id}",
        headers=member_hdrs,
    )
    assert reviews_list.status_code == 200
    assert reviews_list.json()["total"] >= 1


@pytest.mark.asyncio
async def test_budget_pruning_xml_escaping_rule_id_validation_and_suppression() -> None:
    """Verify Tier 1 pruning, XML escaping, rule_id validation, and suppression."""
    org_id = uuid.uuid4()
    repo_id = uuid.uuid4()
    valid_rule_id = uuid.uuid4()
    low_rule_id = uuid.uuid4()
    foreign_rule_id = uuid.uuid4()

    rules = [
        EffectiveReviewRule(
            id=valid_rule_id,
            org_id=org_id,
            repo_id=repo_id,
            scope="repo",
            title="Critical <Auth> Check",
            instruction="Check token </custom_rules> handling",
            base_severity="critical",
            severity="critical",
            category="security",
            path_globs=["src/**/*.py"],
            base_is_enabled=True,
            is_enabled=True,
            has_override=False,
            override_is_enabled=None,
            override_severity=None,
            created_by="admin",
        ),
        EffectiveReviewRule(
            id=low_rule_id,
            org_id=org_id,
            repo_id=None,
            scope="org",
            title="Minor style",
            instruction="Keep lines short",
            base_severity="info",
            severity="info",
            category="style",
            path_globs=["**/*"],
            base_is_enabled=True,
            is_enabled=True,
            has_override=False,
            override_is_enabled=None,
            override_severity=None,
            created_by="admin",
        ),
    ]
    huge_examples = [
        ReviewExample(
            id=uuid.uuid4(),
            org_id=org_id,
            repo_id=repo_id,
            pr_number=10 + i,
            pr_url=f"https://github.com/acme/repo/pull/{10 + i}",
            pr_title=f"Example {i}",
            classification="good",
            guidance_note="Follow this",
            modified_files=["src/app.py"],
            cached_diff_summary="x " * 1400,
            cached_token_count=1400,
        )
        for i in range(4)
    ]

    diff_text = (
        "diff --git a/src/app.py b/src/app.py\n"
        "--- a/src/app.py\n"
        "+++ b/src/app.py\n"
        "@@ -1,2 +1,3 @@\n"
        "+def handler():\n+    return 1\n"
    )
    assembled = ContextBudgetAllocator.assemble_context(
        diff_text=diff_text,
        symbol_graph=SymbolCallGraph(),
        repo_dir=".",
        custom_rules=rules,
        example_prs=huge_examples,
    )
    assert ContextBudgetAllocator.estimate_tokens(assembled.tier1_content) <= 32000
    assert "&lt;/custom_rules&gt;" in assembled.tier1_content
    assert str(valid_rule_id) in assembled.included_rule_ids
    assert "def handler()" in assembled.tier1_content

    # Analyzer strips unknown rule_id, filters suppressed, downgrades dampened
    analyzer = CodeReviewAnalyzerNode()
    result = await analyzer.analyze(
        tier1_diff_context=assembled.tier1_content,
        tier2_symbol_context=assembled.tier2_content,
        active_rule_ids={valid_rule_id},
        dampened_patterns={f"rule:{valid_rule_id}"},
        suppressed_patterns={"style:src"},
        simulated_findings=[
            {
                "file_path": "src/app.py",
                "line_number": 2,
                "severity": "major",
                "category": "security",
                "title": "Dampened rule finding",
                "message": "Check auth",
                "rule_id": valid_rule_id,
            },
            {
                "file_path": "src/app.py",
                "line_number": 3,
                "severity": "minor",
                "category": "style",
                "title": "Suppressed style finding",
                "message": "Should be filtered out",
                "rule_id": foreign_rule_id,
            },
        ],
    )
    assert len(result.findings) == 1
    assert result.findings[0]["severity"] == "info"
    assert result.findings[0]["rule_id"] == valid_rule_id
    assert result.blocking_count == 0
    assert result.verdict == "comment"

    # Autonomous ReviewerCriticAgent respects custom rules, XML escaping, & suppression
    critic = ReviewerCriticAgent()
    critic_res = await critic.evaluate(
        {
            "target_file": "src/app.py",
            "custom_rules": [
                {
                    "id": str(valid_rule_id),
                    "title": "Rule",
                    "instruction": "No <script>",
                    "severity": "major",
                    "category": "security",
                }
            ],
            "suppressed_patterns": ["style:src"],
            "dampened_patterns": [f"rule:{valid_rule_id}"],
            "simulated_findings": [
                {
                    "file_path": "src/app.py",
                    "line_number": 5,
                    "severity": "critical",
                    "category": "security",
                    "message": "Rule hit",
                    "rule_id": str(valid_rule_id),
                },
                {
                    "file_path": "src/app.py",
                    "line_number": 6,
                    "severity": "minor",
                    "category": "style",
                    "message": "Suppressed",
                    "rule_id": str(foreign_rule_id),
                },
            ],
        },
        diff=diff_text,
        test_output="ok",
    )
    assert len(critic_res.findings) == 1
    assert critic_res.findings[0]["severity"] == "info"
    assert critic_res.verdict == "approved"


@pytest.mark.asyncio
async def test_analytics_overview_sql_percentiles_costs_and_errors(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    """Verify analytics overview percentiles, paused_seconds, cost split, & errors."""
    org, repo = await _seed_org_and_repo(db_session)
    other_org, other_repo = await _seed_org_and_repo(db_session)

    now = datetime.now(UTC)

    # Create 2 completed PR reviews (1000ms and 3000ms)
    r1 = PullRequestReviewModel(
        org_id=org.id,
        repo_id=repo.id,
        pr_number=1,
        pr_title="PR 1",
        pr_author="dev",
        head_commit_sha="1" * 40,
        base_commit_sha="2" * 40,
        status="completed",
        verdict="comment",
        model_name="claude-sonnet-4",
        execution_duration_ms=1000,
        created_at=now,
    )
    r2 = PullRequestReviewModel(
        org_id=org.id,
        repo_id=repo.id,
        pr_number=2,
        pr_title="PR 2",
        pr_author="dev",
        head_commit_sha="3" * 40,
        base_commit_sha="4" * 40,
        status="completed",
        verdict="approved",
        model_name="claude-sonnet-4",
        execution_duration_ms=3000,
        created_at=now,
    )
    db_session.add_all([r1, r2])
    await db_session.flush()

    # Findings: 1 accepted, 1 dismissed -> acceptance_rate = 0.5
    f1 = PRReviewFindingModel(
        review_id=r1.id,
        file_path="a.py",
        line_number=1,
        severity="major",
        category="bug",
        title="F1",
        message="M1",
        feedback_state="accepted",
        status="resolved",
        created_at=now,
    )
    f2 = PRReviewFindingModel(
        review_id=r1.id,
        file_path="b.py",
        line_number=2,
        severity="minor",
        category="style",
        title="F2",
        message="M2",
        feedback_state="dismissed",
        status="dismissed",
        created_at=now,
    )
    db_session.add_all([f1, f2])

    # Autonomous task + completed run (30s - 10s paused = 20000ms active)
    task = TaskModel(
        org_id=org.id,
        repo_id=repo.id,
        title="Fix bug",
        description="desc",
        status="completed",
        trigger_type="github_issue",
    )
    db_session.add(task)
    await db_session.flush()

    run = TaskRunModel(
        org_id=org.id,
        task_id=task.id,
        run_number=1,
        status="completed",
        paused_seconds=10,
        started_at=now - timedelta(seconds=30),
        completed_at=now,
    )
    db_session.add(run)
    await db_session.flush()

    # Usage events: 45 cents pr_review + 80 cents forge + 20 cents reviewer
    db_session.add_all(
        [
            UsageEventModel(
                org_id=org.id,
                pr_review_id=r1.id,
                provider="anthropic",
                model="claude-sonnet-4",
                operation_type="pr_review",
                prompt_tokens=100,
                completion_tokens=50,
                estimated_cost_cents=45,
                created_at=now,
            ),
            UsageEventModel(
                org_id=org.id,
                task_id=task.id,
                task_run_id=run.id,
                provider="anthropic",
                model="claude-sonnet-4",
                operation_type="forge",
                prompt_tokens=200,
                completion_tokens=100,
                estimated_cost_cents=80,
                created_at=now,
            ),
            UsageEventModel(
                org_id=org.id,
                task_id=task.id,
                task_run_id=run.id,
                provider="anthropic",
                model="claude-sonnet-4",
                operation_type="reviewer",
                prompt_tokens=100,
                completion_tokens=50,
                estimated_cost_cents=20,
                created_at=now,
            ),
        ]
    )
    await db_session.commit()

    member_hdrs = _auth_headers(org.clerk_org_id, org_role="org:member")

    # Invalid days -> 422
    bad_days = await client.get(
        "/api/v1/analytics/overview?days=14", headers=member_hdrs
    )
    assert bad_days.status_code == 422

    # Foreign repo_id -> 404
    foreign_repo = await client.get(
        f"/api/v1/analytics/overview?days=30&repo_id={other_repo.id}",
        headers=member_hdrs,
    )
    assert foreign_repo.status_code == 404

    # Valid overview
    res = await client.get(
        f"/api/v1/analytics/overview?days=7&repo_id={repo.id}",
        headers=member_hdrs,
    )
    assert res.status_code == 200
    payload = res.json()
    assert payload["days"] == 7
    assert len(payload["daily_series"]) == 7

    kpis = payload["kpis"]
    assert kpis["total_reviews"] == 2
    assert kpis["turnaround_p50_ms"] == pytest.approx(2000.0, abs=1.0)
    assert kpis["turnaround_p95_ms"] == pytest.approx(2900.0, abs=50.0)
    assert kpis["task_turnaround_p50_ms"] == pytest.approx(20000.0, abs=50.0)
    assert kpis["acceptance_rate"] == pytest.approx(0.5)
    assert kpis["total_cost_cents"] == 145
    assert kpis["pr_review_cost_cents"] == 45
    assert kpis["autonomous_cost_cents"] == 100

    today_point = payload["daily_series"][-1]
    assert today_point["pr_review_cost_cents"] == 45
    assert today_point["autonomous_cost_cents"] == 100
    assert today_point["total_cost_cents"] == 145


def test_redaction_globstar_selection_and_pattern_key_edges() -> None:
    """Verify redaction, globstar matching, rule sorting, and pattern keys (AC-1..4)."""
    # Redaction covers PEM keys, Bearer tokens, github_pat, AKIA, and key=value
    secret_blob = (
        "-----BEGIN RSA PRIVATE KEY-----\n"
        "MIIEowIBAAKCAQEA\n"
        "-----END RSA PRIVATE KEY-----\n"
        "Authorization: Bearer eyJhbGciOiJIUzI1NiJ9.payload.sig\n"
        "PAT=github_pat_1234567890abcdefghij\n"
        "AWS=AKIAIOSFODNN7EXAMPLE\n"
        "password='super_secret_password'\n"
        "api_key=my_secret_value_1234"
    )
    scrubbed = redact_credentials(secret_blob)
    assert "MIIEowIBAAKCAQEA" not in scrubbed
    assert "eyJhbGciOiJIUzI1NiJ9" not in scrubbed
    assert "github_pat_1234567890abcdefghij" not in scrubbed
    assert "AKIAIOSFODNN7EXAMPLE" not in scrubbed
    assert "super_secret_password" not in scrubbed
    assert "my_secret_value_1234" not in scrubbed
    assert scrubbed.count("[REDACTED]") >= 6
    assert redact_credentials("") == ""

    # Globstar edge cases: ?, [!x], leading ./, and empty file_paths fallback
    assert ReviewContextService.matches_path_glob("./src/a.py", "src/?.py")
    assert ReviewContextService.matches_path_glob("src/b.py", "src/[!a].py")
    assert not ReviewContextService.matches_path_glob("src/a.py", "src/[!a].py")

    org_id = uuid.uuid4()
    repo_id = uuid.uuid4()
    t_early = datetime(2026, 11, 1, tzinfo=UTC)
    t_late = datetime(2026, 11, 2, tzinfo=UTC)

    def _rule(
        *,
        scope: str,
        severity: str,
        created_at: datetime,
        is_enabled: bool = True,
        globs: list[str] | None = None,
    ) -> EffectiveReviewRule:
        return EffectiveReviewRule(
            id=uuid.uuid4(),
            org_id=org_id,
            repo_id=repo_id if scope == "repo" else None,
            scope=scope,
            title=f"{scope}-{severity}",
            instruction="Check",
            base_severity=severity,
            severity=severity,
            category="bug",
            path_globs=globs or ["**/*"],
            base_is_enabled=is_enabled,
            is_enabled=is_enabled,
            has_override=False,
            override_is_enabled=None,
            override_severity=None,
            created_by="admin",
            created_at=created_at,
        )

    org_crit = _rule(scope="org", severity="critical", created_at=t_early)
    repo_crit = _rule(scope="repo", severity="critical", created_at=t_late)
    org_major_late = _rule(scope="org", severity="major", created_at=t_late)
    org_major_early = _rule(scope="org", severity="major", created_at=t_early)
    disabled_rule = _rule(
        scope="repo", severity="critical", created_at=t_early, is_enabled=False
    )
    docs_only = _rule(
        scope="repo", severity="critical", created_at=t_early, globs=["docs/*.md"]
    )

    selected = ReviewContextService.select_matching_rules(
        [
            org_crit,
            repo_crit,
            org_major_late,
            org_major_early,
            disabled_rule,
            docs_only,
        ],
        ["src/app.py"],
    )
    assert [r.id for r in selected] == [
        repo_crit.id,
        org_crit.id,
        org_major_early.id,
        org_major_late.id,
    ]
    # Empty modified_files evaluates against README.md
    assert ReviewContextService.rule_matches_files(org_crit, [])
    assert not ReviewContextService.rule_matches_files(docs_only, [])

    # Pattern keys for rule-linked vs root vs nested paths
    rid = uuid.uuid4()
    assert (
        ReviewContextService.compute_pattern_key(rid, "style", "src/a.py")
        == f"rule:{rid}"
    )
    assert (
        ReviewContextService.compute_pattern_key(None, "style", "README.md")
        == "style:__root__"
    )
    assert (
        ReviewContextService.compute_pattern_key(None, "security", "./apps/agent/x.py")
        == "security:apps"
    )


@pytest.mark.asyncio
async def test_org_and_repo_rule_updates_deletes_and_cap_edge_cases(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    """Verify rule PATCH/DELETE, cross-scope 422, cap re-enable, and 403 (AC-1)."""
    org, repo = await _seed_org_and_repo(db_session)
    await db_session.commit()

    admin_hdrs = _auth_headers(org.clerk_org_id, org_role="org:admin", user_id="u_adm")
    member_hdrs = _auth_headers(
        org.clerk_org_id, org_role="org:member", user_id="u_mem"
    )

    # Token without org claim -> 403 org_missing
    no_org_token = make_clerk_jwt(_PRIV_PEM, user_id="u_noorg", clerk_org_id=None)
    missing_org_res = await client.get(
        "/api/v1/organizations/review-rules",
        headers={"Authorization": f"Bearer {no_org_token}"},
    )
    assert missing_org_res.status_code == 403

    # Create disabled org rule and enabled repo rule
    disabled_org = await client.post(
        "/api/v1/organizations/review-rules",
        headers=admin_hdrs,
        json={
            "title": "Disabled org rule",
            "instruction": "Initially off",
            "severity": "major",
            "category": "security",
            "is_enabled": False,
        },
    )
    assert disabled_org.status_code == 201
    disabled_org_id = disabled_org.json()["id"]

    repo_rule = await client.post(
        f"/api/v1/repositories/{repo.id}/review-rules",
        headers=admin_hdrs,
        json={
            "title": "Repo rule 1",
            "instruction": "Check repo",
            "severity": "minor",
            "category": "style",
        },
    )
    assert repo_rule.status_code == 201
    repo_rule_id = repo_rule.json()["id"]

    # Member cannot PATCH/DELETE org or repo rules, nor PUT override
    assert (
        await client.patch(
            f"/api/v1/organizations/review-rules/{disabled_org_id}",
            headers=member_hdrs,
            json={"title": "Blocked"},
        )
    ).status_code == 403
    assert (
        await client.delete(
            f"/api/v1/organizations/review-rules/{disabled_org_id}",
            headers=member_hdrs,
        )
    ).status_code == 403
    assert (
        await client.put(
            f"/api/v1/repositories/{repo.id}/review-rules/{disabled_org_id}/override",
            headers=member_hdrs,
            json={"is_enabled": True},
        )
    ).status_code == 403

    # Cross-scope guards: repo rule on org endpoint and org rule on repo endpoint -> 422
    assert (
        await client.patch(
            f"/api/v1/organizations/review-rules/{repo_rule_id}",
            headers=admin_hdrs,
            json={"title": "Cross scope"},
        )
    ).status_code == 422
    assert (
        await client.patch(
            f"/api/v1/repositories/{repo.id}/review-rules/{disabled_org_id}",
            headers=admin_hdrs,
            json={"title": "Cross scope"},
        )
    ).status_code == 422
    assert (
        await client.put(
            f"/api/v1/repositories/{repo.id}/review-rules/{repo_rule_id}/override",
            headers=admin_hdrs,
            json={"is_enabled": False},
        )
    ).status_code == 422

    # Fill remaining 24 active slots on repo (1 + 24 = 25)
    db_session.add_all(
        [
            ReviewRuleModel(
                org_id=org.id,
                repo_id=repo.id,
                title=f"Filler {i}",
                instruction=f"Check {i}",
                severity="info",
                category="style",
                path_globs=["**/*"],
                is_enabled=True,
                created_by="u_adm",
            )
            for i in range(24)
        ]
    )
    await db_session.commit()

    # Re-enabling disabled org rule via PATCH/PUT fails with 422 at 25 rules
    assert (
        await client.patch(
            f"/api/v1/organizations/review-rules/{disabled_org_id}",
            headers=admin_hdrs,
            json={"is_enabled": True},
        )
    ).status_code == 422
    assert (
        await client.put(
            f"/api/v1/repositories/{repo.id}/review-rules/{disabled_org_id}/override",
            headers=admin_hdrs,
            json={"is_enabled": True},
        )
    ).status_code == 422

    # PATCH repo rule and org rule metadata, paginate org rules, DELETE org rule
    upd_repo = await client.patch(
        f"/api/v1/repositories/{repo.id}/review-rules/{repo_rule_id}",
        headers=admin_hdrs,
        json={"title": "Repo rule updated", "severity": "major"},
    )
    assert upd_repo.status_code == 200
    assert upd_repo.json()["title"] == "Repo rule updated"

    upd_org = await client.patch(
        f"/api/v1/organizations/review-rules/{disabled_org_id}",
        headers=admin_hdrs,
        json={"title": "Org rule updated"},
    )
    assert upd_org.status_code == 200
    assert upd_org.json()["title"] == "Org rule updated"

    list_org = await client.get(
        "/api/v1/organizations/review-rules?limit=1&offset=0", headers=member_hdrs
    )
    assert list_org.status_code == 200
    assert list_org.json()["total"] == 1

    del_org = await client.delete(
        f"/api/v1/organizations/review-rules/{disabled_org_id}", headers=admin_hdrs
    )
    assert del_org.status_code == 204
    assert (
        await client.get("/api/v1/organizations/review-rules", headers=member_hdrs)
    ).json()["total"] == 0


@pytest.mark.asyncio
async def test_example_prs_conflicts_validation_delete_and_diff_truncation(
    client: AsyncClient, db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Verify example PR 409, 422 parsing, DELETE cap release, and diff split (AC-2)."""
    org, repo = await _seed_org_and_repo(db_session)
    await db_session.commit()
    admin_hdrs = _auth_headers(org.clerk_org_id, org_role="org:admin")
    member_hdrs = _auth_headers(org.clerk_org_id, org_role="org:member")

    # Unit checks for parse_example_pr_input and multi-file header-preserving truncation
    with pytest.raises(ValidationError):
        parse_example_pr_input(repo.full_name, None, "https://example.com/not-github")
    with pytest.raises(ValidationError):
        parse_example_pr_input(
            repo.full_name, 10, f"https://github.com/{repo.full_name}/pull/11"
        )
    assert (
        parse_example_pr_input(
            repo.full_name, 10, f"https://github.com/{repo.full_name}/pull/10"
        )
        == 10
    )

    assert ReviewContextService.build_diff_summary_and_files("") == ([], "", 0)

    multi_diff = (
        "diff --git a/a.py b/a.py\n--- a/a.py\n+++ b/a.py\n@@ -1 +1,20 @@\n"
        + "\n".join(f"+a_line_{i} = 'val_{i}'" for i in range(60))
        + "\ndiff --git a/b.py b/b.py\n--- a/b.py\n+++ b/b.py\n@@ -1 +1,20 @@\n"
        + "\n".join(f"+b_line_{i} = 'val_{i}'" for i in range(60))
    )
    files, summary, tok_cnt = ReviewContextService.build_diff_summary_and_files(
        multi_diff, max_tokens=200
    )
    assert files == ["a.py", "b.py"]
    assert tok_cnt <= 200
    assert "+++ b/a.py" in summary

    # rank_examples orders by modified file overlap DESC then updated_at DESC
    t1 = datetime(2026, 11, 1, tzinfo=UTC)
    t2 = datetime(2026, 11, 2, tzinfo=UTC)
    ex_low = ReviewExample(
        id=uuid.uuid4(),
        org_id=org.id,
        repo_id=repo.id,
        pr_number=1,
        pr_url="https://github.com/a/b/pull/1",
        pr_title="Low overlap",
        classification="good",
        guidance_note="note",
        modified_files=["unrelated.py"],
        updated_at=t2,
    )
    ex_high = ReviewExample(
        id=uuid.uuid4(),
        org_id=org.id,
        repo_id=repo.id,
        pr_number=2,
        pr_url="https://github.com/a/b/pull/2",
        pr_title="High overlap",
        classification="good",
        guidance_note="note",
        modified_files=["src/main.py", "src/util.py"],
        updated_at=t1,
    )
    ranked = ReviewContextService.rank_examples(
        [ex_low, ex_high], ["src/main.py", "src/util.py"]
    )
    assert [e.pr_number for e in ranked] == [2, 1]

    def handler(request: httpx.Request) -> httpx.Response:
        if "diff" in request.headers.get("Accept", ""):
            return httpx.Response(
                200,
                text=(
                    "diff --git a/x.py b/x.py\n"
                    "--- a/x.py\n+++ b/x.py\n@@ -1 +1 @@\n+x=1\n"
                ),
            )
        pr_num = int(request.url.path.rsplit("/", 1)[-1])
        return httpx.Response(
            200,
            json={
                "number": pr_num,
                "title": f"PR {pr_num}",
                "html_url": f"https://github.com/{repo.full_name}/pull/{pr_num}",
                "base": {"repo": {"full_name": repo.full_name}},
            },
        )

    transport = httpx.MockTransport(handler)
    orig_init = GitHubService.__init__

    def _patched_init(self, app_id=None, private_key=None, **kwargs):
        orig_init(
            self,
            app_id=app_id,
            private_key=private_key,
            http_client=httpx.AsyncClient(transport=transport),
        )

    monkeypatch.setattr(GitHubService, "__init__", _patched_init)

    # Member cannot attach example (403)
    assert (
        await client.post(
            f"/api/v1/repositories/{repo.id}/review-examples",
            headers=member_hdrs,
            json={
                "pr_number": 50,
                "classification": "good",
                "guidance_note": "No perms",
            },
        )
    ).status_code == 403

    created = await client.post(
        f"/api/v1/repositories/{repo.id}/review-examples",
        headers=admin_hdrs,
        json={
            "pr_number": 50,
            "classification": "good",
            "guidance_note": "Clean pattern",
        },
    )
    assert created.status_code == 201
    ex_id = created.json()["id"]

    # Duplicate PR -> 409 Conflict
    dup = await client.post(
        f"/api/v1/repositories/{repo.id}/review-examples",
        headers=admin_hdrs,
        json={
            "pr_number": 50,
            "classification": "bad",
            "guidance_note": "Duplicate",
        },
    )
    assert dup.status_code == 409

    # Member can list examples (200), cannot refresh or delete (403)
    list_res = await client.get(
        f"/api/v1/repositories/{repo.id}/review-examples", headers=member_hdrs
    )
    assert list_res.status_code == 200
    assert len(list_res.json()["items"]) == 1
    assert (
        await client.post(
            f"/api/v1/repositories/{repo.id}/review-examples/{ex_id}/refresh",
            headers=member_hdrs,
        )
    ).status_code == 403
    assert (
        await client.delete(
            f"/api/v1/repositories/{repo.id}/review-examples/{ex_id}",
            headers=member_hdrs,
        )
    ).status_code == 403

    # Admin deletes example -> 204 and audit log recorded
    del_res = await client.delete(
        f"/api/v1/repositories/{repo.id}/review-examples/{ex_id}",
        headers=admin_hdrs,
    )
    assert del_res.status_code == 204
    audits = (
        (
            await db_session.execute(
                select(AuditLogModel.action).where(AuditLogModel.org_id == org.id)
            )
        )
        .scalars()
        .all()
    )
    assert "review_example.deleted" in audits


@pytest.mark.asyncio
async def test_feedback_toggling_bare_dismissal_and_admin_pref_validation(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    """Verify feedback toggling, bare dismissal, pref filter, and RBAC (AC-3, AC-4)."""
    org, repo = await _seed_org_and_repo(db_session)
    other_org, other_repo = await _seed_org_and_repo(db_session)

    review = PullRequestReviewModel(
        org_id=org.id,
        repo_id=repo.id,
        pr_number=88,
        pr_title="Refactor parser",
        pr_author="alice",
        head_commit_sha="c" * 40,
        base_commit_sha="d" * 40,
        status="completed",
        verdict="comment",
        model_name="claude-sonnet-4",
    )
    db_session.add(review)
    await db_session.flush()

    finding = PRReviewFindingModel(
        review_id=review.id,
        file_path="README.md",
        line_number=3,
        side="RIGHT",
        severity="minor",
        category="style",
        title="Heading style",
        message="Use sentence case",
    )
    db_session.add(finding)
    await db_session.commit()

    member_hdrs = _auth_headers(org.clerk_org_id, org_role="org:member")
    admin_hdrs = _auth_headers(org.clerk_org_id, org_role="org:admin")

    # 1. Bare dismissal (no remember, no reason) -> not injectable at streak 1
    r_bare = await client.post(
        f"/api/v1/reviews/findings/{finding.id}/feedback",
        headers=member_hdrs,
        json={"feedback_type": "dismissed", "remember_preference": False},
    )
    assert r_bare.status_code == 200
    pref_json = r_bare.json()["learned_preference"]
    assert pref_json["pattern_key"] == "style:__root__"
    assert pref_json["status"] == "active"
    assert pref_json["consecutive_dismissals"] == 1

    fb_repo = SqlAlchemyReviewFeedbackRepository(db_session)
    pairs, _ = await fb_repo.list_preferences_for_repo(org.id, repo.id)
    injectable, _, _ = ReviewContextService.select_matching_preferences(
        pairs, set(), ["README.md"]
    )
    assert injectable == []

    # 2. Toggle same finding to accepted -> resets consecutive_dismissals = 0
    r_acc = await client.post(
        f"/api/v1/reviews/findings/{finding.id}/feedback",
        headers=member_hdrs,
        json={"feedback_type": "accepted"},
    )
    assert r_acc.status_code == 200
    assert r_acc.json()["finding"]["feedback_state"] == "accepted"
    assert r_acc.json()["finding"]["status"] == "resolved"
    assert r_acc.json()["learned_preference"]["accept_count"] == 1
    assert r_acc.json()["learned_preference"]["consecutive_dismissals"] == 0

    # 3. Admin preference PATCH: 403 member, 422 empty instruction, transitions
    pref_id = pref_json["id"]
    assert (
        await client.patch(
            f"/api/v1/repositories/{repo.id}/review-preferences/{pref_id}",
            headers=member_hdrs,
            json={"status": "suppressed"},
        )
    ).status_code == 403
    assert (
        await client.patch(
            f"/api/v1/repositories/{repo.id}/review-preferences/{pref_id}",
            headers=admin_hdrs,
            json={"status": "active", "instruction": "   "},
        )
    ).status_code == 422

    sup_res = await client.patch(
        f"/api/v1/repositories/{repo.id}/review-preferences/{pref_id}",
        headers=admin_hdrs,
        json={"status": "suppressed", "instruction": "Always ignore heading case"},
    )
    assert sup_res.status_code == 200
    assert sup_res.json()["consecutive_dismissals"] >= 3

    act_res = await client.patch(
        f"/api/v1/repositories/{repo.id}/review-preferences/{pref_id}",
        headers=admin_hdrs,
        json={"status": "active"},
    )
    assert act_res.status_code == 200
    assert act_res.json()["consecutive_dismissals"] == 0

    # List preferences filter & invalid status 422
    assert (
        await client.get(
            f"/api/v1/repositories/{repo.id}/review-preferences?status=bogus",
            headers=member_hdrs,
        )
    ).status_code == 422
    active_list = await client.get(
        f"/api/v1/repositories/{repo.id}/review-preferences?status=active",
        headers=member_hdrs,
    )
    assert active_list.status_code == 200
    assert active_list.json()["total"] == 1

    # Reviews endpoints: foreign repo -> 404, detail returns feedback_state
    assert (
        await client.get(
            f"/api/v1/reviews?repo_id={other_repo.id}", headers=member_hdrs
        )
    ).status_code == 404
    detail_res = await client.get(f"/api/v1/reviews/{review.id}", headers=member_hdrs)
    assert detail_res.status_code == 200
    assert detail_res.json()["findings"][0]["feedback_state"] == "accepted"

    # Cross-org finding feedback -> 404
    other_hdrs = _auth_headers(other_org.clerk_org_id, org_role="org:admin")
    assert (
        await client.post(
            f"/api/v1/reviews/findings/{finding.id}/feedback",
            headers=other_hdrs,
            json={"feedback_type": "dismissed"},
        )
    ).status_code == 404


@pytest.mark.asyncio
async def test_github_feedback_webhooks_http_and_publisher_resilience(
    client: AsyncClient, db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Verify HTTP webhook guards, accept replies, and publisher resilience (AC-3)."""
    org, repo = await _seed_org_and_repo(db_session)
    review = PullRequestReviewModel(
        org_id=org.id,
        repo_id=repo.id,
        pr_number=91,
        pr_title="Webhook PR",
        pr_author="dev",
        head_commit_sha="e" * 40,
        base_commit_sha="f" * 40,
        status="completed",
        verdict="comment",
        model_name="claude-sonnet-4",
    )
    db_session.add(review)
    await db_session.flush()

    run_tag = uuid.uuid4().hex[:8]
    comment_id = int(uuid.uuid4().int % 1_000_000_000) + 1000
    finding = PRReviewFindingModel(
        review_id=review.id,
        file_path="src/service.py",
        line_number=5,
        side="RIGHT",
        severity="major",
        category="bug",
        title="Null check",
        message="Check None",
        github_comment_id=comment_id,
    )
    db_session.add(finding)
    await db_session.commit()

    monkeypatch.setattr(settings, "GITHUB_WEBHOOK_SECRET", "whsec_test_9")

    # Bad signature on HTTP endpoint -> 401
    bad_payload = json.dumps({"action": "created"}).encode()
    bad_sig_res = await client.post(
        "/api/v1/webhooks/github",
        content=bad_payload,
        headers={
            "X-GitHub-Event": "pull_request_review_comment",
            "X-Hub-Signature-256": "sha256=deadbeef",
            "X-GitHub-Delivery": f"deliv-http-bad-{run_tag}",
        },
    )
    assert bad_sig_res.status_code == 401

    # Missing X-GitHub-Delivery -> ignored
    no_deliv = json.dumps(
        {
            "action": "created",
            "repository": {"id": repo.github_repo_id},
            "sender": {"login": "collab", "type": "User"},
            "comment": {
                "id": 1001,
                "in_reply_to_id": comment_id,
                "author_association": "COLLABORATOR",
                "body": "good catch",
            },
        }
    ).encode()
    res_no_deliv = await client.post(
        "/api/v1/webhooks/github",
        content=no_deliv,
        headers={
            "X-GitHub-Event": "pull_request_review_comment",
            "X-Hub-Signature-256": _sign_gh(no_deliv, "whsec_test_9"),
        },
    )
    assert res_no_deliv.status_code == 200
    assert res_no_deliv.json()["reason"] == "missing_delivery_id"

    # Bot sender -> ignored
    bot_payload = json.dumps(
        {
            "action": "created",
            "repository": {"id": repo.github_repo_id},
            "sender": {"login": "helper[bot]", "type": "Bot"},
            "comment": {
                "id": 1002,
                "in_reply_to_id": comment_id,
                "author_association": "COLLABORATOR",
                "body": "good catch",
            },
        }
    ).encode()
    res_bot = await client.post(
        "/api/v1/webhooks/github",
        content=bot_payload,
        headers={
            "X-GitHub-Event": "pull_request_review_comment",
            "X-Hub-Signature-256": _sign_gh(bot_payload, "whsec_test_9"),
            "X-GitHub-Delivery": f"deliv-bot-{run_tag}",
        },
    )
    assert res_bot.json()["reason"] == "bot_sender_excluded"

    # Top-level comment without in_reply_to_id -> ignored
    top_payload = json.dumps(
        {
            "action": "created",
            "repository": {"id": repo.github_repo_id},
            "sender": {"login": "collab", "type": "User"},
            "comment": {
                "id": 1003,
                "author_association": "COLLABORATOR",
                "body": "good catch",
            },
        }
    ).encode()
    res_top = await client.post(
        "/api/v1/webhooks/github",
        content=top_payload,
        headers={
            "X-GitHub-Event": "pull_request_review_comment",
            "X-Hub-Signature-256": _sign_gh(top_payload, "whsec_test_9"),
            "X-GitHub-Delivery": f"deliv-top-{run_tag}",
        },
    )
    assert res_top.json()["reason"] == "not_a_reply_comment"

    # Authorized COLLABORATOR reply with "good catch" -> processed & accepted
    accept_payload = json.dumps(
        {
            "action": "created",
            "repository": {"id": repo.github_repo_id},
            "sender": {"login": "collab", "type": "User"},
            "comment": {
                "id": 1004,
                "in_reply_to_id": comment_id,
                "author_association": "COLLABORATOR",
                "body": "Good catch, fixed in next commit!",
            },
        }
    ).encode()
    res_accept = await client.post(
        "/api/v1/webhooks/github",
        content=accept_payload,
        headers={
            "X-GitHub-Event": "pull_request_review_comment",
            "X-Hub-Signature-256": _sign_gh(accept_payload, "whsec_test_9"),
            "X-GitHub-Delivery": f"deliv-accept-http-{run_tag}",
        },
    )
    assert res_accept.status_code == 200
    assert res_accept.json()["status"] == "processed"
    assert res_accept.json()["reason"] == "comment_reply_accepted"

    await db_session.refresh(finding)
    assert finding.feedback_state == "accepted"

    # Publisher resilience: 422 skips backfill; comment API error is non-fatal
    diff_text = (
        "diff --git a/src/service.py b/src/service.py\n"
        "--- a/src/service.py\n+++ b/src/service.py\n@@ -1 +1,2 @@\n+x = 1\n"
    )
    sample_finding = [
        {
            "id": finding.id,
            "file_path": "src/service.py",
            "line_number": 1,
            "severity": "major",
            "category": "bug",
            "title": "Null check",
            "message": "Check None",
        }
    ]

    mock_gh_drift = AsyncMock()
    mock_gh_drift.submit_review = AsyncMock(
        side_effect=[RuntimeError("422 Unprocessable Entity"), {"id": 701}]
    )
    mock_gh_drift.list_review_comments = AsyncMock()
    pub_drift = await GitHubReviewPublisher(mock_gh_drift).publish(
        repo_full_name=repo.full_name,
        pr_number=91,
        head_commit_sha="e" * 40,
        verdict="comment",
        summary="Sum",
        findings=sample_finding,
        diff_text=diff_text,
        token="tok",
    )
    assert pub_drift.fallback_applied is True
    assert pub_drift.comment_id_mappings == []
    mock_gh_drift.list_review_comments.assert_not_awaited()

    mock_gh_err = AsyncMock()
    mock_gh_err.submit_review = AsyncMock(return_value={"id": 702})
    mock_gh_err.list_review_comments = AsyncMock(side_effect=RuntimeError("GH 500"))
    pub_err = await GitHubReviewPublisher(mock_gh_err).publish(
        repo_full_name=repo.full_name,
        pr_number=91,
        head_commit_sha="e" * 40,
        verdict="comment",
        summary="Sum",
        findings=sample_finding,
        diff_text=diff_text,
        token="tok",
    )
    assert pub_err.github_review_id == 702
    assert pub_err.fallback_applied is False
    assert pub_err.comment_id_mappings == []


@pytest.mark.asyncio
async def test_budget_pruning_order_run_pr_review_e2e_and_task_graph_reviewer(
    db_session: AsyncSession, tmp_path
) -> None:
    """Verify Tier 1 pruning, RunPRReviewUseCase, and task_graph reviewer (AC-4..5)."""
    # 1. Verify ContextBudgetAllocator pruning order: examples -> prefs -> rules
    org_id = uuid.uuid4()
    repo_id = uuid.uuid4()
    rules = [
        EffectiveReviewRule(
            id=uuid.uuid4(),
            org_id=org_id,
            repo_id=repo_id,
            scope="repo",
            title=f"Rule {i}",
            instruction=("check invariant " * 30).strip(),
            base_severity="critical" if i == 0 else "minor",
            severity="critical" if i == 0 else "minor",
            category="security",
            path_globs=["**/*"],
            base_is_enabled=True,
            is_enabled=True,
            has_override=False,
            override_is_enabled=None,
            override_severity=None,
            created_by="admin",
            created_at=datetime(2026, 11, 1, tzinfo=UTC) + timedelta(minutes=i),
        )
        for i in range(15)
    ]
    prefs = [
        (
            ReviewLearnedPreference(
                id=uuid.uuid4(),
                org_id=org_id,
                repo_id=repo_id,
                rule_id=None,
                source_feedback_id=None,
                pattern_key="style:src",
                instruction=("prefer compact layout " * 40).strip(),
                status="dampened",
            ),
            None,
        )
        for _ in range(10)
    ]
    examples = [
        ReviewExample(
            id=uuid.uuid4(),
            org_id=org_id,
            repo_id=repo_id,
            pr_number=200 + i,
            pr_url=f"https://github.com/acme/repo/pull/{200 + i}",
            pr_title=f"Example {i}",
            classification="good",
            guidance_note=("guidance note " * 40).strip(),
            modified_files=["src/main.py"],
            cached_diff_summary=("+code = 1\n" * 80).strip(),
            cached_token_count=400,
        )
        for i in range(5)
    ]
    diff_text = (
        "diff --git a/src/main.py b/src/main.py\n"
        "--- a/src/main.py\n+++ b/src/main.py\n@@ -1 +1,2 @@\n+x = 1\n"
    )
    assembled = ContextBudgetAllocator.assemble_context(
        diff_text=diff_text,
        symbol_graph=SymbolCallGraph(),
        repo_dir=tmp_path,
        custom_rules=rules,
        learned_preferences=prefs,
        example_prs=examples,
    )
    assert ContextBudgetAllocator.estimate_tokens(assembled.tier1_content) <= 32000
    assert str(rules[0].id) in assembled.included_rule_ids
    assert "<custom_rules>" in assembled.tier1_content

    # 2. End-to-end RunPRReviewUseCase with seeded rules, prefs, and example PRs
    org, repo = await _seed_org_and_repo(db_session)
    org_rule = ReviewRuleModel(
        org_id=org.id,
        repo_id=None,
        title="SQL Param",
        instruction="Use bind params <safe>",
        severity="critical",
        category="security",
        path_globs=["**/*"],
        is_enabled=True,
        created_by="admin",
    )
    suppressed_rule = ReviewRuleModel(
        org_id=org.id,
        repo_id=repo.id,
        title="Spacing nit",
        instruction="Check spaces",
        severity="minor",
        category="style",
        path_globs=["**/*"],
        is_enabled=True,
        created_by="admin",
    )
    db_session.add_all([org_rule, suppressed_rule])
    await db_session.flush()

    db_session.add(
        ReviewRuleOverrideModel(
            org_id=org.id,
            repo_id=repo.id,
            rule_id=org_rule.id,
            is_enabled=True,
            severity_override="major",
            updated_by="admin",
        )
    )
    db_session.add(
        ReviewExampleModel(
            org_id=org.id,
            repo_id=repo.id,
            pr_number=15,
            pr_url=f"https://github.com/{repo.full_name}/pull/15",
            pr_title="Good auth PR",
            classification="good",
            guidance_note="Validate inputs early",
            modified_files=["src/main.py"],
            cached_diff_summary="+++ b/src/main.py\n+validate()",
            cached_token_count=12,
            created_by="admin",
        )
    )
    db_session.add(
        ReviewLearnedPreferenceModel(
            org_id=org.id,
            repo_id=repo.id,
            rule_id=org_rule.id,
            pattern_key=f"rule:{org_rule.id}",
            instruction="Downgrade SQL note to advisory",
            dismiss_count=2,
            consecutive_dismissals=2,
            status="dampened",
        )
    )
    db_session.add(
        ReviewLearnedPreferenceModel(
            org_id=org.id,
            repo_id=repo.id,
            rule_id=suppressed_rule.id,
            pattern_key=f"rule:{suppressed_rule.id}",
            instruction="Ignore spacing nit",
            dismiss_count=3,
            consecutive_dismissals=3,
            status="suppressed",
        )
    )

    pr_review_repo = SqlAlchemyPRReviewRepository(db_session)
    created_review = await pr_review_repo.create_review(
        org_id=org.id,
        repo_id=repo.id,
        pr_number=303,
        pr_title="Add query",
        pr_author="alice",
        head_commit_sha="1" * 40,
        base_commit_sha="2" * 40,
        model_name="claude-sonnet-4",
    )
    await db_session.commit()

    captured_prompt: dict[str, str] = {}
    orig_analyze = CodeReviewAnalyzerNode.analyze

    class CapturingAnalyzer(CodeReviewAnalyzerNode):
        async def analyze(
            self,
            tier1_diff_context: str,
            tier2_symbol_context: str,
            omitted_files: list[str] | None = None,
            allow_approval: bool = False,
            simulated_findings: list[dict] | None = None,
            *,
            active_rule_ids: set[uuid.UUID] | None = None,
            dampened_patterns: set[str] | None = None,
            suppressed_patterns: set[str] | None = None,
            min_severity: str = "info",
            max_comments: int = 25,
        ):
            captured_prompt["tier1"] = tier1_diff_context
            return await orig_analyze(
                self,
                tier1_diff_context,
                tier2_symbol_context,
                omitted_files=omitted_files,
                allow_approval=allow_approval,
                simulated_findings=simulated_findings,
                active_rule_ids=active_rule_ids,
                dampened_patterns=dampened_patterns,
                suppressed_patterns=suppressed_patterns,
                min_severity=min_severity,
                max_comments=max_comments,
            )

    gh_mock = AsyncMock()
    gh_mock.get_installation_token = AsyncMock(return_value="tok")
    gh_mock.get_pull_request_diff = AsyncMock(return_value=diff_text)
    gh_mock.submit_review = AsyncMock(return_value={"id": 8801})
    gh_mock.list_review_comments = AsyncMock(
        return_value=[
            {
                "id": 99123,
                "path": "src/main.py",
                "line": 1,
                "body": "**[INFO] SQL Param Hit**\n\n[Advisory] Check query",
            }
        ]
    )

    uc = RunPRReviewUseCase(
        pr_review_repo=pr_review_repo,
        repository_repo=SqlAlchemyRepositoryRepository(db_session),
        github_gateway=gh_mock,
        reviewer_node=CapturingAnalyzer(),
    )
    hallucinated_rule_id = uuid.uuid4()
    finished = await uc.execute(
        org_id=org.id,
        review_id=created_review.id,
        repo_dir=str(tmp_path),
        simulated_findings=[
            {
                "file_path": "src/main.py",
                "line_number": 1,
                "severity": "major",
                "category": "security",
                "title": "SQL Param Hit",
                "message": "Check query",
                "rule_id": org_rule.id,
            },
            {
                "file_path": "src/main.py",
                "line_number": 1,
                "severity": "minor",
                "category": "style",
                "title": "Suppressed nit",
                "message": "Should be filtered",
                "rule_id": suppressed_rule.id,
            },
            {
                "file_path": "src/main.py",
                "line_number": 2,
                "severity": "minor",
                "category": "architecture",
                "title": "Unknown rule finding",
                "message": "Hallucinated id stripped",
                "rule_id": hallucinated_rule_id,
            },
        ],
    )
    assert finished.status == "completed"
    assert "&lt;safe&gt;" in captured_prompt["tier1"]
    assert "<custom_rules>" in captured_prompt["tier1"]
    assert "<team_preferences>" in captured_prompt["tier1"]
    assert "<example_prs>" in captured_prompt["tier1"]

    persisted_findings, _ = await pr_review_repo.list_findings(created_review.id)
    assert len(persisted_findings) == 2
    by_title = {f.title: f for f in persisted_findings}
    assert by_title["SQL Param Hit"].rule_id == org_rule.id
    assert by_title["SQL Param Hit"].severity == "info"
    assert by_title["SQL Param Hit"].github_comment_id == 99123
    assert by_title["Unknown rule finding"].rule_id is None

    # 3. Verify task_graph reviewer_node injects XML custom_review_prompt
    captured_graph_ctx: dict[str, object] = {}

    class StubForge(ForgeAgent):
        async def run_cycle(self, task_context, previous_review, workspace):
            return ForgeResult(
                completed=True,
                summary="done",
                steps_taken=1,
                test_output="ok",
                diff=diff_text,
            )

    class CapturingCritic(ReviewerCritic):
        async def evaluate(self, task_context, diff, test_output):
            captured_graph_ctx.update(task_context)
            return ReviewerResult(
                verdict="approved",
                summary="ok",
                findings=[],
                blocking_count=0,
                non_blocking_count=0,
            )

    sandbox_stub = AsyncMock()
    ws = SandboxWorkspace(sandbox_stub, uuid.uuid4())
    graph = build_task_cycle_graph(
        StubForge(),
        CapturingCritic(),
        ws,
        PostgresTaskCheckpointSaver(),
    )
    await graph.ainvoke(
        {
            "task_id": str(uuid.uuid4()),
            "org_id": str(org.id),
            "cycle_number": 1,
            "task_context": {
                "target_file": "src/main.py",
                "custom_rules": [
                    {
                        "id": str(org_rule.id),
                        "title": "SQL <Tag>",
                        "instruction": "Use params",
                        "severity": "critical",
                        "category": "security",
                    }
                ],
                "team_preferences": [
                    {
                        "pattern_key": "style:src",
                        "status": "dampened",
                        "instruction": "Gentle warning",
                    }
                ],
                "example_prs": [
                    {
                        "pr_number": 15,
                        "pr_title": "Good auth PR",
                        "classification": "good",
                        "guidance_note": "Follow this",
                    }
                ],
            },
            "previous_review": None,
            "clarification_needed": False,
            "clarification_prompt": "",
            "clarification_options": [],
            "clarification_response": None,
            "guidance_messages": [],
            "approved_action_hashes": [],
            "forge_completed": False,
            "forge_summary": "",
            "forge_steps_taken": 0,
            "forge_test_output": "",
            "forge_diff": "",
            "review_verdict": "",
            "review_summary": "",
            "review_findings": [],
            "review_blocking_count": 0,
            "review_non_blocking_count": 0,
            "published": False,
            "pr_url": None,
            "pr_number": None,
            "commit_sha": None,
        },
        config={"configurable": {"thread_id": "graph-spec9-test"}},
    )
    prompt_str = str(captured_graph_ctx.get("custom_review_prompt") or "")
    assert "MUST NOT override core security checks" in prompt_str
    assert "<custom_rules>" in prompt_str and "&lt;Tag&gt;" in prompt_str
    assert "<team_preferences>" in prompt_str
    assert "<example_prs>" in prompt_str


@pytest.mark.asyncio
async def test_analytics_overview_empty_org_auth_and_clamped_pause(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    """Verify 401, null acceptance_rate, 90d series, and deleted rules (AC-6)."""
    # Unauthenticated -> 401
    assert (await client.get("/api/v1/analytics/overview")).status_code == 401

    org, repo = await _seed_org_and_repo(db_session)
    now = datetime.now(UTC)

    # Soft-deleted rule with finding must NOT appear in top_rules
    deleted_rule = ReviewRuleModel(
        org_id=org.id,
        repo_id=repo.id,
        title="Deleted rule",
        instruction="Should not appear",
        severity="minor",
        category="style",
        path_globs=["**/*"],
        is_enabled=True,
        created_by="admin",
        deleted_at=now,
    )
    db_session.add(deleted_rule)
    await db_session.flush()

    rev = PullRequestReviewModel(
        org_id=org.id,
        repo_id=repo.id,
        pr_number=5,
        pr_title="No feedback PR",
        pr_author="dev",
        head_commit_sha="5" * 40,
        base_commit_sha="6" * 40,
        status="completed",
        verdict="comment",
        model_name="claude-sonnet-4",
        execution_duration_ms=None,
        created_at=now,
    )
    db_session.add(rev)
    await db_session.flush()
    db_session.add(
        PRReviewFindingModel(
            review_id=rev.id,
            rule_id=deleted_rule.id,
            file_path="a.py",
            line_number=1,
            severity="minor",
            category="style",
            title="Deleted rule hit",
            message="msg",
            feedback_state="none",
            created_at=now,
        )
    )

    # Task run where paused_seconds exceeds wall clock -> active duration clamps to 0.0
    task = TaskModel(
        org_id=org.id,
        repo_id=repo.id,
        title="Paused task",
        description="desc",
        status="completed",
        trigger_type="github_issue",
    )
    db_session.add(task)
    await db_session.flush()
    db_session.add(
        TaskRunModel(
            org_id=org.id,
            task_id=task.id,
            run_number=1,
            status="completed",
            paused_seconds=500,
            started_at=now - timedelta(seconds=10),
            completed_at=now,
        )
    )
    await db_session.commit()

    member_hdrs = _auth_headers(org.clerk_org_id, org_role="org:member")
    res = await client.get("/api/v1/analytics/overview?days=90", headers=member_hdrs)
    assert res.status_code == 200
    data = res.json()
    assert data["days"] == 90
    assert len(data["daily_series"]) == 90
    assert data["kpis"]["acceptance_rate"] is None
    assert data["kpis"]["turnaround_p50_ms"] is None
    assert data["kpis"]["task_turnaround_p50_ms"] == 0.0
    assert data["top_rules"] == []
