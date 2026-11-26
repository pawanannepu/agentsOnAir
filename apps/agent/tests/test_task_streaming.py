"""Tests for live task streaming, Clerk auth, LangGraph interrupt, and ARQ watchdog."""

import asyncio
import gzip
import uuid
from datetime import UTC, datetime, timedelta

import jwt
import pytest
import pytest_asyncio
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from httpx import ASGITransport, AsyncClient
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool

from app.application.use_cases.run_autonomous_loop import RunAutonomousLoopUseCase
from app.core.config import settings
from app.infrastructure.db.models.audit_log import AuditLogModel
from app.infrastructure.db.models.organization import OrganizationModel
from app.infrastructure.db.models.repository import RepositoryModel
from app.infrastructure.db.models.sandbox_run import SandboxRunModel
from app.infrastructure.db.models.task import TaskModel
from app.infrastructure.db.models.task_run import TaskRunModel
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
from app.infrastructure.db.repositories.task_intervention_repository import (
    SqlAlchemyTaskInterventionRepository,
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
from app.infrastructure.db.session import get_db
from app.infrastructure.events.redis_streamer import (
    InMemoryOrRedisEventStreamer,
    get_event_streamer,
)
from app.infrastructure.github.github_service import GitHubService
from app.infrastructure.llm.agents import ForgeCoderAgent, ReviewerCriticAgent
from app.infrastructure.llm.task_graph import PostgresTaskCheckpointSaver
from app.infrastructure.queue.arq_queue import ArqTaskQueue
from app.infrastructure.queue.worker import handle_interruption_timeout
from app.infrastructure.sandbox.e2b_sandbox import E2BSandboxProvider
from app.infrastructure.sandbox.mock_sandbox import MockSandboxProvider
from app.infrastructure.sandbox.registry import SandboxRegistry, get_sandbox_registry
from app.main import app


@pytest.fixture(scope="module")
def rsa_keypair() -> tuple[bytes, str]:
    """Generate an ephemeral RS256 keypair for testing Clerk JWT verification."""
    private_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    private_pem = private_key.private_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PrivateFormat.PKCS8,
        encryption_algorithm=serialization.NoEncryption(),
    )
    public_pem = (
        private_key.public_key()
        .public_bytes(
            encoding=serialization.Encoding.PEM,
            format=serialization.PublicFormat.SubjectPublicKeyInfo,
        )
        .decode("utf-8")
    )
    return private_pem, public_pem


def _make_clerk_jwt(
    private_pem: bytes,
    *,
    user_id: str = "user_clerk_test_1",
    clerk_org_id: str | None = None,
    expired: bool = False,
) -> str:
    now = datetime.now(UTC)
    exp = now - timedelta(minutes=5) if expired else now + timedelta(minutes=15)
    payload: dict = {
        "sub": user_id,
        "iat": int(now.timestamp()),
        "exp": int(exp.timestamp()),
    }
    if clerk_org_id:
        payload["org_id"] = clerk_org_id
    return jwt.encode(payload, private_pem, algorithm="RS256")


@pytest.fixture(autouse=True)
def configure_clerk_test_key(rsa_keypair, monkeypatch):
    """Configure CLERK_JWT_KEY for all streaming endpoint tests."""
    _priv, pub = rsa_keypair
    monkeypatch.setattr(settings, "CLERK_JWT_KEY", pub)


@pytest_asyncio.fixture
async def sample_task(db_session: AsyncSession):
    """Seed test organization, repository, and task."""
    org_id = uuid.uuid4()
    repo_id = uuid.uuid4()
    task_id = uuid.uuid4()
    clerk_org_id = f"org_stream_{org_id.hex[:8]}"

    org = OrganizationModel(
        id=org_id,
        clerk_org_id=clerk_org_id,
        name="Streaming Org",
        slug=f"stream-{org_id.hex[:8]}",
    )
    db_session.add(org)

    repo = RepositoryModel(
        id=repo_id,
        org_id=org_id,
        github_repo_id=123456,
        github_installation_id=654321,
        name="stream-repo",
        full_name="org/stream-repo",
    )
    db_session.add(repo)

    task = TaskModel(
        id=task_id,
        org_id=org_id,
        repo_id=repo_id,
        title="Live streaming task",
        description="Verify SSE and human collaboration",
        status="in_progress",
        trigger_type="manual_console",
    )
    db_session.add(task)
    await db_session.commit()

    return {
        "org_id": org_id,
        "clerk_org_id": clerk_org_id,
        "repo_id": repo_id,
        "task_id": task_id,
    }


