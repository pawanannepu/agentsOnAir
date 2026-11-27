"""Comprehensive tests for Spec 0008: Guardrails, Branch Protection & Budget Limits."""

import json
import subprocess
import uuid
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.application.schemas.guardrails import (
    GuardrailPolicy,
    GuardrailPolicyOverride,
    apply_guardrail_overrides,
)
from app.application.services.sandbox_workspace import SandboxWorkspace
from app.application.services.usage_tracker import UsageTracker
from app.application.use_cases.run_autonomous_loop import RunAutonomousLoopUseCase
from app.application.use_cases.run_pr_review import RunPRReviewUseCase
from app.core.config import settings
from app.core.pricing import estimate_cost_cents
from app.domain.entities.task_run import TaskRun
from app.domain.exceptions import (
    ApprovalRequiredError,
    GuardrailBlockedError,
    ProtectedBranchError,
    ValidationError,
)
from app.domain.services.policy_evaluator import (
    EffectiveGuardrailPolicy,
    PolicyEvaluator,
)
from app.infrastructure.db.models.audit_log import AuditLogModel
from app.infrastructure.db.models.task_approval import TaskApprovalModel
from app.infrastructure.db.models.usage_event import UsageEventModel
from app.infrastructure.db.repositories.audit_log_repository import (
    SqlAlchemyAuditLogRepository,
)
from app.infrastructure.db.repositories.organization_repository import (
    SqlAlchemyOrganizationRepository,
)
from app.infrastructure.db.repositories.pr_review_repository import (
    SqlAlchemyPRReviewRepository,
)
from app.infrastructure.db.repositories.repository_repository import (
    SqlAlchemyRepositoryRepository,
)
from app.infrastructure.db.repositories.review_iteration_repository import (
    SqlAlchemyReviewIterationRepository,
)
from app.infrastructure.db.repositories.sandbox_run_repository import (
    SqlAlchemySandboxRunRepository,
)
from app.infrastructure.db.repositories.task_approval_repository import (
    SqlAlchemyTaskApprovalRepository,
)
from app.infrastructure.db.repositories.task_repository import (
    SqlAlchemyTaskRepository,
)
from app.infrastructure.db.repositories.task_run_repository import (
    SqlAlchemyTaskRunRepository,
)
from app.infrastructure.db.repositories.task_transcript_repository import (
    SqlAlchemyTaskTranscriptRepository,
)
from app.infrastructure.db.repositories.usage_repository import (
    SqlAlchemyUsageRepository,
)
from app.infrastructure.events.redis_streamer import InMemoryOrRedisEventStreamer
from app.infrastructure.github.github_service import GitHubService
from app.infrastructure.llm.agents import ForgeCoderAgent, ReviewerCriticAgent
from app.infrastructure.queue.arq_queue import ArqTaskQueue
from app.infrastructure.queue.worker import handle_interruption_timeout
from app.infrastructure.sandbox.mock_sandbox import (
    MockSandboxProvider,
    MockSandboxSession,
)
from app.infrastructure.sandbox.registry import SandboxRegistry
from tests.clerk_test_helpers import generate_rsa_keypair, make_clerk_jwt

_PRIV_PEM, _PUB_PEM = generate_rsa_keypair()


@pytest.fixture(autouse=True)
def _configure_clerk_key(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "CLERK_JWT_KEY", _PUB_PEM)


def _auth_headers(
    clerk_org_id: str,
    org_role: str = "org:member",
    user_id: str = "user_test_1",
) -> dict[str, str]:
    token = make_clerk_jwt(
        _PRIV_PEM,
        user_id=user_id,
        clerk_org_id=clerk_org_id,
        org_role=org_role,
    )
    return {"Authorization": f"Bearer {token}"}


# ---------------------------------------------------------------------------
# Unit tests: PolicyEvaluator, GuardrailPolicy schemas, pricing.py
# ---------------------------------------------------------------------------


def test_policy_merge_and_null_override_deletion():
    """Verify org defaults, repo overrides, and null key removal (AC-1)."""
    org_settings = {
        "max_task_cost_cents": 800,
        "protected_branches": ["main", "prod/*"],
        "network_egress_mode": "allowlist",
        "allowed_egress_domains": ["pypi.org", "*.npmjs.org"],
    }
    repo_config = {
        "test_command": "pytest -q",
        "install_command": "uv sync",
        "guardrails": {
            "max_task_cost_cents": 250,
            "timeout_minutes": 15,
        },
    }
    merged = PolicyEvaluator.merge_policy(org_settings, repo_config)
    assert merged.max_task_cost_cents == 250
    assert merged.timeout_minutes == 15
    assert merged.protected_branches == ("main", "prod/*")
    assert merged.network_egress_mode == "allowlist"
    assert merged.allowed_egress_domains == ("pypi.org", "*.npmjs.org")

    patch = GuardrailPolicyOverride(max_task_cost_cents=None)
    updated_overrides = apply_guardrail_overrides(repo_config["guardrails"], patch)
    assert "max_task_cost_cents" not in updated_overrides
    assert updated_overrides["timeout_minutes"] == 15

    # Reject protected_branch_guard: false when protected_branches non-empty
    with pytest.raises(ValueError):
        GuardrailPolicy(
            protected_branch_guard=False,
            protected_branches=["main"],
        )

    # Reject invalid domain patterns
    with pytest.raises(ValueError):
        GuardrailPolicy(allowed_egress_domains=["HTTPS://UPPER.COM"])


