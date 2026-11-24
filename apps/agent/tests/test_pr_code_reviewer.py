"""Comprehensive test suite for Full Repository Context Code Reviewer (Spec 0005)."""

import hashlib
import hmac
import json
import random
import uuid
from pathlib import Path
from unittest.mock import AsyncMock, patch

import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.application.ports.github_gateway import GitHubGateway
from app.application.ports.pr_review_repository import PRReviewRepository
from app.application.ports.repository_repository import RepositoryRepository
from app.application.ports.task_repository import TaskRepository
from app.application.services.context_budget_allocator import ContextBudgetAllocator
from app.application.services.diff_hunk_parser import DiffHunkParser
from app.application.services.symbol_indexer import SymbolIndexer
from app.application.use_cases.ingest_github_webhook import IngestGitHubWebhookUseCase
from app.application.use_cases.run_pr_review import RunPRReviewUseCase
from app.domain.entities.pr_review_finding import PRReviewFinding
from app.domain.entities.pull_request_review import PullRequestReview
from app.domain.entities.repository import Repository
from app.domain.entities.task import Task
from app.domain.exceptions import ConflictError, NotFoundError, WebhookSignatureError
from app.infrastructure.db.repositories.organization_repository import (
    SqlAlchemyOrganizationRepository,
)
from app.infrastructure.db.repositories.repository_repository import (
    SqlAlchemyRepositoryRepository,
)
from app.infrastructure.github.review_publisher import GitHubReviewPublisher
from app.infrastructure.llm.reviewer_node import CodeReviewAnalyzerNode


class InMemoryRepositoryRepository(RepositoryRepository):
    """In-memory stub for RepositoryRepository."""

    def __init__(self, repos: list[Repository] | None = None) -> None:
        self.repos: dict[uuid.UUID, Repository] = {r.id: r for r in (repos or [])}
        self.by_github_id: dict[int, Repository] = {
            r.github_repo_id: r for r in (repos or [])
        }

    async def create(
        self,
        org_id: uuid.UUID,
        github_repo_id: int,
        github_installation_id: int,
        name: str,
        full_name: str,
        default_branch: str = "main",
        is_private: bool = True,
        config: dict | None = None,
    ) -> Repository:
        raise NotImplementedError

    async def get_by_id(self, org_id: uuid.UUID, repo_id: uuid.UUID) -> Repository:
        repo = self.repos.get(repo_id)
        if not repo or repo.org_id != org_id:
            raise NotFoundError("Repository not found")
        return repo

    async def get_by_github_id(
        self, org_id: uuid.UUID, github_repo_id: int
    ) -> Repository:
        repo = self.by_github_id.get(github_repo_id)
        if not repo or repo.org_id != org_id:
            raise NotFoundError("Repository not found")
        return repo

    async def find_by_github_repo_id(self, github_repo_id: int) -> Repository | None:
        return self.by_github_id.get(github_repo_id)

    async def list_by_org(
        self, org_id: uuid.UUID, page: int = 1, page_size: int = 20
    ) -> tuple[list[Repository], int]:
        items = [r for r in self.repos.values() if r.org_id == org_id]
        return items, len(items)

    async def soft_delete(self, org_id: uuid.UUID, repo_id: uuid.UUID) -> None:
        pass


class InMemoryTaskRepository(TaskRepository):
    """In-memory stub for TaskRepository."""

    def __init__(self) -> None:
        self.tasks: dict[uuid.UUID, Task] = {}

    async def create_task(
        self,
        org_id: uuid.UUID,
        repo_id: uuid.UUID,
        title: str,
        description: str,
        trigger_type: str,
        trigger_metadata: dict | None = None,
        base_branch: str = "main",
        branch_name: str | None = None,
        created_by_clerk_user_id: str | None = None,
    ) -> Task:
        task = Task(
            id=uuid.uuid4(),
            org_id=org_id,
            repo_id=repo_id,
            title=title,
            description=description,
            trigger_type=trigger_type,
            trigger_metadata=trigger_metadata or {},
            base_branch=base_branch,
            branch_name=branch_name,
        )
        self.tasks[task.id] = task
        return task

    async def get_by_id(self, org_id: uuid.UUID, task_id: uuid.UUID) -> Task:
        t = self.tasks.get(task_id)
        if not t or t.org_id != org_id:
            raise NotFoundError("Task not found")
        return t

    async def find_active_by_repo_and_issue(
        self, repo_id: uuid.UUID, issue_number: int
    ) -> Task | None:
        for t in self.tasks.values():
            meta_issue = t.trigger_metadata.get("issue_number")
            if t.repo_id == repo_id and meta_issue == issue_number:
                if t.status in ("queued", "in_progress"):
                    return t
        return None

    async def list_by_repo(
        self,
        org_id: uuid.UUID,
        repo_id: uuid.UUID,
        page: int = 1,
        page_size: int = 20,
    ):
        items = [t for t in self.tasks.values() if t.repo_id == repo_id]
        return items, len(items)

    async def update_status(
        self,
        org_id: uuid.UUID,
        task_id: uuid.UUID,
        status: str,
        branch_name: str | None = None,
        pr_number: int | None = None,
    ) -> Task:
        t = await self.get_by_id(org_id, task_id)
        t.status = status
        return t

    async def update_pr_details(
        self,
        org_id: uuid.UUID,
        task_id: uuid.UUID,
        pr_url: str,
        head_commit_sha: str,
        pr_review_status: str,
        pr_number: int | None = None,
        branch_name: str | None = None,
    ) -> Task:
        raise NotImplementedError

    async def soft_delete(self, org_id: uuid.UUID, task_id: uuid.UUID) -> None:
        pass