@pytest.mark.asyncio
async def test_sse_events_and_cursor_replay(client, sample_task, rsa_keypair):
    priv, _pub = rsa_keypair
    org_id = sample_task["org_id"]
    task_id = sample_task["task_id"]
    token = _make_clerk_jwt(priv, clerk_org_id=sample_task["clerk_org_id"])
    auth_headers = {"Authorization": f"Bearer {token}"}
    streamer = get_event_streamer()

    eid1 = await streamer.append_event(
        task_id, "task.log", {"stream": "stdout", "chunk": "Line 1\n"}
    )
    eid2 = await streamer.append_event(
        task_id, "task.log", {"stream": "stdout", "chunk": "Line 2\n"}
    )
    eid3 = await streamer.append_event(
        task_id, "task.step", {"node": "forge", "status": "running"}
    )

    # 1. Stream events from cursor 0-0
    async with client.stream(
        "GET",
        f"/api/v1/tasks/{task_id}/events",
        params={"org_id": str(org_id), "follow": "false"},
        headers=auth_headers,
    ) as response:
        assert response.status_code == 200
        assert "text/event-stream" in response.headers["content-type"]
        lines = []
        async for line in response.aiter_lines():
            lines.append(line)

        body = "\n".join(lines)
        assert f"id: {eid1}" in body
        assert f"id: {eid2}" in body
        assert f"id: {eid3}" in body
        assert "event: task.log" in body
        assert "Line 1" in body

    # 2. Reconnect with Last-Event-ID = eid2, expect only eid3
    async with client.stream(
        "GET",
        f"/api/v1/tasks/{task_id}/events",
        params={"org_id": str(org_id), "follow": "false"},
        headers={**auth_headers, "Last-Event-ID": eid2},
    ) as reconnect_resp:
        assert reconnect_resp.status_code == 200
        reconnect_lines = []
        async for line in reconnect_resp.aiter_lines():
            reconnect_lines.append(line)

        reconnect_body = "\n".join(reconnect_lines)
        assert f"id: {eid1}" not in reconnect_body
        assert f"id: {eid2}" not in reconnect_body
        assert f"id: {eid3}" in reconnect_body


@pytest.mark.asyncio
async def test_clerk_auth_and_tenant_isolation(
    client, sample_task, db_session, rsa_keypair
):
    priv, _pub = rsa_keypair
    task_id = sample_task["task_id"]

    # 1. Missing token -> 401
    unauth = await client.get(f"/api/v1/tasks/{task_id}/transcript")
    assert unauth.status_code == 401

    # 2. Expired token -> 401
    expired_tok = _make_clerk_jwt(
        priv, clerk_org_id=sample_task["clerk_org_id"], expired=True
    )
    exp_resp = await client.post(
        f"/api/v1/tasks/{task_id}/intervene",
        headers={"Authorization": f"Bearer {expired_tok}"},
        json={"message": "hello", "action_type": "guidance"},
    )
    assert exp_resp.status_code == 401

    # 3. Other organization -> 403 Forbidden
    other_org = OrganizationModel(
        id=uuid.uuid4(),
        clerk_org_id=f"org_other_{uuid.uuid4().hex[:8]}",
        name="Other Org",
        slug=f"other-{uuid.uuid4().hex[:8]}",
    )
    db_session.add(other_org)
    await db_session.commit()

    other_tok = _make_clerk_jwt(priv, clerk_org_id=other_org.clerk_org_id)
    cross_resp = await client.get(
        f"/api/v1/tasks/{task_id}/transcript",
        headers={"Authorization": f"Bearer {other_tok}"},
    )
    assert cross_resp.status_code == 403


@pytest.mark.asyncio
async def test_task_interventions_and_concurrency(
    client, sample_task, db_session, rsa_keypair
):
    priv, _pub = rsa_keypair
    org_id = sample_task["org_id"]
    task_id = sample_task["task_id"]
    token = _make_clerk_jwt(
        priv, user_id="user_collab_1", clerk_org_id=sample_task["clerk_org_id"]
    )
    headers = {"Authorization": f"Bearer {token}"}

    # 1. Submit guidance intervention
    guidance_resp = await client.post(
        f"/api/v1/tasks/{task_id}/intervene",
        params={"org_id": str(org_id)},
        headers=headers,
        json={"message": "Please prioritize safety checks", "action_type": "guidance"},
    )
    assert guidance_resp.status_code == 200
    data = guidance_resp.json()
    assert data["status"] == "queued"
    intervention_id = uuid.UUID(data["intervention_id"])

    intervention_repo = SqlAlchemyTaskInterventionRepository(db_session)
    interventions = await intervention_repo.list_by_task(org_id, task_id)
    assert len(interventions) == 1
    assert interventions[0].id == intervention_id
    assert interventions[0].clerk_user_id == "user_collab_1"
    assert interventions[0].payload["message"] == "Please prioritize safety checks"

    # 2. Put task into awaiting_input state
    task_repo = SqlAlchemyTaskRepository(db_session)
    await task_repo.set_interruption(
        org_id,
        task_id,
        prompt="Which ORM to use?",
        options=["SQLAlchemy", "Tortoise"],
    )

    task_obj = await task_repo.get_by_id(org_id, task_id)
    assert task_obj.status == "awaiting_input"
    assert task_obj.interruption_prompt == "Which ORM to use?"

    # 3. Respond to interruption
    respond_resp = await client.post(
        f"/api/v1/tasks/{task_id}/respond",
        params={"org_id": str(org_id)},
        headers=headers,
        json={"response": "SQLAlchemy", "selected_option": "SQLAlchemy"},
    )
    assert respond_resp.status_code == 200
    assert respond_resp.json()["status"] == "accepted"

    updated_task = await task_repo.get_by_id(org_id, task_id)
    assert updated_task.status == "in_progress"
    assert updated_task.interruption_prompt is None

    # 4. Duplicate respond attempt returns 409 Conflict
    conflict_resp = await client.post(
        f"/api/v1/tasks/{task_id}/respond",
        params={"org_id": str(org_id)},
        headers=headers,
        json={"response": "Tortoise"},
    )
    assert conflict_resp.status_code == 409