def test_policy_evaluator_classifications_and_action_hash():
    """Verify shlex command matching, sensitive globs, and diff line counting (AC-3)."""
    evaluator = PolicyEvaluator()
    policy = EffectiveGuardrailPolicy(
        protected_branches=("main", "master", "release/*"),
        network_egress_mode="off_after_install",
        large_diff_lines_threshold=5,
    )

    assert evaluator.is_protected_branch("refs/heads/main", policy) is True
    assert evaluator.is_protected_branch("release/v1.2", policy) is True
    assert evaluator.is_protected_branch("feat/guardrails", policy) is False

    # external_network blocked immediately when network_egress_mode == off_after_install
    net_res = evaluator.classify_command("curl https://example.com", policy)
    assert net_res.decision == "block"
    assert net_res.risk_category == "external_network"

    # destructive_shell
    rm_res = evaluator.classify_command("rm -rf /tmp/foo", policy)
    assert rm_res.decision == "require_approval"
    assert rm_res.risk_category == "destructive_shell"

    # force_git_op
    git_res = evaluator.classify_command("git push --force origin feat/x", policy)
    assert git_res.decision == "require_approval"
    assert git_res.risk_category == "force_git_op"

    # sensitive_path_edit (including top-level .env and .github/workflows/**)
    ci_res = evaluator.classify_file_write(".github/workflows/ci.yml", policy)
    assert ci_res.decision == "require_approval"
    assert ci_res.risk_category == "sensitive_path_edit"

    env_res = evaluator.classify_file_write(".env.production", policy)
    assert env_res.decision == "require_approval"
    assert env_res.risk_category == "sensitive_path_edit"

    auth_res = evaluator.classify_file_write("apps/agent/app/auth/jwt.py", policy)
    assert auth_res.decision == "require_approval"

    safe_res = evaluator.classify_file_write("src/calculator.py", policy)
    assert safe_res.decision == "allow"

    # large_diff ignores +++ / --- / @@ headers
    diff = (
        "--- a/foo.py\n"
        "+++ b/foo.py\n"
        "@@ -1,2 +1,7 @@\n"
        "+a = 1\n"
        "+b = 2\n"
        "+c = 3\n"
        "+d = 4\n"
        "+e = 5\n"
        "+f = 6\n"
    )
    assert evaluator.count_diff_lines(diff) == 6
    diff_res = evaluator.classify_publish("feat/x", diff, policy, cycle_number=1)
    assert diff_res.decision == "require_approval"
    assert diff_res.risk_category == "large_diff"


def test_pricing_ceiling_cent_math_and_overrides(monkeypatch: pytest.MonkeyPatch):
    """Verify ceiling integer cent pricing and env overrides (AC-5)."""
    assert estimate_cost_cents("claude-sonnet-4", 0, 0) == 0
    assert estimate_cost_cents("claude-sonnet-4", 1, 1) == 1

    # 1M input at 300 cents + 1M output at 1500 cents = 1800 cents
    assert estimate_cost_cents("claude-sonnet-4", 1_000_000, 1_000_000) == 1800

    monkeypatch.setattr(
        settings,
        "MODEL_PRICING_OVERRIDES_JSON",
        json.dumps(
            {
                "custom-fast": {
                    "input_cents_per_million": 100,
                    "output_cents_per_million": 200,
                }
            }
        ),
    )
    assert estimate_cost_cents("custom-fast", 500_000, 500_000) == 150
    # Unknown model falls back conservatively (1000 input + 3000 output)
    assert estimate_cost_cents("unknown-xyz", 1_000_000, 0) == 1000


def test_active_runtime_excludes_paused_seconds():
    """Verify UsageTracker excludes paused_seconds from timeout_minutes (AC-6)."""
    now = datetime.now(UTC)
    run = TaskRun(
        id=uuid.uuid4(),
        org_id=uuid.uuid4(),
        task_id=uuid.uuid4(),
        started_at=now - timedelta(minutes=12),
        paused_seconds=300,  # 5 minutes paused -> 7 active minutes
    )
    policy = EffectiveGuardrailPolicy(timeout_minutes=10)
    remaining = UsageTracker.get_remaining_active_seconds(run, policy, now=now)
    assert 175 <= remaining <= 185


# ---------------------------------------------------------------------------
# Sandbox & GitHub Gateway branch protection + egress tests (AC-2, AC-7)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_host_github_gateway_and_sandbox_pre_push_hook(tmp_path: Path):
    """Verify host GitHubGateway & sandbox pre-push hook block protected branches."""
    gh = GitHubService()
    write_tok = await gh.get_installation_token(101, write_access=True)
    read_tok = await gh.get_installation_token(101, write_access=False)

    with pytest.raises(ValidationError):
        await gh.push_branch("org/repo", "feat/ok", "msg", read_tok)

    for protected in ("main", "refs/heads/main", "release/v1"):
        with pytest.raises(ProtectedBranchError):
            await gh.push_branch("org/repo", protected, "msg", write_tok)
        with pytest.raises(ProtectedBranchError):
            await gh.create_pull_request(
                "org/repo", "main", protected, "t", "b", write_tok
            )

    # Create a bare remote repo + local clone URL with embedded token
    bare_dir = tmp_path / "remote.git"
    subprocess.run(["git", "init", "--bare", str(bare_dir)], check=True)

    provider = MockSandboxProvider()
    org_id = uuid.uuid4()
    task_id = uuid.uuid4()
    policy = EffectiveGuardrailPolicy(
        protected_branches=("main", "release/*"),
        network_egress_mode="allowlist",
        allowed_egress_domains=("pypi.org",),
    )
    session = await provider.create_sandbox(
        org_id,
        task_id,
        network_egress_mode=policy.network_egress_mode,
        allowed_egress_domains=policy.allowed_egress_domains,
    )
    workspace = SandboxWorkspace(session, task_id, policy=policy)

    try:
        # Reject write tokens passed into sandbox
        with pytest.raises(ValidationError):
            await workspace.init_workspace(
                repo_url_with_read_token="https://x-access-token:ghs_write_abc@github.com/org/repo.git"
            )

        await workspace.init_workspace(
            repo_url_with_read_token=None,
            base_branch="main",
            work_branch="feat/safe",
            protected_branches=policy.protected_branches,
            install_command="echo 'installed deps'",
        )
        assert isinstance(session, MockSandboxSession)
        assert session.network_restricted is True
        assert session.network_egress_mode == "allowlist"

        # Verify credential stripping helper removes token from origin URL
        await session.execute_command(
            "git remote add origin https://x-access-token:ghs_read_123@github.com/org/repo.git"
        )
        await workspace.strip_remote_credentials()
        remote_url = (
            await session.execute_command("git remote get-url origin")
        ).stdout.strip()
        assert "ghs_read_" not in remote_url
        assert remote_url == "https://github.com/org/repo.git"

        # Wire bare remote and verify system core.hooksPath hook blocks protected push
        await session.execute_command(f"git remote set-url origin {bare_dir}")
        await session.write_file("README.md", "hello\n")
        await session.execute_command("git add README.md && git commit -m 'init'")

        push_main = await session.execute_command(
            "git push origin HEAD:refs/heads/main"
        )
        assert push_main.exit_code != 0
        assert "protected_branch_blocked" in push_main.stderr

        push_rel = await session.execute_command(
            "git push origin HEAD:refs/heads/release/v1"
        )
        assert push_rel.exit_code != 0
        assert "protected_branch_blocked" in push_rel.stderr

        # External network blocked when off_after_install; run_test allowed
        off_ws = SandboxWorkspace(
            session,
            task_id,
            policy=EffectiveGuardrailPolicy(network_egress_mode="off_after_install"),
        )
        with pytest.raises(GuardrailBlockedError):
            await off_ws.run_command("curl https://evil.example.com")
        with pytest.raises(ApprovalRequiredError):
            await off_ws.write_file(".github/workflows/ci.yml", "name: ci\n")
        test_res = await off_ws.run_test("echo 'tests pass'")
        assert test_res.exit_code == 0
    finally:
        await session.terminate()