class InMemoryPRReviewRepository(PRReviewRepository):
    """In-memory stub for PRReviewRepository."""

    def __init__(self) -> None:
        self.reviews: dict[uuid.UUID, PullRequestReview] = {}
        self.findings: dict[uuid.UUID, list[PRReviewFinding]] = {}

    async def create_review(
        self,
        org_id: uuid.UUID,
        repo_id: uuid.UUID,
        pr_number: int,
        pr_title: str,
        pr_author: str,
        head_commit_sha: str,
        base_commit_sha: str,
        model_name: str,
        task_id: uuid.UUID | None = None,
    ) -> PullRequestReview:
        active = await self.find_active_by_repo_and_pr(repo_id, pr_number)
        if active:
            raise ConflictError(f"Active review exists for PR #{pr_number}")

        review = PullRequestReview(
            id=uuid.uuid4(),
            org_id=org_id,
            repo_id=repo_id,
            task_id=task_id,
            pr_number=pr_number,
            pr_title=pr_title,
            pr_author=pr_author,
            head_commit_sha=head_commit_sha,
            base_commit_sha=base_commit_sha,
            status="pending",
            verdict=None,
            summary=None,
            github_review_id=None,
            context_token_count=0,
            model_name=model_name,
            execution_duration_ms=None,
            error_message=None,
        )
        self.reviews[review.id] = review
        self.findings[review.id] = []
        return review

    async def get_by_id(
        self, org_id: uuid.UUID, review_id: uuid.UUID
    ) -> PullRequestReview:
        r = self.reviews.get(review_id)
        if not r or r.org_id != org_id:
            raise NotFoundError("Review not found")
        return r

    async def find_active_by_repo_and_pr(
        self, repo_id: uuid.UUID, pr_number: int
    ) -> PullRequestReview | None:
        for r in self.reviews.values():
            if (
                r.repo_id == repo_id
                and r.pr_number == pr_number
                and r.status in ("pending", "analyzing", "reviewing", "posting")
            ):
                return r
        return None

    async def list_by_repo_and_pr(
        self,
        org_id: uuid.UUID,
        repo_id: uuid.UUID,
        pr_number: int,
        page: int = 1,
        page_size: int = 20,
    ) -> tuple[list[PullRequestReview], int]:
        items = [
            r
            for r in self.reviews.values()
            if r.org_id == org_id and r.repo_id == repo_id and r.pr_number == pr_number
        ]
        return items, len(items)

    async def update_status(
        self,
        review_id: uuid.UUID,
        status: str,
        verdict: str | None = None,
        summary: str | None = None,
        github_review_id: int | None = None,
        context_token_count: int | None = None,
        execution_duration_ms: int | None = None,
        error_message: str | None = None,
    ) -> PullRequestReview:
        r = self.reviews.get(review_id)
        if not r:
            raise NotFoundError("Review not found")
        r.status = status
        if verdict is not None:
            r.verdict = verdict
        if summary is not None:
            r.summary = summary
        if github_review_id is not None:
            r.github_review_id = github_review_id
        if context_token_count is not None:
            r.context_token_count = context_token_count
        if execution_duration_ms is not None:
            r.execution_duration_ms = execution_duration_ms
        if error_message is not None:
            r.error_message = error_message
        return r

    async def add_findings(
        self,
        review_id: uuid.UUID,
        findings: list[dict],
    ) -> list[PRReviewFinding]:
        results = []
        for f in findings:
            finding = PRReviewFinding(
                id=uuid.uuid4(),
                review_id=review_id,
                file_path=f["file_path"],
                start_line=f.get("start_line"),
                line_number=f["line_number"],
                side=f.get("side", "RIGHT"),
                severity=f["severity"],
                category=f["category"],
                title=f["title"],
                message=f["message"],
                suggested_patch=f.get("suggested_patch"),
                github_comment_id=f.get("github_comment_id"),
                status=f.get("status", "open"),
            )
            self.findings[review_id].append(finding)
            results.append(finding)
        return results

    async def list_findings(
        self,
        review_id: uuid.UUID,
        page: int = 1,
        page_size: int = 50,
    ) -> tuple[list[PRReviewFinding], int]:
        items = self.findings.get(review_id, [])
        return items, len(items)

    async def update_finding_github_id(
        self,
        finding_id: uuid.UUID,
        github_comment_id: int,
    ) -> None:
        for f_list in self.findings.values():
            for f in f_list:
                if f.id == finding_id:
                    f.github_comment_id = github_comment_id