@pytest.mark.asyncio
async def test_concurrent_respond_race_returns_200_and_409(rsa_keypair):
    """Regression test: two simultaneous POST /respond requests return 200 and 409."""
    priv, _pub = rsa_keypair
    org_id = uuid.uuid4()
    repo_id = uuid.uuid4()
    task_id = uuid.uuid4()
    clerk_org_id = f"org_race_{org_id.hex[:8]}"
    token = _make_clerk_jwt(priv, user_id="user_race", clerk_org_id=clerk_org_id)
    headers = {"Authorization": f"Bearer {token}"}

    engine = create_async_engine(settings.DATABASE_URL, poolclass=NullPool)
    local_factory = async_sessionmaker(
        bind=engine,
        class_=AsyncSession,
        expire_on_commit=False,
        autocommit=False,
        autoflush=False,
    )

    async def override_get_db():
        async with local_factory() as s:
            try:
                yield s
                await s.commit()
            except Exception:
                await s.rollback()
                raise

    async with local_factory() as db:
        db.add(
            OrganizationModel(
                id=org_id,
                clerk_org_id=clerk_org_id,
                name="Race Org",
                slug=f"race-{org_id.hex[:8]}",
            )
        )
        db.add(
            RepositoryModel(
                id=repo_id,
                org_id=org_id,
                github_repo_id=int(org_id.int % 100000000),
                github_installation_id=999,
                name="race-repo",
                full_name="org/race-repo",
            )
        )
        db.add(
            TaskModel(
                id=task_id,
                org_id=org_id,
                repo_id=repo_id,
                title="Concurrent respond race",
                description="Ensure FOR UPDATE prevents double claim",
                status="awaiting_input",
                trigger_type="manual_console",
                interruption_prompt="PostgreSQL or SQLite?",
            )
        )
        await db.commit()

    app.dependency_overrides[get_db] = override_get_db
    try:
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as ac:
            r1, r2 = await asyncio.gather(
                ac.post(
                    f"/api/v1/tasks/{task_id}/respond",
                    headers=headers,
                    json={"response": "PostgreSQL"},
                ),
                ac.post(
                    f"/api/v1/tasks/{task_id}/respond",
                    headers=headers,
                    json={"response": "SQLite"},
                ),
            )
            assert sorted([r1.status_code, r2.status_code]) == [200, 409]
    finally:
        app.dependency_overrides.clear()
        async with local_factory() as db:
            await db.execute(delete(TaskModel).where(TaskModel.id == task_id))
            await db.execute(
                delete(RepositoryModel).where(RepositoryModel.id == repo_id)
            )
            await db.commit()
        await engine.dispose()


@pytest.mark.asyncio
async def test_task_abort_action(client, sample_task, db_session, rsa_keypair):
    priv, _pub = rsa_keypair
    org_id = sample_task["org_id"]
    task_id = sample_task["task_id"]
    token = _make_clerk_jwt(priv, clerk_org_id=sample_task["clerk_org_id"])
    headers = {"Authorization": f"Bearer {token}"}

    abort_resp = await client.post(
        f"/api/v1/tasks/{task_id}/abort",
        params={"org_id": str(org_id)},
        headers=headers,
        json={"reason": "Operator requested cancellation"},
    )
    assert abort_resp.status_code == 200
    assert abort_resp.json()["status"] == "cancelled"

    task_repo = SqlAlchemyTaskRepository(db_session)
    aborted_task = await task_repo.get_by_id(org_id, task_id)
    assert aborted_task.status == "cancelled"

    dup_abort = await client.post(
        f"/api/v1/tasks/{task_id}/abort",
        params={"org_id": str(org_id)},
        headers=headers,
        json={"reason": "Repeat"},
    )
    assert dup_abort.status_code == 409