# ---------------------------------------------------------------------------
# Integration tests: Approval pause, /respond 409, RBAC, concurrency, resume
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_approval_interrupt_resume_concurrency_and_rbac(
    client: AsyncClient, db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
):
    """Verify approval pause, /respond 409, RBAC, 409 race, and resume (AC-3, AC-4)."""
    org_repo = SqlAlchemyOrganizationRepository(db_session)
    repo_repo = SqlAlchemyRepositoryRepository(db_session)
    task_repo = SqlAlchemyTaskRepository(db_session)
    task_run_repo = SqlAlchemyTaskRunRepository(db_session)
    sandbox_run_repo = SqlAlchemySandboxRunRepository(db_session)
    review_repo = SqlAlchemyReviewIterationRepository(db_session)
    audit_repo = SqlAlchemyAuditLogRepository(db_session)
    approval_repo = SqlAlchemyTaskApprovalRepository(db_session)
    transcript_repo = SqlAlchemyTaskTranscriptRepository(db_session)
    usage_repo = SqlAlchemyUsageRepository(session=db_session)

    org = await org_repo.create_or_update(
        clerk_org_id=f"org_{uuid.uuid4().hex[:12]}",
        name="Guardrails Test Org",
        slug=f"guard-org-{uuid.uuid4().hex[:8]}",
    )
    repo = await repo_repo.create(
        org_id=org.id,
        github_repo_id=55667788,
        github_installation_id=4444,
        name="guard-repo",
        full_name="guardorg/guard-repo",
        default_branch="main",
    )
    task = await task_repo.create_task(
        org_id=org.id,
        repo_id=repo.id,
        title="Update CI workflow safely",
        description="Edit module and update CI workflow",
        trigger_type="manual_console",
        base_branch="main",
        branch_name="feat/ci-update",
    )
    await db_session.commit()

    streamer = InMemoryOrRedisEventStreamer()
    queue = ArqTaskQueue()
    monkeypatch.setattr("app.api.v1.endpoints.tasks.get_task_queue", lambda: queue)
    monkeypatch.setattr(
        "app.api.v1.endpoints.tasks.get_event_streamer", lambda: streamer
    )
    registry = SandboxRegistry()

    use_case = RunAutonomousLoopUseCase(
        task_repo=task_repo,
        task_run_repo=task_run_repo,
        sandbox_run_repo=sandbox_run_repo,
        review_iteration_repo=review_repo,
        audit_log_repo=audit_repo,
        repository_repo=repo_repo,
        sandbox_provider=MockSandboxProvider(),
        github_gateway=GitHubService(),
        forge_agent=ForgeCoderAgent(),
        reviewer_critic=ReviewerCriticAgent(),
        event_streamer=streamer,
        task_transcript_repo=transcript_repo,
        task_queue=queue,
        sandbox_registry=registry,
        organization_repo=org_repo,
        task_approval_repo=approval_repo,
        usage_repo=usage_repo,
    )

    paused_task = await use_case.execute(
        org.id,
        task.id,
        options={
            "test_command": "echo 'ok'",
            "target_file": "src/app.py",
            "risky_write_path": ".github/workflows/ci.yml",
            "risky_write_content": "name: CI\n",
        },
    )
    await db_session.commit()

    assert paused_task.status == "awaiting_input"
    assert paused_task.interruption_type == "approval"

    pending_approval = await approval_repo.get_pending_for_task(org.id, task.id)
    assert pending_approval is not None
    assert pending_approval.risk_category == "sensitive_path_edit"
    assert pending_approval.action_payload["path"] == ".github/workflows/ci.yml"

    events = await streamer.read_events(task.id, count=50)
    assert any(et == "task.approval_requested" for _, et, _, _ in events)

    # 1. /respond rejects approval pauses with 409 Conflict
    respond_res = await client.post(
        f"/api/v1/tasks/{task.id}/respond",
        headers=_auth_headers(org.clerk_org_id, org_role="org:admin"),
        json={"response": "Approve"},
    )
    assert respond_res.status_code == 409

    # 2. Non-admin receives 403 on approval decision
    member_res = await client.post(
        f"/api/v1/tasks/{task.id}/approvals/{pending_approval.id}/decision",
        headers=_auth_headers(org.clerk_org_id, org_role="org:member"),
        json={"decision": "approved"},
    )
    assert member_res.status_code == 403

    # 3. GET /api/v1/tasks/{task_id} includes pending_approval and budget_summary
    detail_res = await client.get(
        f"/api/v1/tasks/{task.id}",
        headers=_auth_headers(org.clerk_org_id, org_role="org:member"),
    )
    assert detail_res.status_code == 200
    detail_json = detail_res.json()
    assert detail_json["pending_approval"]["approval_id"] == str(pending_approval.id)
    assert detail_json["budget_summary"]["max_task_cost_cents"] == 500

    # 4. Admin approves -> 200, second decision -> 409, watchdog expiry -> False
    admin_res = await client.post(
        f"/api/v1/tasks/{task.id}/approvals/{pending_approval.id}/decision",
        headers=_auth_headers(
            org.clerk_org_id, org_role="org:admin", user_id="admin_1"
        ),
        json={"decision": "approved", "note": "Looks safe"},
    )
    assert admin_res.status_code == 200
    assert admin_res.json()["status"] == "approved"
    assert admin_res.json()["task_status"] == "in_progress"
    resume_jobs = [j for j in queue.scheduled_jobs if j.job_name == "resume_task_job"]
    assert len(resume_jobs) == 1
    assert resume_jobs[0].args[4] == {
        "approval_id": str(pending_approval.id),
        "decision": "approved",
    }

    conflict_res = await client.post(
        f"/api/v1/tasks/{task.id}/approvals/{pending_approval.id}/decision",
        headers=_auth_headers(
            org.clerk_org_id, org_role="org:admin", user_id="admin_2"
        ),
        json={"decision": "rejected"},
    )
    assert conflict_res.status_code == 409

    expired = await handle_interruption_timeout(db_session, org.id, task.id)
    assert expired is False

    # 5. Simulate resuming on a DIFFERENT worker (empty SandboxRegistry)
    fresh_registry = SandboxRegistry()
    resume_uc = RunAutonomousLoopUseCase(
        task_repo=task_repo,
        task_run_repo=task_run_repo,
        sandbox_run_repo=sandbox_run_repo,
        review_iteration_repo=review_repo,
        audit_log_repo=audit_repo,
        repository_repo=repo_repo,
        sandbox_provider=MockSandboxProvider(),
        github_gateway=GitHubService(),
        forge_agent=ForgeCoderAgent(),
        reviewer_critic=ReviewerCriticAgent(),
        event_streamer=streamer,
        task_transcript_repo=transcript_repo,
        task_queue=queue,
        sandbox_registry=fresh_registry,
        organization_repo=org_repo,
        task_approval_repo=approval_repo,
        usage_repo=usage_repo,
    )
    completed = await resume_uc.resume(
        org.id,
        task.id,
        response={"approval_id": str(pending_approval.id), "decision": "approved"},
    )
    await db_session.commit()

    assert completed.status == "completed"
    assert completed.pr_url is not None

    refreshed_approval = await approval_repo.get_by_id(org.id, pending_approval.id)
    assert refreshed_approval.consumed_at is not None

    usage_events = (
        (
            await db_session.execute(
                select(UsageEventModel).where(UsageEventModel.task_id == task.id)
            )
        )
        .scalars()
        .all()
    )
    assert len(usage_events) >= 2  # forge + reviewer