class MockGitHubService(GitHubGateway):
    """Mock gateway recording review calls and simulating 422 errors when needed."""

    def __init__(self, simulate_422: bool = False) -> None:
        self.simulate_422 = simulate_422
        self.submitted_reviews: list[dict] = []
        self.call_count = 0

    async def get_installation_token(
        self, installation_id: int, write_access: bool = False
    ) -> str:
        return "mock_token_123"

    async def push_branch(
        self,
        repo_full_name: str,
        branch_name: str,
        commit_message: str,
        token: str,
        diff_text: str | None = None,
    ) -> str:
        return "mockcommitsha" + "0" * 27

    async def create_pull_request(
        self,
        repo_full_name: str,
        base_branch: str,
        head_branch: str,
        title: str,
        body: str,
        token: str,
    ) -> dict[str, str | int]:
        return {"pr_url": "https://github.com/org/repo/pull/1", "pr_number": 1}

    async def get_pull_request(
        self,
        repo_full_name: str,
        pr_number: int,
        token: str,
    ) -> dict:
        return {
            "number": pr_number,
            "title": "Add payment gateway",
            "user": {"login": "alice", "type": "User"},
            "head": {"sha": "headsha12345" + "0" * 27},
            "base": {"sha": "basesha12345" + "0" * 27},
        }

    async def get_pull_request_diff(
        self,
        repo_full_name: str,
        pr_number: int,
        token: str,
    ) -> str:
        return (
            "diff --git a/app/payment.py b/app/payment.py\n"
            "index 0000000..1111111 100644\n"
            "--- a/app/payment.py\n"
            "+++ b/app/payment.py\n"
            "@@ -10,6 +10,10 @@\n"
            " def process_charge(amount: int):\n"
            "+    # TODO: sanitize\n"
            "+    if amount <= 0:\n"
            "+        raise ValueError('Invalid amount')\n"
            "     return True\n"
        )

    async def submit_review(
        self,
        repo_full_name: str,
        pr_number: int,
        commit_sha: str,
        body: str,
        event: str,
        comments: list[dict],
        token: str,
    ) -> dict:
        self.call_count += 1
        if self.simulate_422 and self.call_count == 1:
            raise RuntimeError(
                "GitHub 422 Unprocessable Entity: Pull request review line invalid"
            )

        review = {
            "id": 998877,
            "repo": repo_full_name,
            "pr_number": pr_number,
            "commit_id": commit_sha,
            "body": body,
            "event": event,
            "comments": comments,
        }
        self.submitted_reviews.append(review)
        return review


def sign_payload(payload_bytes: bytes, secret: str) -> str:
    sig = hmac.new(secret.encode("utf-8"), payload_bytes, hashlib.sha256).hexdigest()
    return f"sha256={sig}"


@pytest.mark.asyncio
async def test_symbol_indexer_and_context_budget_allocator(tmp_path: Path):
    """Test AST symbol extraction and two-tier context packing (AC-2, AC-3)."""
    src_dir = tmp_path / "src"
    src_dir.mkdir()

    calc_file = src_dir / "calculator.py"
    calc_file.write_text(
        "class Calculator:\n"
        "    def add(self, a, b):\n"
        "        return a + b\n\n"
        "def compute_total(items):\n"
        "    calc = Calculator()\n"
        "    return calc.add(1, 2)\n"
    )

    indexer = SymbolIndexer(tmp_path)
    graph = indexer.build_graph()

    assert "src/calculator.py::Calculator" in graph.symbols
    assert "src/calculator.py::compute_total" in graph.symbols
    assert "add" in graph.callers

    # Test context budget allocation
    diff_text = (
        "diff --git a/src/calculator.py b/src/calculator.py\n"
        "--- a/src/calculator.py\n"
        "+++ b/src/calculator.py\n"
        "@@ -1,3 +1,3 @@\n"
        "-def compute_total():\n"
        "+def compute_total(items):\n"
    )
    context = ContextBudgetAllocator.assemble_context(
        diff_text=diff_text,
        symbol_graph=graph,
        repo_dir=tmp_path,
        agents_md_text="# Agents Guide",
    )

    assert "AGENTS.md" in context.tier1_content
    assert "compute_total" in context.tier1_content
    assert context.total_token_count < 64000


@pytest.mark.asyncio
async def test_reviewer_verdict_resolution_and_schema():
    """Test deterministic review verdict resolution (AC-4)."""
    analyzer = CodeReviewAnalyzerNode()

    # 1. Critical finding -> changes_requested
    v1 = analyzer.resolve_verdict(
        [{"severity": "critical", "category": "security"}], allow_approval=True
    )
    assert v1 == "changes_requested"

    # 2. Minor finding -> comment
    v2 = analyzer.resolve_verdict(
        [{"severity": "minor", "category": "style"}], allow_approval=True
    )
    assert v2 == "comment"

    # 3. Zero findings with allow_approval=True -> approved
    v3 = analyzer.resolve_verdict([], allow_approval=True)
    assert v3 == "approved"

    # 4. Zero findings with allow_approval=False -> comment
    v4 = analyzer.resolve_verdict([], allow_approval=False)
    assert v4 == "comment"