@pytest.mark.asyncio
async def test_langgraph_interrupt_resume_and_watchdog_timeout(
    db_session: AsyncSession,
):
    """Verify LangGraph interrupt, E2B timeout extension, ARQ watchdog, and resume."""
    org_repo = SqlAlchemyOrganizationRepository(db_session)
    repo_repo = SqlAlchemyRepositoryRepository(db_session)
    task_repo = SqlAlchemyTaskRepository(db_session)
    task_run_repo = SqlAlchemyTaskRunRepository(db_session)
    sandbox_run_repo = SqlAlchemySandboxRunRepository(db_session)
    review_repo = SqlAlchemyReviewIterationRepository(db_session)
    audit_repo = SqlAlchemyAuditLogRepository(db_session)
    transcript_repo = SqlAlchemyTaskTranscriptRepository(db_session)
    intervention_repo = SqlAlchemyTaskInterventionRepository(db_session)

    org = await org_repo.create_or_update(
        clerk_org_id=f"org_lg_{uuid.uuid4().hex[:8]}",
        name="LangGraph Org",
        slug=f"lg-{uuid.uuid4().hex[:8]}",
    )
    repo = await repo_repo.create(
        org_id=org.id,
        github_repo_id=int(uuid.uuid4().int % 100000000),
        github_installation_id=4444,
        name="lg-repo",
        full_name="org/lg-repo",
    )
    task = await task_repo.create_task(
        org_id=org.id,
        repo_id=repo.id,
        title="Add DB migration",
        description="Support database migration",
        trigger_type="manual_console",
    )
    await db_session.commit()

    streamer = InMemoryOrRedisEventStreamer()
    task_queue = ArqTaskQueue()
    sandbox_registry = SandboxRegistry()

    use_case = RunAutonomousLoopUseCase(
        task_repo=task_repo,
        task_run_repo=task_run_repo,
        sandbox_run_repo=sandbox_run_repo,
        review_iteration_repo=review_repo,
        audit_log_repo=audit_repo,
        repository_repo=repo_repo,
        sandbox_provider=E2BSandboxProvider(),
        github_gateway=GitHubService(),
        forge_agent=ForgeCoderAgent(),
        reviewer_critic=ReviewerCriticAgent(),
        event_streamer=streamer,
        task_transcript_repo=transcript_repo,
        task_intervention_repo=intervention_repo,
        task_queue=task_queue,
        sandbox_registry=sandbox_registry,
    )

    # 1. Execute hits LangGraph clarification interrupt and releases worker
    paused_task = await use_case.execute(
        org.id,
        task.id,
        options={
            "test_command": "echo 'ok'",
            "simulate_clarification": True,
            "clarification_prompt": "PostgreSQL or SQLite?",
            "clarification_options": ["PostgreSQL", "SQLite"],
        },
    )
    assert paused_task.status == "awaiting_input"
    assert paused_task.interruption_prompt == "PostgreSQL or SQLite?"

    # Sandbox timeout extended to 900s and kept alive in registry
    run = await task_run_repo.get_latest_by_task(org.id, task.id)
    assert run.status == "awaiting_input"
    assert "langgraph" in run.checkpoint_state
    sbx_run = await sandbox_run_repo.get_by_task_run_id(org.id, run.id)
    assert sbx_run.timeout_seconds == 900
    assert sbx_run.status == "active"
    assert sandbox_registry.get(sbx_run.sandbox_id) is not None

    # Delayed ARQ watchdog job scheduled for 900s
    watchdog_jobs = [
        j
        for j in task_queue.scheduled_jobs
        if j.job_name == "interruption_timeout_watchdog"
    ]
    assert len(watchdog_jobs) == 1
    assert watchdog_jobs[0].defer_by_seconds == 900

    # 2. Resume from persisted PostgreSQL LangGraph checkpoint in new instance
    resume_use_case = RunAutonomousLoopUseCase(
        task_repo=task_repo,
        task_run_repo=task_run_repo,
        sandbox_run_repo=sandbox_run_repo,
        review_iteration_repo=review_repo,
        audit_log_repo=audit_repo,
        repository_repo=repo_repo,
        sandbox_provider=E2BSandboxProvider(),
        github_gateway=GitHubService(),
        forge_agent=ForgeCoderAgent(),
        reviewer_critic=ReviewerCriticAgent(),
        event_streamer=streamer,
        task_transcript_repo=transcript_repo,
        task_intervention_repo=intervention_repo,
        task_queue=task_queue,
        sandbox_registry=sandbox_registry,
    )
    completed = await resume_use_case.resume(
        org_id=org.id,
        task_id=task.id,
        response="PostgreSQL",
    )
    assert completed.status == "completed"
    assert completed.pr_url is not None

    # 3. Also test watchdog expiration path on a second awaiting_input task
    task2 = await task_repo.create_task(
        org_id=org.id,
        repo_id=repo.id,
        title="Timeout test task",
        description="Expires if unanswered",
        trigger_type="manual_console",
    )
    await db_session.commit()

    paused2 = await use_case.execute(
        org.id,
        task2.id,
        options={"test_command": "echo 'ok'", "simulate_clarification": True},
    )
    assert paused2.status == "awaiting_input"
    run2 = await task_run_repo.get_latest_by_task(org.id, task2.id)
    sbx2 = await sandbox_run_repo.get_by_task_run_id(org.id, run2.id)

    expired = await handle_interruption_timeout(
        db_session,
        org.id,
        task2.id,
        event_streamer=streamer,
        sandbox_registry=sandbox_registry,
    )
    assert expired is True

    failed_task2 = await task_repo.get_by_id(org.id, task2.id)
    assert failed_task2.status == "failed"

    sbx2_after = (
        await db_session.execute(
            select(SandboxRunModel).where(SandboxRunModel.id == sbx2.id)
        )
    ).scalar_one()
    assert sbx2_after.status == "terminated"

    audit_row = (
        await db_session.execute(
            select(AuditLogModel).where(
                AuditLogModel.target_id == task2.id,
                AuditLogModel.action == "task_interruption_expired",
            )
        )
    ).scalar_one_or_none()
    assert audit_row is not None