@pytest.mark.asyncio
async def test_budget_cap_and_watchdog_approval_expiry(
    db_session: AsyncSession,
):
    """Verify budget_exceeded preserves partial_diff and watchdog expires approvals."""
    org_repo = SqlAlchemyOrganizationRepository(db_session)
    repo_repo = SqlAlchemyRepositoryRepository(db_session)
    task_repo = SqlAlchemyTaskRepository(db_session)
    task_run_repo = SqlAlchemyTaskRunRepository(db_session)
    sandbox_run_repo = SqlAlchemySandboxRunRepository(db_session)
    review_repo = SqlAlchemyReviewIterationRepository(db_session)
    audit_repo = SqlAlchemyAuditLogRepository(db_session)
    approval_repo = SqlAlchemyTaskApprovalRepository(db_session)
    transcript_repo = SqlAlchemyTaskTranscriptRepository(db_session)
    usage_repo = SqlAlchemyUsageRepository(session=db_session)

    org = await org_repo.create_or_update(
        clerk_org_id=f"org_{uuid.uuid4().hex[:12]}",
        name="Budget Halt Org",
        slug=f"budget-org-{uuid.uuid4().hex[:8]}",
        settings={"max_task_cost_cents": 1, "max_monthly_org_cost_cents": 10000},
    )
    repo = await repo_repo.create(
        org_id=org.id,
        github_repo_id=99887766,
        github_installation_id=7777,
        name="budget-repo",
        full_name="budgetorg/budget-repo",
    )
    task = await task_repo.create_task(
        org_id=org.id,
        repo_id=repo.id,
        title="Expensive task",
        description="Should halt after hitting 1 cent task cap",
        trigger_type="manual_console",
        branch_name="feat/expensive",
    )
    await db_session.commit()

    streamer = InMemoryOrRedisEventStreamer()
    use_case = RunAutonomousLoopUseCase(
        task_repo=task_repo,
        task_run_repo=task_run_repo,
        sandbox_run_repo=sandbox_run_repo,
        review_iteration_repo=review_repo,
        audit_log_repo=audit_repo,
        repository_repo=repo_repo,
        sandbox_provider=MockSandboxProvider(),
        github_gateway=GitHubService(),
        forge_agent=ForgeCoderAgent(),
        reviewer_critic=ReviewerCriticAgent(),
        event_streamer=streamer,
        task_transcript_repo=transcript_repo,
        organization_repo=org_repo,
        task_approval_repo=approval_repo,
        usage_repo=usage_repo,
    )
    halted = await use_case.execute(
        org.id,
        task.id,
        options={
            "test_command": "echo 'ok'",
            "simulated_prompt_tokens": 5000,
            "simulated_completion_tokens": 1000,
        },
    )
    await db_session.commit()

    assert halted.status == "failed"
    run = await task_run_repo.get_latest_by_task(org.id, task.id)
    assert run.failure_reason == "budget_exceeded"
    assert run.estimated_cost_cents >= 1

    # Also verify PR review monthly budget cap blocks RunPRReviewUseCase
    pr_review_repo = SqlAlchemyPRReviewRepository(db_session)
    await org_repo.update_settings(org.id, {"max_monthly_org_cost_cents": 1})
    review = await pr_review_repo.create_review(
        org_id=org.id,
        repo_id=repo.id,
        pr_number=99,
        pr_title="PR blocked by monthly budget",
        pr_author="alice",
        head_commit_sha="a" * 40,
        base_commit_sha="b" * 40,
        model_name="claude-sonnet-4",
    )
    await db_session.commit()

    pr_uc = RunPRReviewUseCase(
        pr_review_repo=pr_review_repo,
        repository_repo=repo_repo,
        github_gateway=GitHubService(),
        audit_log_repo=audit_repo,
        organization_repo=org_repo,
        usage_repo=usage_repo,
    )
    failed_review = await pr_uc.execute(org.id, review.id)
    assert failed_review.status == "failed"
    assert failed_review.error_message == "budget_exceeded"

    # Watchdog approval_expired path
    task2 = await task_repo.create_task(
        org_id=org.id,
        repo_id=repo.id,
        title="Expiring approval task",
        description="Needs approval that expires",
        trigger_type="manual_console",
        branch_name="feat/expire",
    )
    await org_repo.update_settings(
        org.id, {"max_task_cost_cents": 500, "max_monthly_org_cost_cents": 10000}
    )
    await db_session.commit()

    registry = SandboxRegistry()
    use_case2 = RunAutonomousLoopUseCase(
        task_repo=task_repo,
        task_run_repo=task_run_repo,
        sandbox_run_repo=sandbox_run_repo,
        review_iteration_repo=review_repo,
        audit_log_repo=audit_repo,
        repository_repo=repo_repo,
        sandbox_provider=MockSandboxProvider(),
        github_gateway=GitHubService(),
        forge_agent=ForgeCoderAgent(),
        reviewer_critic=ReviewerCriticAgent(),
        event_streamer=streamer,
        task_transcript_repo=transcript_repo,
        sandbox_registry=registry,
        organization_repo=org_repo,
        task_approval_repo=approval_repo,
        usage_repo=usage_repo,
    )
    paused2 = await use_case2.execute(
        org.id,
        task2.id,
        options={
            "test_command": "echo 'ok'",
            "risky_command": "rm -rf /tmp/nonexistent",
        },
    )
    await db_session.commit()
    assert paused2.status == "awaiting_input"

    did_expire = await handle_interruption_timeout(
        db_session,
        org.id,
        task2.id,
        event_streamer=streamer,
        sandbox_registry=registry,
    )
    await db_session.commit()
    assert did_expire is True

    expired_task = await task_repo.get_by_id(org.id, task2.id)
    assert expired_task.status == "failed"
    expired_run = await task_run_repo.get_latest_by_task(org.id, task2.id)
    assert expired_run.failure_reason == "approval_expired"

    app_row = (
        await db_session.execute(
            select(TaskApprovalModel).where(TaskApprovalModel.task_id == task2.id)
        )
    ).scalar_one()
    assert app_row.status == "expired"