@pytest.mark.asyncio
async def test_github_webhook_pr_events_and_bot_exclusion():
    """Test webhook routing, bot exclusion, and PR comment triggers (AC-1)."""
    org_id = uuid.uuid4()
    repo_id = uuid.uuid4()
    repo = Repository(
        id=repo_id,
        org_id=org_id,
        github_repo_id=123456,
        github_installation_id=789,
        name="test-repo",
        full_name="testorg/test-repo",
        review_settings={
            "enabled": True,
            "auto_review": True,
            "allow_approval": True,
            "ignore_all_bots": False,
            "min_severity": "info",
            "max_comments": 25,
            "ignored_paths": ["*.lock"],
        },
    )

    repo_repo = InMemoryRepositoryRepository([repo])
    task_repo = InMemoryTaskRepository()
    pr_review_repo = InMemoryPRReviewRepository()
    mock_gh = MockGitHubService()

    use_case = IngestGitHubWebhookUseCase(
        repository_repo=repo_repo,
        task_repo=task_repo,
        pr_review_repo=pr_review_repo,
        github_gateway=mock_gh,
    )

    secret = "secret123"

    # 1. Normal PR opened -> Queued
    pr_payload = {
        "action": "opened",
        "repository": {"id": 123456},
        "pull_request": {
            "number": 10,
            "title": "Feature branch",
            "user": {"login": "developer", "type": "User"},
            "head": {"sha": "sha_head_10"},
            "base": {"sha": "sha_base_10"},
        },
    }
    payload_bytes = json.dumps(pr_payload).encode("utf-8")
    sig = sign_payload(payload_bytes, secret)

    res = await use_case.execute(
        event_type="pull_request",
        delivery_id="del_1",
        payload_bytes=payload_bytes,
        signature_header=sig,
        webhook_secret=secret,
    )
    assert res.status == "queued"
    assert res.review_id is not None

    # 2. Duplicate PR opened while active -> Ignored
    res_dup = await use_case.execute(
        event_type="pull_request",
        delivery_id="del_2",
        payload_bytes=payload_bytes,
        signature_header=sig,
        webhook_secret=secret,
    )
    assert res_dup.status == "ignored"
    assert res_dup.reason == "active_review_already_exists"

    # 3. PR authored by agentsonair[bot] -> Ignored
    bot_payload = {
        "action": "opened",
        "repository": {"id": 123456},
        "pull_request": {
            "number": 11,
            "title": "Bot patch",
            "user": {"login": "agentsonair[bot]", "type": "Bot"},
            "head": {"sha": "sha_head_11"},
            "base": {"sha": "sha_base_11"},
        },
    }
    bot_bytes = json.dumps(bot_payload).encode("utf-8")
    res_bot = await use_case.execute(
        event_type="pull_request",
        delivery_id="del_3",
        payload_bytes=bot_bytes,
        signature_header=sign_payload(bot_bytes, secret),
        webhook_secret=secret,
    )
    assert res_bot.status == "ignored"
    assert res_bot.reason == "bot_author_excluded"


@pytest.mark.asyncio
async def test_review_publisher_with_line_placement_and_422_fallback():
    """Test DiffHunkParser inline suggestions and 422 diff drift fallback (AC-5)."""
    diff_text = (
        "diff --git a/src/service.py b/src/service.py\n"
        "index 0000000..1111111 100644\n"
        "--- a/src/service.py\n"
        "+++ b/src/service.py\n"
        "@@ -10,5 +10,6 @@\n"
        " def handle():\n"
        "+    x = 1\n"
        "     return x\n"
    )

    mock_gh = MockGitHubService(simulate_422=True)
    publisher = GitHubReviewPublisher(mock_gh)

    findings = [
        {
            "file_path": "src/service.py",
            "line_number": 11,  # In diff
            "severity": "major",
            "category": "bug",
            "title": "Unnecessary assignment",
            "message": "Direct return possible",
            "suggested_patch": "    return 1",
        },
        {
            "file_path": "src/other.py",
            "line_number": 50,  # Out of diff
            "severity": "minor",
            "category": "architecture",
            "title": "Caller interface stale",
            "message": "Update caller signature",
            "suggested_patch": None,
        },
    ]

    res = await publisher.publish(
        repo_full_name="testorg/test-repo",
        pr_number=5,
        head_commit_sha="commitsha12345",
        verdict="changes_requested",
        summary="Found 2 issues",
        findings=findings,
        diff_text=diff_text,
        token="token_abc",
    )

    assert res.fallback_applied is True
    assert mock_gh.call_count == 2
    assert "Diff Drift Fallback" in res.summary_markdown