@pytest.mark.asyncio
async def test_transcript_archival_and_compression(
    client, sample_task, db_session, rsa_keypair
):
    priv, _pub = rsa_keypair
    org_id = sample_task["org_id"]
    task_id = sample_task["task_id"]
    token = _make_clerk_jwt(priv, clerk_org_id=sample_task["clerk_org_id"])
    headers = {"Authorization": f"Bearer {token}"}
    streamer = get_event_streamer()

    await streamer.append_event(
        task_id, "task.log", {"stream": "stdout", "chunk": "echo 'build success'\n"}
    )

    # 1. In flight fallback query
    in_flight_resp = await client.get(
        f"/api/v1/tasks/{task_id}/transcript",
        params={"org_id": str(org_id)},
        headers=headers,
    )
    assert in_flight_resp.status_code == 200
    transcript_data = in_flight_resp.json()
    assert "build success" in transcript_data["terminal_log"]

    # 2. Archive to task_transcripts table with gzip compression
    run_id = uuid.uuid4()
    run = TaskRunModel(
        id=run_id,
        org_id=org_id,
        task_id=task_id,
        run_number=1,
        status="completed",
    )
    db_session.add(run)
    await db_session.commit()

    compressed_log = gzip.compress(b"Compressed archive output\nLine 2\n")
    transcript_repo = SqlAlchemyTaskTranscriptRepository(db_session)
    await transcript_repo.create_or_update(
        org_id=org_id,
        task_id=task_id,
        task_run_id=run_id,
        terminal_log=compressed_log,
        events_json=[{"type": "archived"}],
        total_lines=2,
    )
    await db_session.commit()

    completed_resp = await client.get(
        f"/api/v1/tasks/{task_id}/transcript",
        params={"org_id": str(org_id), "run_id": str(run_id)},
        headers=headers,
    )
    assert completed_resp.status_code == 200
    comp_data = completed_resp.json()
    assert comp_data["terminal_log"] == "Compressed archive output\nLine 2\n"
    assert comp_data["total_lines"] == 2


@pytest.mark.asyncio
async def test_redis_xread_block_does_not_timeout(caplog):
    """Ensure blocking XREAD (1000ms) completes without hitting Redis socket_timeout."""
    streamer = InMemoryOrRedisEventStreamer(redis_url=settings.REDIS_URL)
    client = await streamer._get_client()
    if client is None:
        pytest.skip("Redis not reachable in test environment")

    try:
        with caplog.at_level("WARNING"):
            events = await streamer.read_events(
                uuid.uuid4(),
                last_event_id="0-0",
                count=50,
                block_ms=1000,
            )
        assert events == []
        assert "Redis xread failed" not in caplog.text
    finally:
        await client.aclose()


@pytest.mark.asyncio
async def test_sse_events_terminal_task_drains_and_closes(
    client, sample_task, db_session, rsa_keypair
):
    """covers: AC-1 - Terminal tasks drain remaining stream events and close."""
    priv, _pub = rsa_keypair
    org_id = sample_task["org_id"]
    task_id = sample_task["task_id"]
    token = _make_clerk_jwt(priv, clerk_org_id=sample_task["clerk_org_id"])
    headers = {"Authorization": f"Bearer {token}"}
    streamer = get_event_streamer()

    eid1 = await streamer.append_event(
        task_id, "task.log", {"stream": "stdout", "chunk": "step 1\n"}
    )
    eid2 = await streamer.append_event(
        task_id, "task.log", {"stream": "stdout", "chunk": "step 2\n"}
    )

    task_repo = SqlAlchemyTaskRepository(db_session)
    await task_repo.update_status(org_id, task_id, status="completed")
    await db_session.commit()

    async with client.stream(
        "GET",
        f"/api/v1/tasks/{task_id}/events",
        params={"org_id": str(org_id)},
        headers={**headers, "Last-Event-ID": eid1},
    ) as response:
        assert response.status_code == 200
        lines = [line async for line in response.aiter_lines()]
        body = "\n".join(lines)
        assert f"id: {eid1}" not in body
        assert f"id: {eid2}" in body
        assert "event: task.status" in body
        assert '"status": "completed"' in body


@pytest.mark.asyncio
async def test_sse_events_live_terminal_status_closes_stream(
    client, sample_task, rsa_keypair
):
    """covers: AC-1 - Live follow=true stream closes on terminal task.status."""
    priv, _pub = rsa_keypair
    org_id = sample_task["org_id"]
    task_id = sample_task["task_id"]
    token = _make_clerk_jwt(priv, clerk_org_id=sample_task["clerk_org_id"])
    streamer = get_event_streamer()

    async def publish_later():
        await asyncio.sleep(0.05)
        await streamer.append_event(
            task_id, "task.log", {"stream": "stdout", "chunk": "finishing up\n"}
        )
        await streamer.append_event(
            task_id,
            "task.status",
            {"status": "completed", "pr_url": "https://github.com/org/repo/pull/1"},
        )

    publisher = asyncio.create_task(publish_later())
    try:
        async with client.stream(
            "GET",
            f"/api/v1/tasks/{task_id}/events",
            params={"org_id": str(org_id), "follow": "true"},
            headers={"Authorization": f"Bearer {token}"},
        ) as response:
            assert response.status_code == 200
            lines = [line async for line in response.aiter_lines()]
            body = "\n".join(lines)
            assert "finishing up" in body
            assert "event: task.status" in body
            assert '"status": "completed"' in body
    finally:
        await publisher