# ---------------------------------------------------------------------------
# API endpoints: organizations guardrails/usage & repositories guardrails
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_guardrails_and_usage_api_endpoints(
    client: AsyncClient, db_session: AsyncSession
):
    """Verify org guardrails, usage, repositories list, and overrides APIs."""
    org_repo = SqlAlchemyOrganizationRepository(db_session)
    repo_repo = SqlAlchemyRepositoryRepository(db_session)

    org = await org_repo.create_or_update(
        clerk_org_id=f"org_{uuid.uuid4().hex[:12]}",
        name="API Guardrails Org",
        slug=f"api-guard-{uuid.uuid4().hex[:8]}",
    )
    repo = await repo_repo.create(
        org_id=org.id,
        github_repo_id=33445566,
        github_installation_id=1122,
        name="api-repo",
        full_name="apiorg/api-repo",
        config={"test_command": "pytest -v"},
    )
    await db_session.commit()

    # Member can read guardrails, usage, and repositories
    g_res = await client.get(
        "/api/v1/organizations/guardrails",
        headers=_auth_headers(org.clerk_org_id, org_role="org:member"),
    )
    assert g_res.status_code == 200
    assert g_res.json()["max_task_cost_cents"] == 500

    u_res = await client.get(
        "/api/v1/organizations/usage",
        headers=_auth_headers(org.clerk_org_id, org_role="org:member"),
    )
    assert u_res.status_code == 200
    assert u_res.json()["total_cost_cents"] == 0
    assert u_res.json()["remaining_cents"] == 10000

    bad_month = await client.get(
        "/api/v1/organizations/usage?month=2026-13",
        headers=_auth_headers(org.clerk_org_id, org_role="org:member"),
    )
    assert bad_month.status_code == 422

    # Member cannot PATCH org settings or repo guardrails (403)
    mem_patch = await client.patch(
        f"/api/v1/repositories/{repo.id}/guardrails",
        headers=_auth_headers(org.clerk_org_id, org_role="org:member"),
        json={"max_task_cost_cents": 200},
    )
    assert mem_patch.status_code == 403

    # Admin updates org settings; protected_branch_guard=false rejected (422)
    bad_settings = await client.patch(
        "/api/v1/organizations/settings",
        headers=_auth_headers(org.clerk_org_id, org_role="org:admin"),
        json={"protected_branch_guard": False},
    )
    assert bad_settings.status_code == 422

    ok_settings = await client.patch(
        "/api/v1/organizations/settings",
        headers=_auth_headers(org.clerk_org_id, org_role="org:admin"),
        json={
            "max_task_cost_cents": 750,
            "network_egress_mode": "allowlist",
            "allowed_egress_domains": ["*.pypi.org"],
        },
    )
    assert ok_settings.status_code == 200

    # Admin updates repository override while preserving test_command
    patch_repo = await client.patch(
        f"/api/v1/repositories/{repo.id}/guardrails",
        headers=_auth_headers(org.clerk_org_id, org_role="org:admin"),
        json={"max_task_cost_cents": 300, "timeout_minutes": 20},
    )
    assert patch_repo.status_code == 200
    assert patch_repo.json()["effective_policy"]["max_task_cost_cents"] == 300
    assert patch_repo.json()["effective_policy"]["timeout_minutes"] == 20

    # Sending null removes override and falls back to org default (750)
    clear_repo = await client.patch(
        f"/api/v1/repositories/{repo.id}/guardrails",
        headers=_auth_headers(org.clerk_org_id, org_role="org:admin"),
        json={"max_task_cost_cents": None},
    )
    assert clear_repo.status_code == 200
    assert "max_task_cost_cents" not in clear_repo.json()["repo_overrides"]
    assert clear_repo.json()["effective_policy"]["max_task_cost_cents"] == 750

    repos_res = await client.get(
        "/api/v1/repositories",
        headers=_auth_headers(org.clerk_org_id, org_role="org:member"),
    )
    assert repos_res.status_code == 200
    assert repos_res.json()["total"] == 1
    assert repos_res.json()["items"][0]["config"]["test_command"] == "pytest -v"

    # Immutable audit logs recorded for settings & repo overrides
    audits = (
        (
            await db_session.execute(
                select(AuditLogModel).where(AuditLogModel.org_id == org.id)
            )
        )
        .scalars()
        .all()
    )
    actions = {a.action for a in audits}
    assert "organization.settings_updated" in actions
    assert "repository.guardrails_updated" in actions