@pytest.mark.asyncio
async def test_end_to_end_pr_review_use_case(tmp_path: Path):
    """Test full execution of RunPRReviewUseCase updating state (AC-1..AC-5)."""
    org_id = uuid.uuid4()
    repo_id = uuid.uuid4()
    repo = Repository(
        id=repo_id,
        org_id=org_id,
        github_repo_id=123456,
        github_installation_id=789,
        name="test-repo",
        full_name="testorg/test-repo",
        review_settings={
            "enabled": True,
            "auto_review": True,
            "allow_approval": True,
            "ignore_all_bots": False,
            "min_severity": "info",
            "max_comments": 25,
            "ignored_paths": ["*.lock"],
        },
    )

    pr_review_repo = InMemoryPRReviewRepository()
    repo_repo = InMemoryRepositoryRepository([repo])
    mock_gh = MockGitHubService()

    # Create pending review record
    review = await pr_review_repo.create_review(
        org_id=org_id,
        repo_id=repo_id,
        pr_number=42,
        pr_title="Add checkout pipeline",
        pr_author="carol",
        head_commit_sha="head42",
        base_commit_sha="base42",
        model_name="claude-3-5-sonnet",
    )

    use_case = RunPRReviewUseCase(
        pr_review_repo=pr_review_repo,
        repository_repo=repo_repo,
        github_gateway=mock_gh,
    )

    completed = await use_case.execute(
        org_id=org_id,
        review_id=review.id,
        repo_dir=str(tmp_path),
        simulated_findings=[
            {
                "file_path": "app/payment.py",
                "line_number": 12,
                "severity": "minor",
                "category": "style",
                "title": "Use strict comparison",
                "message": "Prefer isinstance check",
                "suggested_patch": None,
            }
        ],
    )

    assert completed.status == "completed"
    assert completed.verdict == "comment"
    assert completed.github_review_id == 998877

    # Verify findings persisted
    findings, total = await pr_review_repo.list_findings(review.id)
    assert total == 1
    assert findings[0].file_path == "app/payment.py"


def test_diff_hunk_parser_multihunk_and_containment():
    """Test DiffHunkParser across multi file and multi hunk diffs (AC-5)."""
    diff_text = (
        "diff --git a/app/core.py b/app/core.py\n"
        "index 1111111..2222222 100644\n"
        "--- a/app/core.py\n"
        "+++ b/app/core.py\n"
        "@@ -5,4 +5,6 @@\n"
        " def start():\n"
        "+    setup_logging()\n"
        "+    init_db()\n"
        "     return True\n"
        "@@ -20,3 +22,5 @@\n"
        " def stop():\n"
        "+    close_db()\n"
        "+    flush_logs()\n"
        "     return False\n"
        "diff --git a/app/config.py b/app/config.py\n"
        "index 3333333..4444444 100644\n"
        "--- a/app/config.py\n"
        "+++ b/app/config.py\n"
        "@@ -1,2 +1,3 @@\n"
        " DEBUG = True\n"
        "+VERSION = '1.0'\n"
    )

    files = DiffHunkParser.parse(diff_text)
    assert len(files) == 2
    assert "app/core.py" in files
    assert "app/config.py" in files

    core_diff = files["app/core.py"]
    assert len(core_diff.hunks) == 2

    # Hunk 1 covers lines 5 to 10 (new_start=5, new_length=6)
    assert core_diff.contains_new_line(5) is True
    assert core_diff.contains_new_line(7) is True
    assert core_diff.contains_new_line(10) is True
    assert core_diff.contains_new_line(11) is False
    assert core_diff.contains_new_line(15) is False

    # Hunk 2 covers lines 22 to 26 (new_start=22, new_length=5)
    assert core_diff.contains_new_line(22) is True
    assert core_diff.contains_new_line(25) is True
    assert core_diff.contains_new_line(30) is False

    # Empty diff handling
    empty_files = DiffHunkParser.parse("")
    assert empty_files == {}


def test_context_budget_allocator_pruning_and_token_bounds(tmp_path: Path):
    """Test context budget allocator limits and file pruning (AC-3)."""
    indexer = SymbolIndexer(tmp_path)
    graph = indexer.build_graph()

    # Diff with normal file and lock file
    diff_text = (
        "diff --git a/yarn.lock b/yarn.lock\n"
        "--- a/yarn.lock\n"
        "+++ b/yarn.lock\n"
        "@@ -1,3 +1,3 @@\n"
        "-lock: 1\n"
        "+lock: 2\n"
        "diff --git a/src/main.py b/src/main.py\n"
        "--- a/src/main.py\n"
        "+++ b/src/main.py\n"
        "@@ -1,2 +1,3 @@\n"
        " import os\n"
        "+print('hello')\n"
    )

    context = ContextBudgetAllocator.assemble_context(
        diff_text=diff_text,
        symbol_graph=graph,
        repo_dir=tmp_path,
        agents_md_text="# Guide\nFollow clean architecture.",
    )

    # Check ignored lock file was omitted
    assert "yarn.lock" in context.omitted_files
    assert "src/main.py" not in context.omitted_files
    assert "print('hello')" in context.tier1_content

    # Test an oversized diff that exceeds TIER1_MAX_TOKENS
    giant_diff_lines = [
        "diff --git a/src/giant.py b/src/giant.py",
        "--- a/src/giant.py",
        "+++ b/src/giant.py",
        "@@ -1,1 +1,40000 @@",
    ] + [f"+line_{i} = {i}" for i in range(25000)]
    giant_diff = "\n".join(giant_diff_lines)

    oversized_context = ContextBudgetAllocator.assemble_context(
        diff_text=giant_diff,
        symbol_graph=graph,
        repo_dir=tmp_path,
    )
    assert "src/giant.py" in oversized_context.omitted_files
    assert oversized_context.total_token_count <= ContextBudgetAllocator.TOTAL_BUDGET