@pytest.mark.asyncio
async def test_sse_events_rejects_other_org_and_missing_task(
    client, sample_task, db_session, rsa_keypair
):
    """covers: AC-1 - SSE endpoint enforces org isolation (403) and missing (404)."""
    priv, _pub = rsa_keypair
    task_id = sample_task["task_id"]

    other_org = OrganizationModel(
        id=uuid.uuid4(),
        clerk_org_id=f"org_sse_other_{uuid.uuid4().hex[:8]}",
        name="Other SSE Org",
        slug=f"sse-other-{uuid.uuid4().hex[:8]}",
    )
    db_session.add(other_org)
    await db_session.commit()

    other_token = _make_clerk_jwt(priv, clerk_org_id=other_org.clerk_org_id)
    forbidden = await client.get(
        f"/api/v1/tasks/{task_id}/events",
        headers={"Authorization": f"Bearer {other_token}"},
    )
    assert forbidden.status_code == 403

    own_token = _make_clerk_jwt(priv, clerk_org_id=sample_task["clerk_org_id"])
    missing = await client.get(
        f"/api/v1/tasks/{uuid.uuid4()}/events",
        headers={"Authorization": f"Bearer {own_token}"},
    )
    assert missing.status_code == 404


@pytest.mark.asyncio
async def test_get_task_exposes_interruption_metadata(
    client, sample_task, db_session, rsa_keypair
):
    """covers: AC-2, AC-3 - GET /tasks/{id} returns interruption prompt and options."""
    priv, _pub = rsa_keypair
    org_id = sample_task["org_id"]
    task_id = sample_task["task_id"]
    token = _make_clerk_jwt(priv, clerk_org_id=sample_task["clerk_org_id"])

    expires_at = datetime.now(UTC) + timedelta(minutes=15)
    task_repo = SqlAlchemyTaskRepository(db_session)
    await task_repo.set_interruption(
        org_id,
        task_id,
        prompt="Use Redis Streams or PubSub?",
        interruption_type="clarification",
        options=["Redis Streams", "PubSub"],
        expires_at=expires_at,
    )
    await db_session.commit()

    resp = await client.get(
        f"/api/v1/tasks/{task_id}",
        params={"org_id": str(org_id)},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "awaiting_input"
    assert body["interruption_prompt"] == "Use Redis Streams or PubSub?"
    assert body["interruption_type"] == "clarification"
    assert body["interruption_options"] == ["Redis Streams", "PubSub"]
    assert body["interruption_expires_at"] is not None


@pytest.mark.asyncio
async def test_intervene_rejects_terminal_task_and_invalid_payload(
    client, sample_task, db_session, rsa_keypair
):
    """covers: AC-3 - /intervene returns 409 on terminal tasks and 422 on bad body."""
    priv, _pub = rsa_keypair
    org_id = sample_task["org_id"]
    task_id = sample_task["task_id"]
    token = _make_clerk_jwt(priv, clerk_org_id=sample_task["clerk_org_id"])
    headers = {"Authorization": f"Bearer {token}"}

    bad_action = await client.post(
        f"/api/v1/tasks/{task_id}/intervene",
        params={"org_id": str(org_id)},
        headers=headers,
        json={"message": "ignore tests", "action_type": "invalid_action"},
    )
    assert bad_action.status_code == 422

    empty_msg = await client.post(
        f"/api/v1/tasks/{task_id}/intervene",
        params={"org_id": str(org_id)},
        headers=headers,
        json={"message": "", "action_type": "guidance"},
    )
    assert empty_msg.status_code == 422

    task_repo = SqlAlchemyTaskRepository(db_session)
    await task_repo.update_status(org_id, task_id, status="completed")
    await db_session.commit()

    terminal_resp = await client.post(
        f"/api/v1/tasks/{task_id}/intervene",
        params={"org_id": str(org_id)},
        headers=headers,
        json={"message": "too late", "action_type": "guidance"},
    )
    assert terminal_resp.status_code == 409


@pytest.mark.asyncio
async def test_respond_rejects_non_awaiting_task_and_empty_response(
    client, sample_task, rsa_keypair
):
    """covers: AC-3 - /respond returns 409 when active and 422 when response empty."""
    priv, _pub = rsa_keypair
    org_id = sample_task["org_id"]
    task_id = sample_task["task_id"]
    token = _make_clerk_jwt(priv, clerk_org_id=sample_task["clerk_org_id"])
    headers = {"Authorization": f"Bearer {token}"}

    empty_resp = await client.post(
        f"/api/v1/tasks/{task_id}/respond",
        params={"org_id": str(org_id)},
        headers=headers,
        json={"response": ""},
    )
    assert empty_resp.status_code == 422

    not_waiting = await client.post(
        f"/api/v1/tasks/{task_id}/respond",
        params={"org_id": str(org_id)},
        headers=headers,
        json={"response": "PostgreSQL"},
    )
    assert not_waiting.status_code == 409


@pytest.mark.asyncio
async def test_abort_awaiting_input_terminates_paused_sandbox_and_records_audit(
    client, sample_task, db_session, rsa_keypair
):
    """covers: AC-3, AC-5 - /abort terminates paused sandbox and logs audit/stream."""
    priv, _pub = rsa_keypair
    org_id = sample_task["org_id"]
    task_id = sample_task["task_id"]
    token = _make_clerk_jwt(
        priv, user_id="user_abort_op", clerk_org_id=sample_task["clerk_org_id"]
    )
    headers = {"Authorization": f"Bearer {token}"}

    task_repo = SqlAlchemyTaskRepository(db_session)
    await task_repo.set_interruption(
        org_id, task_id, prompt="Confirm target branch", options=["main"]
    )

    run = TaskRunModel(
        id=uuid.uuid4(),
        org_id=org_id,
        task_id=task_id,
        run_number=1,
        status="awaiting_input",
    )
    db_session.add(run)
    await db_session.flush()

    sandbox_session = await MockSandboxProvider().create_sandbox(org_id, task_id)
    registry = get_sandbox_registry()
    registry.register(sandbox_session.id, sandbox_session)

    sbx_model = SandboxRunModel(
        id=uuid.uuid4(),
        org_id=org_id,
        task_run_id=run.id,
        provider="mock",
        sandbox_id=sandbox_session.id,
        status="active",
    )
    db_session.add(sbx_model)
    await db_session.commit()

    resp = await client.post(
        f"/api/v1/tasks/{task_id}/abort",
        params={"org_id": str(org_id)},
        headers=headers,
        json={"reason": "Cancel paused task"},
    )
    assert resp.status_code == 200
    assert resp.json()["status"] == "cancelled"

    await db_session.refresh(sbx_model)
    assert sbx_model.status == "terminated"
    assert registry.get(sandbox_session.id) is None

    audit_row = (
        await db_session.execute(
            select(AuditLogModel).where(
                AuditLogModel.target_id == task_id,
                AuditLogModel.action == "task_aborted",
            )
        )
    ).scalar_one_or_none()
    assert audit_row is not None
    assert audit_row.actor_id == "user_abort_op"


@pytest.mark.asyncio
async def test_use_case_collects_and_marks_developer_guidance_applied(
    db_session: AsyncSession,
):
    """covers: AC-3 - Autonomous loop consumes unapplied guidance and marks applied."""
    org_repo = SqlAlchemyOrganizationRepository(db_session)
    repo_repo = SqlAlchemyRepositoryRepository(db_session)
    task_repo = SqlAlchemyTaskRepository(db_session)
    task_run_repo = SqlAlchemyTaskRunRepository(db_session)
    sandbox_run_repo = SqlAlchemySandboxRunRepository(db_session)
    review_repo = SqlAlchemyReviewIterationRepository(db_session)
    audit_repo = SqlAlchemyAuditLogRepository(db_session)
    transcript_repo = SqlAlchemyTaskTranscriptRepository(db_session)
    intervention_repo = SqlAlchemyTaskInterventionRepository(db_session)

    org = await org_repo.create_or_update(
        clerk_org_id=f"org_guide_{uuid.uuid4().hex[:8]}",
        name="Guidance Org",
        slug=f"guide-{uuid.uuid4().hex[:8]}",
    )
    repo = await repo_repo.create(
        org_id=org.id,
        github_repo_id=int(uuid.uuid4().int % 100000000),
        github_installation_id=7777,
        name="guide-repo",
        full_name="org/guide-repo",
    )
    task = await task_repo.create_task(
        org_id=org.id,
        repo_id=repo.id,
        title="Guidance consumption task",
        description="Verify guidance is passed once and marked applied",
        trigger_type="manual_console",
    )
    await intervention_repo.create(
        org_id=org.id,
        task_id=task.id,
        clerk_user_id="user_guide_1",
        intervention_type="guidance",
        payload={"message": "Use uv instead of pip"},
    )
    await db_session.commit()

    captured_guidance: list[list[str]] = []

    class CapturingForgeAgent(ForgeCoderAgent):
        async def run_cycle(self, task_context, previous_review, workspace):
            captured_guidance.append(list(task_context.get("guidance_messages", [])))
            return await super().run_cycle(task_context, previous_review, workspace)

    streamer = InMemoryOrRedisEventStreamer()
    use_case = RunAutonomousLoopUseCase(
        task_repo=task_repo,
        task_run_repo=task_run_repo,
        sandbox_run_repo=sandbox_run_repo,
        review_iteration_repo=review_repo,
        audit_log_repo=audit_repo,
        repository_repo=repo_repo,
        sandbox_provider=E2BSandboxProvider(),
        github_gateway=GitHubService(),
        forge_agent=CapturingForgeAgent(),
        reviewer_critic=ReviewerCriticAgent(),
        event_streamer=streamer,
        task_transcript_repo=transcript_repo,
        task_intervention_repo=intervention_repo,
    )

    completed = await use_case.execute(
        org.id,
        task.id,
        options={"test_command": "echo 'ok'"},
    )
    assert completed.status == "completed"
    assert captured_guidance == [["Use uv instead of pip"]]

    interventions = await intervention_repo.list_by_task(org.id, task.id)
    assert len(interventions) == 1
    assert interventions[0].applied_at is not None


@pytest.mark.asyncio
async def test_watchdog_skips_non_awaiting_and_stale_expiration_and_archives_transcript(
    db_session: AsyncSession,
):
    """covers: AC-4, AC-5 - Watchdog guards stale/active tasks and archives logs."""
    org_repo = SqlAlchemyOrganizationRepository(db_session)
    repo_repo = SqlAlchemyRepositoryRepository(db_session)
    task_repo = SqlAlchemyTaskRepository(db_session)
    task_run_repo = SqlAlchemyTaskRunRepository(db_session)
    transcript_repo = SqlAlchemyTaskTranscriptRepository(db_session)

    org = await org_repo.create_or_update(
        clerk_org_id=f"org_wd_{uuid.uuid4().hex[:8]}",
        name="Watchdog Org",
        slug=f"wd-{uuid.uuid4().hex[:8]}",
    )
    repo = await repo_repo.create(
        org_id=org.id,
        github_repo_id=int(uuid.uuid4().int % 100000000),
        github_installation_id=8888,
        name="wd-repo",
        full_name="org/wd-repo",
    )
    task = await task_repo.create_task(
        org_id=org.id,
        repo_id=repo.id,
        title="Watchdog guard test",
        description="Test non-awaiting and stale deadline checks",
        trigger_type="manual_console",
    )
    run = await task_run_repo.create_run(org.id, task.id)
    await db_session.commit()

    streamer = InMemoryOrRedisEventStreamer()
    await streamer.append_event(
        task.id, "task.log", {"stream": "stdout", "chunk": "before timeout\n"}
    )

    # 1. Task is still queued -> watchdog returns False
    assert (
        await handle_interruption_timeout(
            db_session, org.id, task.id, event_streamer=streamer
        )
        is False
    )

    # 2. Task is awaiting_input, but expected_expires_at is stale -> returns False
    actual_expiry = datetime.now(UTC) + timedelta(minutes=15)
    await task_repo.set_interruption(
        org.id,
        task.id,
        prompt="Need input",
        expires_at=actual_expiry,
    )
    await db_session.commit()

    stale_expiry = actual_expiry - timedelta(minutes=2)
    assert (
        await handle_interruption_timeout(
            db_session,
            org.id,
            task.id,
            expected_expires_at=stale_expiry,
            event_streamer=streamer,
        )
        is False
    )

    # 3. Matching expiry expires the task and archives gzipped transcript
    assert (
        await handle_interruption_timeout(
            db_session,
            org.id,
            task.id,
            expected_expires_at=actual_expiry,
            event_streamer=streamer,
        )
        is True
    )
    archived = await transcript_repo.get_by_task(org.id, task.id, task_run_id=run.id)
    assert archived is not None
    assert gzip.decompress(archived.terminal_log).decode("utf-8") == "before timeout\n"


@pytest.mark.asyncio
async def test_in_memory_streamer_maxlen_cap_wakeup_and_transcript():
    """covers: AC-5 - Streamer caps buffer, wakes blocking reader, builds transcript."""
    streamer = InMemoryOrRedisEventStreamer()
    task_id = uuid.uuid4()

    # Cap at max_len=3
    ids = []
    for i in range(5):
        eid = await streamer.append_event(
            task_id,
            "task.log",
            {"stream": "stdout", "chunk": f"line {i}\n"},
            max_len=3,
        )
        ids.append(eid)

    retained = await streamer.read_events(task_id, last_event_id="0-0")
    assert [e[0] for e in retained] == ids[2:]

    # Blocking reader wakes early when a new event arrives
    q = streamer.subscribe(f"task:{task_id}:stream")

    async def delayed_emit():
        await asyncio.sleep(0.02)
        await streamer.stream_event(
            f"task:{task_id}:stream",
            "task.step",
            {"node": "forge", "status": "completed"},
        )

    emitter = asyncio.create_task(delayed_emit())
    woken = await streamer.read_events(task_id, last_event_id=ids[-1], block_ms=1000)
    await emitter

    assert len(woken) == 1
    assert woken[0][1] == "task.step"
    assert not q.empty()
    streamer.unsubscribe(f"task:{task_id}:stream", q)

    terminal_text, events_json, total_lines = await streamer.get_stream_transcript(
        task_id
    )
    assert terminal_text == "line 2\nline 3\nline 4\n"
    assert total_lines == 3
    assert len(events_json) == 4


def test_postgres_checkpoint_saver_roundtrip():
    """covers: AC-4 - Checkpoint saver exports and imports thread state losslessly."""
    saver1 = PostgresTaskCheckpointSaver()
    thread_id = "run-1:cycle:1"
    saver1.storage[thread_id]["ns"]["cp-1"] = (
        ("json", b'{"v":1}'),
        ("json", b'{"step":1}'),
        None,
    )
    saver1.writes[(thread_id, "ns", "cp-1")] = {
        ("task-a", 0): ("w-task", "channel", ("json", b'{"x":42}'), "path"),
    }

    exported = saver1.export_thread_state(thread_id)

    saver2 = PostgresTaskCheckpointSaver()
    saver2.import_thread_state(thread_id, exported)

    assert (
        saver2.storage[thread_id]["ns"]["cp-1"]
        == saver1.storage[thread_id]["ns"]["cp-1"]
    )
    assert (
        saver2.writes[(thread_id, "ns", "cp-1")]
        == saver1.writes[(thread_id, "ns", "cp-1")]
    )