@pytest.mark.asyncio
async def test_init_workspace_clones_and_captures_untracked_diff(
    tmp_path: Path,
):
    """Verify clone succeeds after git init and get_diff captures untracked files."""
    from app.infrastructure.sandbox.docker_sandbox import DockerSandboxProvider

    bare_dir = tmp_path / "remote.git"
    seed_dir = tmp_path / "seed"
    subprocess.run(["git", "init", "--bare", str(bare_dir)], check=True)
    subprocess.run(["git", "init", "-b", "main", str(seed_dir)], check=True)
    subprocess.run(
        ["git", "-C", str(seed_dir), "config", "user.name", "Seed"], check=True
    )
    subprocess.run(
        ["git", "-C", str(seed_dir), "config", "user.email", "seed@example.com"],
        check=True,
    )
    (seed_dir / "README.md").write_text("seed\n", encoding="utf-8")
    subprocess.run(["git", "-C", str(seed_dir), "add", "."], check=True)
    subprocess.run(["git", "-C", str(seed_dir), "commit", "-m", "init"], check=True)
    subprocess.run(
        ["git", "-C", str(seed_dir), "remote", "add", "origin", str(bare_dir)],
        check=True,
    )
    subprocess.run(
        ["git", "-C", str(seed_dir), "push", "-u", "origin", "main"], check=True
    )

    for provider in (MockSandboxProvider(), DockerSandboxProvider()):
        session = await provider.create_sandbox(uuid.uuid4(), uuid.uuid4())
        workspace = SandboxWorkspace(session, uuid.uuid4())
        work_branch = f"agentsonair/clone-fix-{session.provider}"
        try:
            await workspace.init_workspace(
                repo_url_with_read_token=str(bare_dir),
                base_branch="main",
                work_branch=work_branch,
                protected_branches=("main", "release/*"),
            )
            readme = await workspace.read_file("README.md")
            assert readme == "seed\n"

            await workspace.write_file("src/added.py", "def ok():\n    return 1\n")
            diff = await workspace.get_diff()
            assert "src/added.py" in diff
            assert "+def ok():" in diff

            await session.execute_command(
                "git add src/added.py && git commit -m 'work'"
            )
            push_main = await session.execute_command("git push origin HEAD:main")
            assert push_main.exit_code != 0
            assert "protected_branch_blocked" in push_main.stderr

            push_feat = await session.execute_command(
                f"git push origin HEAD:{work_branch}"
            )
            assert push_feat.exit_code == 0
        finally:
            await session.terminate()

    # Also verify unborn workspace (no initial commit) captures untracked file diff
    unborn_session = await MockSandboxProvider().create_sandbox(
        uuid.uuid4(), uuid.uuid4()
    )
    unborn_ws = SandboxWorkspace(unborn_session, uuid.uuid4())
    try:
        await unborn_ws.init_workspace(None, "main", "agentsonair/unborn-diff")
        await unborn_ws.write_file("src/fresh.py", "VALUE = 42\n")
        unborn_diff = await unborn_ws.get_diff()
        assert "src/fresh.py" in unborn_diff
        assert "+VALUE = 42" in unborn_diff
    finally:
        await unborn_session.terminate()