def test_context_budget_allocator_directory_glob_pruning(tmp_path: Path):
    """Test that directory patterns like dist/** prune matching files (AC-3)."""
    indexer = SymbolIndexer(tmp_path)
    graph = indexer.build_graph()

    diff_text = (
        "diff --git a/dist/bundle.js b/dist/bundle.js\n"
        "--- a/dist/bundle.js\n"
        "+++ b/dist/bundle.js\n"
        "@@ -1,2 +1,2 @@\n"
        "-console.log('old')\n"
        "+console.log('new')\n"
    )

    context = ContextBudgetAllocator.assemble_context(
        diff_text=diff_text,
        symbol_graph=graph,
        repo_dir=tmp_path,
        ignored_patterns=["dist/**"],
    )

    assert "dist/bundle.js" in context.omitted_files


@pytest.mark.asyncio
async def test_webhook_ingest_edge_cases_and_security():
    """Test webhook signature security and edge case routing triggers (AC-1)."""
    org_id = uuid.uuid4()
    repo_id = uuid.uuid4()
    repo = Repository(
        id=repo_id,
        org_id=org_id,
        github_repo_id=222333,
        github_installation_id=444,
        name="edge-repo",
        full_name="testorg/edge-repo",
        review_settings={
            "enabled": True,
            "auto_review": True,
            "allow_approval": True,
            "ignore_all_bots": False,
            "min_severity": "info",
            "max_comments": 25,
            "ignored_paths": ["*.lock"],
        },
    )

    repo_repo = InMemoryRepositoryRepository([repo])
    task_repo = InMemoryTaskRepository()
    pr_review_repo = InMemoryPRReviewRepository()
    mock_gh = MockGitHubService()

    use_case = IngestGitHubWebhookUseCase(
        repository_repo=repo_repo,
        task_repo=task_repo,
        pr_review_repo=pr_review_repo,
        github_gateway=mock_gh,
    )
    secret = "test_secret_key"

    # 1. Invalid signature raises WebhookSignatureError
    payload_bytes = json.dumps({"action": "opened"}).encode("utf-8")
    with pytest.raises(WebhookSignatureError):
        await use_case.execute(
            event_type="pull_request",
            delivery_id="del_sig_bad",
            payload_bytes=payload_bytes,
            signature_header="sha256=bad_hex",
            webhook_secret=secret,
        )

    # 2. PR comment with @agentsonair review on a PR queues review
    comment_payload = {
        "action": "created",
        "repository": {"id": 222333},
        "issue": {
            "number": 77,
            "title": "Update billing module",
            "pull_request": {
                "url": "https://api.github.com/repos/testorg/edge-repo/pulls/77"
            },
            "user": {"login": "bob"},
        },
        "comment": {"body": "Hey @agentsonair review please check this PR"},
        "sender": {"login": "alice", "type": "User"},
    }
    comment_bytes = json.dumps(comment_payload).encode("utf-8")
    res_comment = await use_case.execute(
        event_type="issue_comment",
        delivery_id="del_comm_1",
        payload_bytes=comment_bytes,
        signature_header=sign_payload(comment_bytes, secret),
        webhook_secret=secret,
    )
    assert res_comment.status == "queued"
    assert res_comment.review_id is not None

    # 3. Comment with @agentsonair review on a regular issue (not PR) is ignored
    issue_comment_payload = {
        "action": "created",
        "repository": {"id": 222333},
        "issue": {
            "number": 88,
            "title": "Bug in billing",
            "user": {"login": "bob"},
        },
        "comment": {"body": "Hey @agentsonair review this issue"},
        "sender": {"login": "alice", "type": "User"},
    }
    issue_bytes = json.dumps(issue_comment_payload).encode("utf-8")
    res_issue = await use_case.execute(
        event_type="issue_comment",
        delivery_id="del_comm_2",
        payload_bytes=issue_bytes,
        signature_header=sign_payload(issue_bytes, secret),
        webhook_secret=secret,
    )
    assert res_issue.status == "ignored"
    assert res_issue.reason == "review_command_on_issue_not_pr"

    # 4. Comment created by a bot sender is ignored
    bot_comment_payload = {
        "action": "created",
        "repository": {"id": 222333},
        "issue": {
            "number": 77,
            "title": "Update billing module",
            "pull_request": {
                "url": "https://api.github.com/repos/testorg/edge-repo/pulls/77"
            },
            "user": {"login": "bob"},
        },
        "comment": {"body": "Hey @agentsonair review bot comment"},
        "sender": {"login": "ci-bot", "type": "Bot"},
    }
    bot_comm_bytes = json.dumps(bot_comment_payload).encode("utf-8")
    res_bot_comm = await use_case.execute(
        event_type="issue_comment",
        delivery_id="del_comm_3",
        payload_bytes=bot_comm_bytes,
        signature_header=sign_payload(bot_comm_bytes, secret),
        webhook_secret=secret,
    )
    assert res_bot_comm.status == "ignored"
    assert res_bot_comm.reason == "bot_comment_excluded"

    # 5. Reviews disabled in repository settings is ignored
    repo.review_settings["enabled"] = False
    pr_payload = {
        "action": "opened",
        "repository": {"id": 222333},
        "pull_request": {
            "number": 99,
            "title": "PR with disabled reviews",
            "user": {"login": "carol", "type": "User"},
            "head": {"sha": "sha_99"},
            "base": {"sha": "sha_base_99"},
        },
    }
    pr_bytes = json.dumps(pr_payload).encode("utf-8")
    res_disabled = await use_case.execute(
        event_type="pull_request",
        delivery_id="del_pr_dis",
        payload_bytes=pr_bytes,
        signature_header=sign_payload(pr_bytes, secret),
        webhook_secret=secret,
    )
    assert res_disabled.status == "ignored"
    assert res_disabled.reason == "reviews_disabled"

    # 6. Auto review disabled in repository settings is ignored
    repo.review_settings["enabled"] = True
    repo.review_settings["auto_review"] = False
    res_no_auto = await use_case.execute(
        event_type="pull_request",
        delivery_id="del_pr_no_auto",
        payload_bytes=pr_bytes,
        signature_header=sign_payload(pr_bytes, secret),
        webhook_secret=secret,
    )
    assert res_no_auto.status == "ignored"
    assert res_no_auto.reason == "auto_review_disabled"

    # 7. ignore_all_bots enabled in settings ignores generic bots
    repo.review_settings["auto_review"] = True
    repo.review_settings["ignore_all_bots"] = True
    generic_bot_payload = {
        "action": "opened",
        "repository": {"id": 222333},
        "pull_request": {
            "number": 100,
            "title": "Renovate updates",
            "user": {"login": "renovate[bot]", "type": "Bot"},
            "head": {"sha": "sha_100"},
            "base": {"sha": "sha_base_100"},
        },
    }
    bot_pr_bytes = json.dumps(generic_bot_payload).encode("utf-8")
    res_generic_bot = await use_case.execute(
        event_type="pull_request",
        delivery_id="del_pr_gen_bot",
        payload_bytes=bot_pr_bytes,
        signature_header=sign_payload(bot_pr_bytes, secret),
        webhook_secret=secret,
    )
    assert res_generic_bot.status == "ignored"
    assert res_generic_bot.reason == "bot_author_excluded_by_settings"


