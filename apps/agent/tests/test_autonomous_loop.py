"""Integration tests for autonomous engineer & reviewer loop (AC-1..5).

Critical test scenarios from spec 0004:
1. Happy path: Webhook triggers task, baseline passes, PR opens.
2. Loop iteration & fix: Reviewer blocks cycle 1, fixed cycle 2, PR opens.
3. Broken baseline abort: Base branch fails tests, aborts without cycles.
4. Cycle limit exhaustion: 3 cycles fail review, halts without PR.
5. Command timeout: Runaway script exceeds timeout in sandbox.
"""

import uuid

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.application.use_cases.run_autonomous_loop import (
    RunAutonomousLoopUseCase,
)
from app.infrastructure.db.repositories.audit_log_repository import (
    SqlAlchemyAuditLogRepository,
)
from app.infrastructure.db.repositories.organization_repository import (
    SqlAlchemyOrganizationRepository,
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
from app.infrastructure.db.repositories.task_repository import (
    SqlAlchemyTaskRepository,
)
from app.infrastructure.db.repositories.task_run_repository import (
    SqlAlchemyTaskRunRepository,
)
from app.infrastructure.events.redis_streamer import InMemoryOrRedisEventStreamer
from app.infrastructure.github.github_service import GitHubService
from app.infrastructure.llm.agents import ForgeCoderAgent, ReviewerCriticAgent
from app.infrastructure.sandbox.mock_sandbox import (
    MockSandboxProvider,
    MockSandboxSession,
)


@pytest.fixture
def autonomous_loop_use_case(db_session: AsyncSession):
    event_streamer = InMemoryOrRedisEventStreamer()
    use_case = RunAutonomousLoopUseCase(
        task_repo=SqlAlchemyTaskRepository(db_session),
        task_run_repo=SqlAlchemyTaskRunRepository(db_session),
        sandbox_run_repo=SqlAlchemySandboxRunRepository(db_session),
        review_iteration_repo=SqlAlchemyReviewIterationRepository(db_session),
        audit_log_repo=SqlAlchemyAuditLogRepository(db_session),
        repository_repo=SqlAlchemyRepositoryRepository(db_session),
        sandbox_provider=MockSandboxProvider(),
        github_gateway=GitHubService(),
        forge_agent=ForgeCoderAgent(),
        reviewer_critic=ReviewerCriticAgent(),
        event_streamer=event_streamer,
    )
    return use_case, event_streamer


@pytest.mark.asyncio
async def test_autonomous_loop_happy_path(
    db_session: AsyncSession, autonomous_loop_use_case
):
    """Scenario 1: Happy path - baseline passes, review approved, PR opened."""
    use_case, streamer = autonomous_loop_use_case
    org_repo = SqlAlchemyOrganizationRepository(db_session)
    repo_repo = SqlAlchemyRepositoryRepository(db_session)
    task_repo = SqlAlchemyTaskRepository(db_session)

    org = await org_repo.create_or_update(
        clerk_org_id=f"org_{uuid.uuid4().hex[:12]}",
        name="Tracer Bullet Org",
        slug=f"tb-org-{uuid.uuid4().hex[:8]}",
    )
    repo = await repo_repo.create(
        org_id=org.id,
        github_repo_id=11223344,
        github_installation_id=1001,
        name="agentsonair-core",
        full_name="agentsonair/agentsonair-core",
        default_branch="main",
    )
    task = await task_repo.create_task(
        org_id=org.id,
        repo_id=repo.id,
        title="Add user caching",
        description="Cache user lookups in redis",
        trigger_type="webhook_issue",
        trigger_metadata={"issue_number": 42},
        base_branch="main",
        branch_name="agentsonair/task-tb001-issue-42",
    )
    await db_session.commit()

    # Execute autonomous loop with a passing test command
    completed_task = await use_case.execute(
        org_id=org.id,
        task_id=task.id,
        options={
            "test_command": "echo 'All 5 tests passed'",
            "target_file": "src/cache.py",
        },
    )

    # Invariants verification
    assert completed_task.status == "completed"
    assert completed_task.pr_review_status == "approved"
    assert completed_task.pr_url is not None
    assert (
        "https://github.com/agentsonair/agentsonair-core/pull/" in completed_task.pr_url
    )
    assert completed_task.pr_number is not None
    assert completed_task.head_commit_sha is not None
    assert len(completed_task.head_commit_sha) == 40
    assert completed_task.branch_name == "agentsonair/task-tb001-issue-42"

    # Review iterations verification
    stmt = (
        "SELECT id, cycle_number, verdict, blocking_count "
        "FROM review_iterations WHERE org_id = :oid"
    )
    from sqlalchemy import text

    rev_rows = (await db_session.execute(text(stmt), {"oid": org.id})).fetchall()
    assert len(rev_rows) == 1
    assert rev_rows[0][1] == 1  # cycle_number
    assert rev_rows[0][2] == "approved"  # verdict
    assert rev_rows[0][3] == 0  # blocking_count

    # Telemetry verification: verify Redis/in-memory streamer captured events
    event_types = [e["type"] for e in streamer.events]
    assert "workspace_init_started" in event_types
    assert "baseline_test_completed" in event_types
    assert "tool_write_file" in event_types
    assert "tool_run_test_completed" in event_types


@pytest.mark.asyncio
async def test_autonomous_loop_iteration_repair_on_cycle_2(
    db_session: AsyncSession, autonomous_loop_use_case
):
    """Scenario 2: Loop iteration & fix - Reviewer blocks c1, fixed c2 (AC-2..5)."""
    use_case, _ = autonomous_loop_use_case
    org_repo = SqlAlchemyOrganizationRepository(db_session)
    repo_repo = SqlAlchemyRepositoryRepository(db_session)
    task_repo = SqlAlchemyTaskRepository(db_session)

    org = await org_repo.create_or_update(
        clerk_org_id=f"org_{uuid.uuid4().hex[:12]}",
        name="Repair Loop Org",
        slug=f"rep-org-{uuid.uuid4().hex[:8]}",
    )
    repo = await repo_repo.create(
        org_id=org.id,
        github_repo_id=55667788,
        github_installation_id=1002,
        name="payments-service",
        full_name="agentsonair/payments-service",
    )
    task = await task_repo.create_task(
        org_id=org.id,
        repo_id=repo.id,
        title="Fix refund calculation",
        description="Account for prorated discounts on partial refunds",
        trigger_type="webhook_issue",
        trigger_metadata={"issue_number": 77},
    )
    await db_session.commit()

    completed_task = await use_case.execute(
        org_id=org.id,
        task_id=task.id,
        options={
            "test_command": "echo 'Pass'",
            "target_file": "src/refunds.py",
            "force_review_critical": True,
            "clear_critical_on_cycle_2": True,
        },
    )

    assert completed_task.status == "completed"
    assert completed_task.pr_review_status == "approved"
    assert completed_task.pr_url is not None

    # Verify 2 review iterations exist: cycle 1 changes_requested, cycle 2 approved
    from sqlalchemy import text

    rev_rows = (
        await db_session.execute(
            text(
                "SELECT cycle_number, verdict, blocking_count "
                "FROM review_iterations WHERE org_id = :oid ORDER BY cycle_number"
            ),
            {"oid": org.id},
        )
    ).fetchall()

    assert len(rev_rows) == 2
    assert rev_rows[0][0] == 1
    assert rev_rows[0][1] == "changes_requested"
    assert rev_rows[0][2] == 1  # blocking_count
    assert rev_rows[1][0] == 2
    assert rev_rows[1][1] == "approved"
    assert rev_rows[1][2] == 0


@pytest.mark.asyncio
async def test_autonomous_loop_broken_baseline_aborts_immediately(
    db_session: AsyncSession, autonomous_loop_use_case
):
    """Scenario 3: Broken baseline abort - Base fails, aborts without cycles."""
    use_case, _ = autonomous_loop_use_case
    org_repo = SqlAlchemyOrganizationRepository(db_session)
    repo_repo = SqlAlchemyRepositoryRepository(db_session)
    task_repo = SqlAlchemyTaskRepository(db_session)

    org = await org_repo.create_or_update(
        clerk_org_id=f"org_{uuid.uuid4().hex[:12]}",
        name="Baseline Fail Org",
        slug=f"bf-org-{uuid.uuid4().hex[:8]}",
    )
    repo = await repo_repo.create(
        org_id=org.id,
        github_repo_id=99001122,
        github_installation_id=1003,
        name="broken-base-repo",
        full_name="agentsonair/broken-base-repo",
    )
    task = await task_repo.create_task(
        org_id=org.id,
        repo_id=repo.id,
        title="Add analytics hook",
        description="Log page views",
        trigger_type="webhook_issue",
        trigger_metadata={"issue_number": 88},
    )
    await db_session.commit()

    failed_task = await use_case.execute(
        org_id=org.id,
        task_id=task.id,
        options={
            "test_command": "exit 1",  # Command that returns non-zero exit code
        },
    )

    assert failed_task.status == "failed"
    assert failed_task.pr_url is None

    # Check that NO review iterations were run (no cycles wasted!)
    from sqlalchemy import text

    rev_count = (
        await db_session.execute(
            text("SELECT count(*) FROM review_iterations WHERE org_id = :oid"),
            {"oid": org.id},
        )
    ).scalar()
    assert rev_count == 0

    # Verify audit log recorded baseline failure
    audit_rows = (
        await db_session.execute(
            text(
                "SELECT action, payload_after FROM audit_logs "
                "WHERE org_id = :oid AND action = 'task_failed_baseline'"
            ),
            {"oid": org.id},
        )
    ).fetchall()
    assert len(audit_rows) == 1
    assert audit_rows[0][1]["reason"] == "baseline_tests_failed"


@pytest.mark.asyncio
async def test_autonomous_loop_cycle_limit_exhausted(
    db_session: AsyncSession, autonomous_loop_use_case
):
    """Scenario 4: Cycle limit exhaustion - 3 cycles fail, halts without PR."""
    use_case, _ = autonomous_loop_use_case
    org_repo = SqlAlchemyOrganizationRepository(db_session)
    repo_repo = SqlAlchemyRepositoryRepository(db_session)
    task_repo = SqlAlchemyTaskRepository(db_session)

    org = await org_repo.create_or_update(
        clerk_org_id=f"org_{uuid.uuid4().hex[:12]}",
        name="Exhaustion Org",
        slug=f"ex-org-{uuid.uuid4().hex[:8]}",
    )
    repo = await repo_repo.create(
        org_id=org.id,
        github_repo_id=33445566,
        github_installation_id=1004,
        name="strict-review-repo",
        full_name="agentsonair/strict-review-repo",
    )
    task = await task_repo.create_task(
        org_id=org.id,
        repo_id=repo.id,
        title="Implement OAuth provider",
        description="Add custom OAuth flow",
        trigger_type="webhook_issue",
        trigger_metadata={"issue_number": 99},
    )
    await db_session.commit()

    failed_task = await use_case.execute(
        org_id=org.id,
        task_id=task.id,
        options={
            "test_command": "echo 'Tests ok'",
            "force_review_critical": True,  # Keep critical across all 3 cycles
        },
    )

    assert failed_task.status == "failed"
    assert failed_task.pr_url is None

    # Exactly 3 review iterations should be recorded
    from sqlalchemy import text

    rev_rows = (
        await db_session.execute(
            text(
                "SELECT cycle_number, verdict, blocking_count "
                "FROM review_iterations WHERE org_id = :oid ORDER BY cycle_number"
            ),
            {"oid": org.id},
        )
    ).fetchall()
    assert len(rev_rows) == 3
    assert [r[0] for r in rev_rows] == [1, 2, 3]
    assert all(r[1] == "changes_requested" for r in rev_rows)

    # Check task run failure reason
    run_row = (
        await db_session.execute(
            text("SELECT status, failure_reason FROM task_runs WHERE task_id = :tid"),
            {"tid": task.id},
        )
    ).fetchone()
    assert run_row is not None
    assert run_row[0] == "failed"
    assert run_row[1] == "review_cycle_limit_exhausted"


@pytest.mark.asyncio
async def test_sandbox_command_timeout():
    """Scenario 5: Command timeout - runaway shell command terminates code 124."""
    import tempfile

    temp_dir = tempfile.mkdtemp()
    session = MockSandboxSession("test_sbx", temp_dir)
    try:
        # Command sleep for 2 seconds with 0.2 second timeout
        result = await session.execute_command("sleep 2", timeout_seconds=0.2)
        assert result.exit_code == 124
        assert "timed out" in result.stderr
    finally:
        await session.terminate()