@pytest.mark.asyncio
async def test_guardrail_schema_bounds_policy_edges_and_e2b_egress():
    """Verify Pydantic bounds, policy edges, and E2B egress (AC-1, AC-3, AC-7)."""
    from unittest.mock import AsyncMock

    from app.infrastructure.sandbox.e2b_sandbox import E2BSandboxSession

    for invalid_kwargs in (
        {"timeout_minutes": 0},
        {"timeout_minutes": 61},
        {"max_cycles": 0},
        {"max_cycles": 11},
        {"max_task_cost_cents": 0},
        {"max_monthly_org_cost_cents": 0},
        {"large_diff_lines_threshold": 0},
        {"protected_branches": []},
        {"allowed_egress_domains": ["not_a_host"]},
    ):
        with pytest.raises(ValueError):
            GuardrailPolicy.model_validate(invalid_kwargs)

    ok_policy = GuardrailPolicy(
        allowed_egress_domains=["*.pypi.org", "registry.npmjs.org"]
    )
    assert ok_policy.allowed_egress_domains == ["*.pypi.org", "registry.npmjs.org"]

    evaluator = PolicyEvaluator()
    allowlist_policy = EffectiveGuardrailPolicy(
        network_egress_mode="allowlist",
        allowed_egress_domains=("pypi.org",),
    )

    chained_rm = evaluator.classify_command(
        "echo ok && rm -rf /tmp/x", allowlist_policy
    )
    assert chained_rm.decision == "require_approval"
    assert chained_rm.risk_category == "destructive_shell"

    redir_env = evaluator.classify_command(
        "echo SECRET=1 > .env.local", allowlist_policy
    )
    assert redir_env.decision == "require_approval"
    assert redir_env.risk_category == "sensitive_path_edit"

    cp_ci = evaluator.classify_command(
        "cp hack.yml .github/workflows/deploy.yml", allowlist_policy
    )
    assert cp_ci.decision == "require_approval"
    assert cp_ci.risk_category == "sensitive_path_edit"

    net_allow = evaluator.classify_command(
        "curl https://pypi.org/simple", allowlist_policy
    )
    assert net_allow.decision == "require_approval"
    assert net_allow.risk_category == "external_network"

    rebase_res = evaluator.classify_command("git rebase main", allowlist_policy)
    assert rebase_res.decision == "require_approval"
    assert rebase_res.risk_category == "force_git_op"

    chmod_res = evaluator.classify_command("chmod 777 app.py", allowlist_policy)
    assert chmod_res.decision == "require_approval"
    assert chmod_res.risk_category == "destructive_shell"

    dd_res = evaluator.classify_command(
        "dd if=/dev/zero of=/dev/null", allowlist_policy
    )
    assert dd_res.decision == "require_approval"
    assert dd_res.risk_category == "destructive_shell"

    class _FakeE2B:
        def __init__(self) -> None:
            self.set_network_rules = AsyncMock()
            self.kill = AsyncMock()

    delegate = await MockSandboxProvider().create_sandbox(uuid.uuid4(), uuid.uuid4())
    fake_client = _FakeE2B()
    e2b_sess = E2BSandboxSession(delegate=delegate, e2b_client=fake_client)
    try:
        await e2b_sess.restrict_network("off_after_install", [])
        fake_client.set_network_rules.assert_awaited_with(
            allow_out=[], deny_out=["0.0.0.0/0"]
        )
        await e2b_sess.restrict_network("allowlist", [])
        fake_client.set_network_rules.assert_awaited_with(
            allow_out=[], deny_out=["0.0.0.0/0"]
        )
        await e2b_sess.restrict_network("allowlist", ["*.pypi.org"])
        fake_client.set_network_rules.assert_awaited_with(
            allow_out=["*.pypi.org"], deny_out=["0.0.0.0/0"]
        )
        await e2b_sess.restrict_network("unrestricted", [])
        fake_client.set_network_rules.assert_awaited_with(
            allow_out=["0.0.0.0/0"], deny_out=[]
        )
    finally:
        await e2b_sess.terminate()


@pytest.mark.asyncio
async def test_approval_rejection_cross_org_and_repo_404(
    client: AsyncClient, db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
):
    """Verify repo 404, cross-org 403, and approval rejection (AC-1, AC-4)."""
    org_repo = SqlAlchemyOrganizationRepository(db_session)
    repo_repo = SqlAlchemyRepositoryRepository(db_session)
    task_repo = SqlAlchemyTaskRepository(db_session)
    task_run_repo = SqlAlchemyTaskRunRepository(db_session)
    sandbox_run_repo = SqlAlchemySandboxRunRepository(db_session)
    review_repo = SqlAlchemyReviewIterationRepository(db_session)
    audit_repo = SqlAlchemyAuditLogRepository(db_session)
    approval_repo = SqlAlchemyTaskApprovalRepository(db_session)
    transcript_repo = SqlAlchemyTaskTranscriptRepository(db_session)
    usage_repo = SqlAlchemyUsageRepository(session=db_session)

    org = await org_repo.create_or_update(
        clerk_org_id=f"org_{uuid.uuid4().hex[:12]}",
        name="Reject Org",
        slug=f"reject-{uuid.uuid4().hex[:8]}",
    )
    other_org = await org_repo.create_or_update(
        clerk_org_id=f"org_{uuid.uuid4().hex[:12]}",
        name="Other Org",
        slug=f"other-{uuid.uuid4().hex[:8]}",
    )
    repo = await repo_repo.create(
        org_id=org.id,
        github_repo_id=44556677,
        github_installation_id=3333,
        name="reject-repo",
        full_name="rejectorg/reject-repo",
    )
    task = await task_repo.create_task(
        org_id=org.id,
        repo_id=repo.id,
        title="Risky command task",
        description="Should fail cleanly on rejection",
        trigger_type="manual_console",
        branch_name="feat/reject",
    )
    await db_session.commit()

    missing_id = uuid.uuid4()
    r404 = await client.get(
        f"/api/v1/repositories/{missing_id}/guardrails",
        headers=_auth_headers(org.clerk_org_id, org_role="org:member"),
    )
    assert r404.status_code == 404

    p404 = await client.patch(
        f"/api/v1/repositories/{missing_id}/guardrails",
        headers=_auth_headers(org.clerk_org_id, org_role="org:admin"),
        json={"max_task_cost_cents": 200},
    )
    assert p404.status_code == 404

    streamer = InMemoryOrRedisEventStreamer()
    registry = SandboxRegistry()
    monkeypatch.setattr(
        "app.api.v1.endpoints.tasks.get_event_streamer", lambda: streamer
    )
    monkeypatch.setattr(
        "app.api.v1.endpoints.tasks.get_sandbox_registry", lambda: registry
    )

    uc = RunAutonomousLoopUseCase(
        task_repo=task_repo,
        task_run_repo=task_run_repo,
        sandbox_run_repo=sandbox_run_repo,
        review_iteration_repo=review_repo,
        audit_log_repo=audit_repo,
        repository_repo=repo_repo,
        sandbox_provider=MockSandboxProvider(),
        github_gateway=GitHubService(),
        forge_agent=ForgeCoderAgent(),
        reviewer_critic=ReviewerCriticAgent(),
        event_streamer=streamer,
        task_transcript_repo=transcript_repo,
        sandbox_registry=registry,
        organization_repo=org_repo,
        task_approval_repo=approval_repo,
        usage_repo=usage_repo,
    )
    paused = await uc.execute(
        org.id,
        task.id,
        options={"test_command": "echo ok", "risky_command": "rm -rf /tmp/x"},
    )
    await db_session.commit()
    assert paused.status == "awaiting_input"

    pending = await approval_repo.get_pending_for_task(org.id, task.id)
    assert pending is not None

    cross_org_res = await client.post(
        f"/api/v1/tasks/{task.id}/approvals/{pending.id}/decision",
        headers=_auth_headers(other_org.clerk_org_id, org_role="org:admin"),
        json={"decision": "rejected"},
    )
    assert cross_org_res.status_code == 403

    rej_res = await client.post(
        f"/api/v1/tasks/{task.id}/approvals/{pending.id}/decision",
        headers=_auth_headers(org.clerk_org_id, org_role="org:admin"),
        json={"decision": "rejected", "note": "Too risky"},
    )
    assert rej_res.status_code == 200
    assert rej_res.json()["status"] == "rejected"
    assert rej_res.json()["task_status"] == "failed"

    failed_task = await task_repo.get_by_id(org.id, task.id)
    assert failed_task.status == "failed"
    latest_run = await task_run_repo.get_latest_by_task(org.id, task.id)
    assert latest_run.failure_reason == "approval_rejected"