def test_reviewer_verdict_severity_combinations():
    """Test verdict resolution rules across severity combinations (AC-4)."""
    analyzer = CodeReviewAnalyzerNode()

    # Critical alone gives changes_requested
    v_crit = analyzer.resolve_verdict(
        [{"severity": "critical", "category": "security"}]
    )
    assert v_crit == "changes_requested"

    # Major alone gives changes_requested
    v_maj = analyzer.resolve_verdict([{"severity": "major", "category": "bug"}])
    assert v_maj == "changes_requested"

    # Mixed critical and minor gives changes_requested
    assert (
        analyzer.resolve_verdict(
            [
                {"severity": "critical", "category": "security"},
                {"severity": "minor", "category": "style"},
            ]
        )
        == "changes_requested"
    )

    # Mixed minor and info gives comment
    assert (
        analyzer.resolve_verdict(
            [
                {"severity": "minor", "category": "style"},
                {"severity": "info", "category": "architecture"},
            ]
        )
        == "comment"
    )

    # Only info gives comment
    v_info = analyzer.resolve_verdict([{"severity": "info", "category": "performance"}])
    assert v_info == "comment"

    # Zero findings with allow_approval=True gives approved
    assert analyzer.resolve_verdict([], allow_approval=True) == "approved"

    # Zero findings with allow_approval=False gives comment
    assert analyzer.resolve_verdict([], allow_approval=False) == "comment"


