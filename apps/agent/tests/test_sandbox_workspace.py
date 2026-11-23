"""Unit tests for SandboxWorkspace, providers, and webhook signatures (AC-1, AC-3)."""

import hashlib
import hmac
import uuid

import pytest

from app.application.services.sandbox_workspace import SandboxWorkspace
from app.domain.exceptions import BaselineTestFailedError
from app.infrastructure.events.redis_streamer import InMemoryOrRedisEventStreamer
from app.infrastructure.github.webhook import verify_github_signature
from app.infrastructure.sandbox.docker_sandbox import DockerSandboxProvider
from app.infrastructure.sandbox.e2b_sandbox import E2BSandboxProvider
from app.infrastructure.sandbox.factory import get_sandbox_provider
from app.infrastructure.sandbox.mock_sandbox import MockSandboxProvider


@pytest.mark.asyncio
async def test_sandbox_workspace_file_operations_and_init():
    """Verify workspace initialization and file read/write operations (AC-3)."""
    provider = MockSandboxProvider()
    streamer = InMemoryOrRedisEventStreamer()
    org_id = uuid.uuid4()
    task_id = uuid.uuid4()

    sandbox = await provider.create_sandbox(org_id, task_id)
    workspace = SandboxWorkspace(sandbox, task_id, streamer)

    try:
        # Initialize workspace
        await workspace.init_workspace(
            repo_url_with_read_token=None,
            base_branch="main",
            work_branch="agentsonair/task-test01-issue-1",
        )

        # Write and read file
        test_content = "def hello():\n    return 'world'\n"
        write_res = await workspace.write_file("src/hello.py", test_content)
        assert "Successfully wrote" in write_res

        read_back = await workspace.read_file("src/hello.py")
        assert read_back == test_content

        # List files via underlying session
        file_list = await workspace.session.list_files()
        assert any("src/hello.py" in f for f in file_list)

        # Get diff
        diff = await workspace.get_diff()
        assert isinstance(diff, str)

        # Telemetry verification
        event_types = [e["type"] for e in streamer.events]
        assert "workspace_init_started" in event_types
        assert "workspace_init_completed" in event_types
        assert "tool_write_file" in event_types
        assert "tool_read_file" in event_types
        assert "tool_get_diff" in event_types
    finally:
        await sandbox.terminate()


@pytest.mark.asyncio
async def test_sandbox_workspace_baseline_tests_success():
    """Verify passing baseline command succeeds and emits telemetry (AC-3)."""
    provider = MockSandboxProvider()
    streamer = InMemoryOrRedisEventStreamer()
    task_id = uuid.uuid4()

    sandbox = await provider.create_sandbox(uuid.uuid4(), task_id)
    workspace = SandboxWorkspace(sandbox, task_id, streamer)

    try:
        await workspace.init_workspace(None, "main", "agentsonair/task-test-baseline")
        result = await workspace.run_baseline_tests("echo 'Tests passed'")
        assert result.exit_code == 0
        assert "Tests passed" in result.stdout

        event_types = [e["type"] for e in streamer.events]
        assert "baseline_test_started" in event_types
        assert "baseline_test_completed" in event_types
    finally:
        await sandbox.terminate()


@pytest.mark.asyncio
async def test_sandbox_workspace_baseline_tests_failure_raises_error():
    """Verify non-zero baseline exit code aborts with BaselineTestFailedError (AC-3)."""
    provider = MockSandboxProvider()
    task_id = uuid.uuid4()

    sandbox = await provider.create_sandbox(uuid.uuid4(), task_id)
    workspace = SandboxWorkspace(sandbox, task_id)

    try:
        await workspace.init_workspace(
            None, "main", "agentsonair/task-test-baseline-fail"
        )
        with pytest.raises(BaselineTestFailedError) as exc_info:
            await workspace.run_baseline_tests("exit 1")

        assert "Baseline tests failed with code 1" in str(exc_info.value)
    finally:
        await sandbox.terminate()


@pytest.mark.asyncio
async def test_sandbox_workspace_run_command_and_telemetry():
    """Verify tool execution streams command telemetry events (AC-3)."""
    provider = MockSandboxProvider()
    streamer = InMemoryOrRedisEventStreamer()
    task_id = uuid.uuid4()

    sandbox = await provider.create_sandbox(uuid.uuid4(), task_id)
    workspace = SandboxWorkspace(sandbox, task_id, streamer)

    try:
        await workspace.init_workspace(None, "main", "agentsonair/task-test-tool")
        res_cmd = await workspace.run_command("echo 'hello stdout'")
        assert res_cmd.exit_code == 0
        assert "hello stdout" in res_cmd.stdout
        assert res_cmd.duration_seconds >= 0

        res_test = await workspace.run_test("echo 'test ran'")
        assert res_test.exit_code == 0
        assert "test ran" in res_test.stdout

        event_types = [e["type"] for e in streamer.events]
        assert "tool_run_command_started" in event_types
        assert "tool_run_command_completed" in event_types
        assert "tool_run_test_started" in event_types
        assert "tool_run_test_completed" in event_types
    finally:
        await sandbox.terminate()


def test_sandbox_provider_factory():
    """Verify factory returns appropriate provider implementation."""
    mock_prov = get_sandbox_provider("mock")
    assert isinstance(mock_prov, MockSandboxProvider)

    default_prov = get_sandbox_provider()
    assert isinstance(default_prov, (DockerSandboxProvider, MockSandboxProvider))

    docker_prov = get_sandbox_provider("docker")
    assert isinstance(docker_prov, DockerSandboxProvider)

    e2b_prov = get_sandbox_provider("e2b")
    assert isinstance(e2b_prov, E2BSandboxProvider)


def test_webhook_signature_verification_utility():
    """Verify HMAC SHA256 signature utility edge cases (AC-1)."""
    secret = "my-test-secret"
    payload = b'{"hello": "world"}'
    valid_sig = (
        "sha256="
        + hmac.new(secret.encode("utf-8"), payload, hashlib.sha256).hexdigest()
    )

    # Valid signature
    assert verify_github_signature(payload, valid_sig, secret) is True

    # Empty signature header
    assert verify_github_signature(payload, None, secret) is False
    assert verify_github_signature(payload, "", secret) is False

    # Empty secret
    assert verify_github_signature(payload, valid_sig, "") is False

    # Missing sha256= prefix
    raw_hash = hmac.new(secret.encode("utf-8"), payload, hashlib.sha256).hexdigest()
    assert verify_github_signature(payload, raw_hash, secret) is False

    # Mismatched payload
    assert verify_github_signature(b'{"different": "data"}', valid_sig, secret) is False

    # Tampered signature
    assert (
        verify_github_signature(
            payload,
            "sha256=0000000000000000000000000000000000000000000000000000000000000000",
            secret,
        )
        is False
    )