@pytest.mark.asyncio
async def test_large_diff_gate_cycle_limit_and_partial_diff_on_budget_halt(
    client: AsyncClient, db_session: AsyncSession
):
    """Verify large_diff gate, cycle limit, and partial_diff API (AC-3..6)."""
    org_repo = SqlAlchemyOrganizationRepository(db_session)
    repo_repo = SqlAlchemyRepositoryRepository(db_session)
    task_repo = SqlAlchemyTaskRepository(db_session)
    task_run_repo = SqlAlchemyTaskRunRepository(db_session)
    sandbox_run_repo = SqlAlchemySandboxRunRepository(db_session)
    review_repo = SqlAlchemyReviewIterationRepository(db_session)
    audit_repo = SqlAlchemyAuditLogRepository(db_session)
    approval_repo = SqlAlchemyTaskApprovalRepository(db_session)
    transcript_repo = SqlAlchemyTaskTranscriptRepository(db_session)
    usage_repo = SqlAlchemyUsageRepository(session=db_session)

    org = await org_repo.create_or_update(
        clerk_org_id=f"org_{uuid.uuid4().hex[:12]}",
        name="Caps Org",
        slug=f"caps-{uuid.uuid4().hex[:8]}",
        settings={"large_diff_lines_threshold": 1, "max_cycles": 1},
    )
    repo = await repo_repo.create(
        org_id=org.id,
        github_repo_id=66778899,
        github_installation_id=2222,
        name="caps-repo",
        full_name="capsorg/caps-repo",
    )
    task_ld = await task_repo.create_task(
        org_id=org.id,
        repo_id=repo.id,
        title="Large diff task",
        description="Triggers host large_diff approval",
        trigger_type="manual_console",
        branch_name="feat/large-diff",
    )
    task_cyc = await task_repo.create_task(
        org_id=org.id,
        repo_id=repo.id,
        title="Cycle limit task",
        description="Hits max_cycles=1",
        trigger_type="manual_console",
        branch_name="feat/cycles",
    )
    task_bdg = await task_repo.create_task(
        org_id=org.id,
        repo_id=repo.id,
        title="Partial diff budget task",
        description="Preserves partial_diff on budget halt",
        trigger_type="manual_console",
        branch_name="feat/budget-diff",
    )
    await db_session.commit()

    streamer = InMemoryOrRedisEventStreamer()
    uc = RunAutonomousLoopUseCase(
        task_repo=task_repo,
        task_run_repo=task_run_repo,
        sandbox_run_repo=sandbox_run_repo,
        review_iteration_repo=review_repo,
        audit_log_repo=audit_repo,
        repository_repo=repo_repo,
        sandbox_provider=MockSandboxProvider(),
        github_gateway=GitHubService(),
        forge_agent=ForgeCoderAgent(),
        reviewer_critic=ReviewerCriticAgent(),
        event_streamer=streamer,
        task_transcript_repo=transcript_repo,
        organization_repo=org_repo,
        task_approval_repo=approval_repo,
        usage_repo=usage_repo,
    )

    # 1. large_diff pauses at host_publish_node then resumes to PR completion
    paused_ld = await uc.execute(
        org.id,
        task_ld.id,
        options={"test_command": "echo ok", "target_file": "src/big.py"},
    )
    await db_session.commit()
    assert paused_ld.status == "awaiting_input"
    ld_app = await approval_repo.get_pending_for_task(org.id, task_ld.id)
    assert ld_app is not None
    assert ld_app.risk_category == "large_diff"
    await approval_repo.decide_atomic(
        org.id, task_ld.id, ld_app.id, "approved", "admin_1"
    )
    await db_session.commit()
    done_ld = await uc.resume(
        org.id,
        task_ld.id,
        response={"approval_id": str(ld_app.id), "decision": "approved"},
    )
    await db_session.commit()
    assert done_ld.status == "completed"
    assert done_ld.pr_number is not None

    # 2. max_cycles exhausted halts with review_cycle_limit_exhausted
    halted_cyc = await uc.execute(
        org.id,
        task_cyc.id,
        options={
            "test_command": "echo ok",
            "force_review_critical": True,
            "policy_override": {"large_diff_lines_threshold": 500},
        },
    )
    await db_session.commit()
    assert halted_cyc.status == "failed"
    cyc_run = await task_run_repo.get_latest_by_task(org.id, task_cyc.id)
    assert cyc_run.failure_reason == "review_cycle_limit_exhausted"

    # 3. budget_exceeded preserves non-empty partial_diff in GET /tasks/{id}
    halted_bdg = await uc.execute(
        org.id,
        task_bdg.id,
        options={
            "test_command": "echo ok",
            "target_file": "src/partial_target.py",
            "policy_override": {"max_task_cost_cents": 1},
            "simulated_prompt_tokens": 50000,
            "simulated_completion_tokens": 10000,
        },
    )
    await db_session.commit()
    assert halted_bdg.status == "failed"

    bdg_res = await client.get(
        f"/api/v1/tasks/{task_bdg.id}",
        headers=_auth_headers(org.clerk_org_id, org_role="org:member"),
    )
    assert bdg_res.status_code == 200
    partial_diff = bdg_res.json()["budget_summary"]["partial_diff"]
    assert isinstance(partial_diff, str)
    assert "src/partial_target.py" in partial_diff
    assert "+def solution():" in partial_diff