@pytest.mark.asyncio
async def test_pr_review_repository_concurrency_and_lifecycle():
    """Test active review concurrency guard and status lifecycle (AC-1, AC-5)."""
    repo = InMemoryPRReviewRepository()
    org_id = uuid.uuid4()
    repo_id = uuid.uuid4()

    review1 = await repo.create_review(
        org_id=org_id,
        repo_id=repo_id,
        pr_number=50,
        pr_title="Add telemetry",
        pr_author="dan",
        head_commit_sha="sha_50_a",
        base_commit_sha="sha_50_b",
        model_name="claude-3-5-sonnet",
    )
    assert review1.status == "pending"

    # Concurrent create while review1 is active raises ConflictError
    with pytest.raises(ConflictError):
        await repo.create_review(
            org_id=org_id,
            repo_id=repo_id,
            pr_number=50,
            pr_title="Add telemetry again",
            pr_author="dan",
            head_commit_sha="sha_50_a",
            base_commit_sha="sha_50_b",
            model_name="claude-3-5-sonnet",
        )

    # Transition review1 through analyzing and completed
    await repo.update_status(review1.id, "analyzing")
    assert (await repo.get_by_id(org_id, review1.id)).status == "analyzing"

    await repo.update_status(
        review1.id,
        status="completed",
        verdict="approved",
        summary="All checks look clean.",
        github_review_id=1234567,
        context_token_count=15000,
        execution_duration_ms=4500,
    )
    completed_review = await repo.get_by_id(org_id, review1.id)
    assert completed_review.status == "completed"
    assert completed_review.verdict == "approved"
    assert completed_review.github_review_id == 1234567

    # Since review1 is completed, creating a new review for same PR succeeds
    review2 = await repo.create_review(
        org_id=org_id,
        repo_id=repo_id,
        pr_number=50,
        pr_title="Add telemetry rev 2",
        pr_author="dan",
        head_commit_sha="sha_50_c",
        base_commit_sha="sha_50_b",
        model_name="claude-3-5-sonnet",
    )
    assert review2.status == "pending"

    # Status update to failed with error message
    await repo.update_status(
        review2.id,
        status="failed",
        error_message="GitHub secondary rate limit reached",
    )
    failed_review = await repo.get_by_id(org_id, review2.id)
    assert failed_review.status == "failed"
    assert failed_review.error_message == "GitHub secondary rate limit reached"


@pytest.mark.asyncio
async def test_reviews_api_endpoints_integration(
    client: AsyncClient, db_session: AsyncSession
):
    """Test Pull Request Reviews REST API endpoints (AC-5)."""
    org_repo = SqlAlchemyOrganizationRepository(db_session)
    repo_repo = SqlAlchemyRepositoryRepository(db_session)

    org = await org_repo.create_or_update(
        clerk_org_id=f"org_{uuid.uuid4().hex[:12]}",
        name="Review API Test Org",
        slug=f"review-api-{uuid.uuid4().hex[:8]}",
    )
    repo = await repo_repo.create(
        org_id=org.id,
        github_repo_id=random.randint(100000, 999999),
        github_installation_id=55555,
        name="review-api-repo",
        full_name=f"testorg/review-api-repo-{uuid.uuid4().hex[:6]}",
        default_branch="main",
    )
    await db_session.commit()

    pr_num = 123

    # Mock GitHubService for trigger endpoint
    with (
        patch(
            "app.api.v1.endpoints.reviews.GitHubService.get_installation_token",
            new=AsyncMock(return_value="mock_token"),
        ),
        patch(
            "app.api.v1.endpoints.reviews.GitHubService.get_pull_request",
            new=AsyncMock(
                return_value={
                    "number": pr_num,
                    "title": "Add analytics",
                    "user": {"login": "eva"},
                    "head": {"sha": "sha_head_123"},
                    "base": {"sha": "sha_base_123"},
                }
            ),
        ),
    ):
        # 1. Trigger review returns 200 with review id
        res = await client.post(
            f"/api/v1/repos/{repo.id}/pulls/{pr_num}/reviews",
            json={"org_id": str(org.id)},
        )
        assert res.status_code == 200
        review_data = res.json()
        assert review_data["status"] == "pending"
        assert review_data["pr_number"] == pr_num
        review_id = review_data["id"]

        # 2. Trigger duplicate review while active returns 409 Conflict
        res_dup = await client.post(
            f"/api/v1/repos/{repo.id}/pulls/{pr_num}/reviews",
            json={"org_id": str(org.id)},
        )
        assert res_dup.status_code == 409
        assert "active review already exists" in res_dup.json()["detail"].lower()

        # 3. List reviews for PR returns reviews list
        res_list = await client.get(
            f"/api/v1/repos/{repo.id}/pulls/{pr_num}/reviews",
            params={"org_id": str(org.id)},
        )
        assert res_list.status_code == 200
        list_data = res_list.json()
        assert list_data["total"] >= 1
        assert list_data["items"][0]["id"] == review_id

        # 4. Get review detail returns review and findings
        res_detail = await client.get(
            f"/api/v1/reviews/{review_id}",
            params={"org_id": str(org.id)},
        )
        assert res_detail.status_code == 200
        detail_data = res_detail.json()
        assert detail_data["id"] == review_id
        assert detail_data["pr_title"] == "Add analytics"
        assert isinstance(detail_data["findings"], list)

        # 5. Non existent review returns 404 Not Found
        non_existent_id = uuid.uuid4()
        res_404 = await client.get(
            f"/api/v1/reviews/{non_existent_id}",
            params={"org_id": str(org.id)},
        )
        assert res_404.status_code == 404
