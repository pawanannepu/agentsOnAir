"""Cyclical autonomous engineer and reviewer execution loop use case."""

import asyncio
import gzip
import json
import uuid
from datetime import UTC, datetime, timedelta
from typing import Any

from app.application.ports.audit_log_repository import AuditLogRepository
from app.application.ports.event_streamer import EventStreamer
from app.application.ports.github_gateway import GitHubGateway
from app.application.ports.model_gateway import (
    ForgeAgent,
    ForgeResult,
    ReviewerCritic,
    ReviewerResult,
)
from app.application.ports.organization_repository import OrganizationRepository
from app.application.ports.repository_repository import RepositoryRepository
from app.application.ports.review_iteration_repository import (
    ReviewIterationRepository,
)
from app.application.ports.sandbox import SandboxProvider, SandboxSession
from app.application.ports.sandbox_run_repository import SandboxRunRepository
from app.application.ports.task_approval_repository import TaskApprovalRepository
from app.application.ports.task_intervention_repository import (
    TaskInterventionRepository,
)
from app.application.ports.task_queue import TaskQueue
from app.application.ports.task_repository import TaskRepository
from app.application.ports.task_run_repository import TaskRunRepository
from app.application.ports.task_transcript_repository import (
    TaskTranscriptRepository,
)
from app.application.ports.usage_repository import UsageRepository
from app.application.services.sandbox_workspace import SandboxWorkspace
from app.application.services.usage_tracker import UsageTracker
from app.core.config import settings
from app.domain.entities.repository import Repository
from app.domain.entities.task import Task
from app.domain.entities.task_run import TaskRun
from app.domain.exceptions import (
    BaselineTestFailedError,
    BudgetExceededError,
    GuardrailBlockedError,
    ProtectedBranchError,
    TaskTimeoutError,
)
from app.domain.services.policy_evaluator import (
    EffectiveGuardrailPolicy,
    PolicyEvaluator,
    RiskClassification,
)
from app.infrastructure.db.repositories.organization_repository import (
    SqlAlchemyOrganizationRepository,
)
from app.infrastructure.db.repositories.task_approval_repository import (
    SqlAlchemyTaskApprovalRepository,
)
from app.infrastructure.db.repositories.usage_repository import (
    SqlAlchemyUsageRepository,
)
from app.infrastructure.llm.task_graph import (
    Command,
    PostgresTaskCheckpointSaver,
    TaskGraphState,
    build_task_cycle_graph,
)
from app.infrastructure.sandbox.registry import SandboxRegistry


class RunAutonomousLoopUseCase:
    """Orchestrates cyclical Forge engineer and Reviewer critic execution loop."""

    def __init__(
        self,
        task_repo: TaskRepository,
        task_run_repo: TaskRunRepository,
        sandbox_run_repo: SandboxRunRepository,
        review_iteration_repo: ReviewIterationRepository,
        audit_log_repo: AuditLogRepository,
        repository_repo: RepositoryRepository,
        sandbox_provider: SandboxProvider,
        github_gateway: GitHubGateway,
        forge_agent: ForgeAgent,
        reviewer_critic: ReviewerCritic,
        event_streamer: EventStreamer | None = None,
        task_transcript_repo: TaskTranscriptRepository | None = None,
        task_intervention_repo: TaskInterventionRepository | None = None,
        task_queue: TaskQueue | None = None,
        sandbox_registry: SandboxRegistry | None = None,
        organization_repo: OrganizationRepository | None = None,
        task_approval_repo: TaskApprovalRepository | None = None,
        usage_repo: UsageRepository | None = None,
    ) -> None:
        self._task_repo = task_repo
        self._task_run_repo = task_run_repo
        self._sandbox_run_repo = sandbox_run_repo
        self._review_iteration_repo = review_iteration_repo
        self._audit_log_repo = audit_log_repo
        self._repository_repo = repository_repo
        self._sandbox_provider = sandbox_provider
        self._github_gateway = github_gateway
        self._forge_agent = forge_agent
        self._reviewer_critic = reviewer_critic
        self._event_streamer = event_streamer
        self._task_transcript_repo = task_transcript_repo
        self._task_intervention_repo = task_intervention_repo
        self._task_queue = task_queue
        self._sandbox_registry = sandbox_registry
        self._policy_evaluator = PolicyEvaluator()

        session = getattr(repository_repo, "_session", None)
        self._organization_repo: OrganizationRepository | None = organization_repo or (
            SqlAlchemyOrganizationRepository(session) if session is not None else None
        )
        self._task_approval_repo: TaskApprovalRepository | None = (
            task_approval_repo
            or (
                SqlAlchemyTaskApprovalRepository(session)
                if session is not None
                else None
            )
        )
        self._usage_repo: UsageRepository = usage_repo or SqlAlchemyUsageRepository(
            session=session,
            isolated=(session is None),
        )
        self._usage_tracker = UsageTracker(self._usage_repo)

    async def _commit_if_isolated(self) -> None:
        if getattr(self._usage_repo, "_isolated", False):
            session = getattr(self._task_run_repo, "_session", None)
            if session is not None:
                await session.commit()

    async def _resolve_policy(
        self, org_id: uuid.UUID, repo: Repository, options: dict[str, Any]
    ) -> EffectiveGuardrailPolicy:
        org_settings: dict[str, Any] | None = None
        if self._organization_repo is not None:
            try:
                org = await self._organization_repo.get_by_id(org_id)
                org_settings = org.settings
            except Exception:
                org_settings = None
        policy = self._policy_evaluator.merge_policy(org_settings, repo.config)
        # Allow explicit test-harness option overrides if provided
        if options.get("policy_override") and isinstance(
            options["policy_override"], dict
        ):
            policy = self._policy_evaluator.merge_policy(
                policy.to_dict(), {"guardrails": options["policy_override"]}
            )
        return policy

    def _make_approval_checker(
        self,
        org_id: uuid.UUID,
        task_id: uuid.UUID,
        approved_hashes: set[str],
    ):
        async def _check(classification: RiskClassification) -> bool:
            if not classification.action_hash:
                return False
            if self._task_approval_repo is not None:
                found = await self._task_approval_repo.find_approved_unconsumed(
                    org_id, task_id, classification.action_hash
                )
                if found is not None:
                    await self._task_approval_repo.mark_consumed(org_id, found.id)
                    approved_hashes.add(classification.action_hash)
                    return True
            return classification.action_hash in approved_hashes

        return _check

    async def _halt_with_failure(
        self,
        *,
        org_id: uuid.UUID,
        task: Task,
        current_run: TaskRun,
        workspace: SandboxWorkspace | None,
        failure_reason: str,
        action_name: str,
        extra_audit: dict[str, Any] | None = None,
    ) -> Task:
        partial_diff = ""
        if workspace is not None:
            try:
                partial_diff = await workspace.get_diff()
            except Exception:
                partial_diff = ""

        cp = dict(current_run.checkpoint_state or {})
        if partial_diff:
            cp["partial_diff"] = partial_diff
            try:
                current_run = await self._task_run_repo.update_checkpoint(
                    org_id=org_id,
                    task_run_id=current_run.id,
                    checkpoint_state=cp,
                    expected_version=current_run.version,
                )
            except Exception:
                pass

        if self._event_streamer:
            await self._event_streamer.append_event(
                task.id,
                "task.log",
                {
                    "stream": "stderr",
                    "chunk": f"[guardrail:halt] Task halted ({failure_reason}).\n",
                },
            )
            if partial_diff:
                await self._event_streamer.append_event(
                    task.id,
                    "task.log",
                    {"stream": "stdout", "chunk": f"[partial_diff]\n{partial_diff}\n"},
                )

        run_tokens, run_cost_cents = await self._usage_repo.get_task_run_usage(
            org_id, current_run.id
        )
        effective_cost = max(run_cost_cents, current_run.estimated_cost_cents)
        await self._task_run_repo.complete_run(
            org_id=org_id,
            task_run_id=current_run.id,
            status="failed",
            prompt_tokens=current_run.prompt_tokens,
            completion_tokens=current_run.completion_tokens,
            estimated_cost_cents=effective_cost,
            failure_reason=failure_reason,
        )
        await self._task_repo.update_status(
            org_id=org_id, task_id=task.id, status="failed"
        )
        await self._audit_log_repo.record_event(
            org_id=org_id,
            actor_type="system",
            actor_id="agentsonair_engine",
            action=action_name,
            target_type="task",
            target_id=task.id,
            payload_after={
                "failure_reason": failure_reason,
                "estimated_cost_cents": effective_cost,
                "tokens_used": max(run_tokens, current_run.tokens_used),
                **(extra_audit or {}),
            },
        )
        if self._task_transcript_repo and self._event_streamer:
            try:
                (
                    terminal_text,
                    events_json,
                    total_lines,
                ) = await self._event_streamer.get_stream_transcript(task.id)
                compressed = gzip.compress(terminal_text.encode("utf-8"))
                await self._task_transcript_repo.create_or_update(
                    org_id=org_id,
                    task_id=task.id,
                    task_run_id=current_run.id,
                    terminal_log=compressed,
                    events_json=events_json,
                    total_lines=total_lines,
                )
            except Exception:
                pass
        if self._event_streamer:
            await self._event_streamer.append_event(
                task.id,
                "task.status",
                {
                    "status": "failed",
                    "failure_reason": failure_reason,
                    "reason": failure_reason,
                },
            )
        return await self._task_repo.get_by_id(org_id, task.id)

    async def execute(
        self,
        org_id: uuid.UUID,
        task_id: uuid.UUID,
        options: dict[str, Any] | None = None,
    ) -> Task:
        options = dict(options or {})

        # 1. Fetch task, repository, and effective guardrail policy
        task = await self._task_repo.get_by_id(org_id, task_id)
        repo = await self._repository_repo.get_by_id(org_id, task.repo_id)
        policy = await self._resolve_policy(org_id, repo, options)

        # 2. Transition task to in_progress and create run
        await self._task_repo.update_status(org_id, task_id, status="in_progress")
        task_run = await self._task_run_repo.create_run(org_id, task_id)
        await self._commit_if_isolated()

        # Preflight check before allocating sandbox if monthly org cap already hit
        preflight_halt = await self._usage_tracker.check_preflight(
            org_id, policy, task_run=task_run
        )
        if preflight_halt is not None:
            return await self._halt_with_failure(
                org_id=org_id,
                task=task,
                current_run=task_run,
                workspace=None,
                failure_reason=preflight_halt,
                action_name="task_failed_budget_preflight",
            )

        # 3. Sub-state allocating_sandbox (AC-3, AC-6, AC-7)
        if self._event_streamer:
            await self._event_streamer.append_event(
                task_id,
                "task.step",
                {"node": "sandbox_allocate", "status": "running"},
            )

        sandbox_timeout_seconds = policy.timeout_minutes * 60
        sandbox = await self._sandbox_provider.create_sandbox(
            org_id,
            task_id,
            timeout_seconds=sandbox_timeout_seconds,
            network_egress_mode=policy.network_egress_mode,
            allowed_egress_domains=policy.allowed_egress_domains,
        )
        await self._sandbox_run_repo.record_allocation(
            org_id=org_id,
            task_run_id=task_run.id,
            provider=sandbox.provider,
            sandbox_id=sandbox.id,
            timeout_seconds=sandbox_timeout_seconds,
        )

        if self._event_streamer:
            await self._event_streamer.append_event(
                task_id,
                "task.step",
                {"node": "sandbox_allocate", "status": "completed"},
            )

        approved_hashes: set[str] = set()
        workspace = SandboxWorkspace(
            sandbox,
            task_id,
            self._event_streamer,
            policy=policy,
            policy_evaluator=self._policy_evaluator,
            cycle_number=1,
            approval_checker=self._make_approval_checker(
                org_id, task_id, approved_hashes
            ),
        )
        release_without_terminate = False

        try:
            # 4. Sub-state workspace_init (AC-2, AC-3, AC-7)
            work_branch = (
                task.branch_name or f"agentsonair/task-{task.id.hex[:8]}-issue-1"
            )
            if self._event_streamer:
                await self._event_streamer.append_event(
                    task_id,
                    "task.step",
                    {"node": "repo_checkout", "status": "running"},
                )

            read_clone_url: str | None = options.get("repo_url_with_read_token")
            if read_clone_url is None and options.get("clone_with_read_token"):
                read_token = await self._github_gateway.get_installation_token(
                    repo.github_installation_id, write_access=False
                )
                read_clone_url = f"https://x-access-token:{read_token}@github.com/{repo.full_name}.git"

            install_command = options.get("install_command") or repo.config.get(
                "install_command"
            )
            await workspace.init_workspace(
                repo_url_with_read_token=read_clone_url,
                base_branch=task.base_branch,
                work_branch=work_branch,
                protected_branches=policy.protected_branches,
                install_command=install_command,
            )

            if self._event_streamer:
                await self._event_streamer.append_event(
                    task_id,
                    "task.step",
                    {"node": "repo_checkout", "status": "completed"},
                )

            # 5. Sub-state baseline_testing (AC-3)
            test_command = options.get("test_command") or repo.config.get(
                "test_command", "pytest"
            )

            if self._event_streamer:
                await self._event_streamer.append_event(
                    task_id,
                    "task.step",
                    {"node": "baseline_testing", "status": "running"},
                )

            try:
                remaining = self._usage_tracker.get_remaining_active_seconds(
                    task_run, policy
                )
                if remaining <= 0:
                    raise TaskTimeoutError("Active runtime budget exceeded")
                await asyncio.wait_for(
                    workspace.run_baseline_tests(test_command),
                    timeout=remaining,
                )
                if self._event_streamer:
                    await self._event_streamer.append_event(
                        task_id,
                        "task.step",
                        {"node": "baseline_testing", "status": "completed"},
                    )
            except (TimeoutError, TaskTimeoutError):
                return await self._halt_with_failure(
                    org_id=org_id,
                    task=task,
                    current_run=task_run,
                    workspace=workspace,
                    failure_reason="timeout_exceeded",
                    action_name="task_failed_timeout",
                )
            except BaselineTestFailedError as exc:
                await self._task_run_repo.complete_run(
                    org_id=org_id,
                    task_run_id=task_run.id,
                    status="failed",
                    failure_reason="baseline_tests_failed",
                )
                await self._task_repo.update_status(
                    org_id=org_id, task_id=task_id, status="failed"
                )
                await self._audit_log_repo.record_event(
                    org_id=org_id,
                    actor_type="system",
                    actor_id="agentsonair_engine",
                    action="task_failed_baseline",
                    target_type="task",
                    target_id=task.id,
                    payload_after={
                        "reason": "baseline_tests_failed",
                        "details": str(exc),
                    },
                )
                if self._event_streamer:
                    await self._event_streamer.append_event(
                        task_id,
                        "task.status",
                        {
                            "status": "failed",
                            "failure_reason": "baseline_tests_failed",
                            "reason": "baseline_tests_failed",
                        },
                    )
                return await self._task_repo.get_by_id(org_id, task_id)

            final_task, paused = await self._run_cycles(
                org_id=org_id,
                task=task,
                repo=repo,
                policy=policy,
                task_run=task_run,
                sandbox=sandbox,
                workspace=workspace,
                test_command=test_command,
                work_branch=work_branch,
                options=options,
                approved_hashes=approved_hashes,
            )
            if paused:
                release_without_terminate = True
            return final_task
        finally:
            if not release_without_terminate:
                if self._sandbox_registry is not None:
                    self._sandbox_registry.pop(sandbox.id)
                await sandbox.terminate()

    async def resume(
        self,
        org_id: uuid.UUID,
        task_id: uuid.UUID,
        response: str | dict[str, Any],
        intervention_id: uuid.UUID | None = None,
    ) -> Task:
        """Resume an interrupted task from its saved LangGraph checkpoint."""
        task = await self._task_repo.get_by_id(org_id, task_id)
        repo = await self._repository_repo.get_by_id(org_id, task.repo_id)
        task_run = await self._task_run_repo.get_latest_by_task(org_id, task_id)

        if intervention_id and self._task_intervention_repo:
            await self._task_intervention_repo.mark_applied(org_id, intervention_id)

        cp = dict(task_run.checkpoint_state or {})
        options = dict(cp.get("options") or {})
        policy = await self._resolve_policy(org_id, repo, options)

        # Accumulate paused_seconds so awaiting_input does not eat active runtime budget
        paused_at_iso = cp.get("paused_at")
        if isinstance(paused_at_iso, str):
            try:
                paused_at = datetime.fromisoformat(paused_at_iso)
                delta_paused = max(
                    0, int((datetime.now(UTC) - paused_at).total_seconds())
                )
                if delta_paused > 0:
                    task_run = await self._task_run_repo.increment_paused_seconds(
                        org_id, task_run.id, delta_paused
                    )
            except ValueError:
                pass

        cycle_number = int(cp.get("cycle_number", 1))
        work_branch = str(
            cp.get("work_branch")
            or task.branch_name
            or f"agentsonair/task-{task.id.hex[:8]}-issue-1"
        )
        previous_review = cp.get("previous_review")
        saved_langgraph = cp.get("langgraph")
        sandbox_id = cp.get("sandbox_id")
        partial_diff = cp.get("partial_diff")
        approved_hashes: set[str] = set(cp.get("approved_action_hashes") or [])

        # Parse structured approval payload if serialized as JSON
        parsed_response: str | dict[str, Any] = response
        if isinstance(response, str) and response.startswith("{"):
            try:
                maybe_dict = json.loads(response)
                if isinstance(maybe_dict, dict):
                    parsed_response = maybe_dict
            except json.JSONDecodeError:
                pass

        if (
            isinstance(parsed_response, dict)
            and parsed_response.get("approval_id")
            and self._task_approval_repo is not None
        ):
            try:
                approval = await self._task_approval_repo.get_by_id(
                    org_id, uuid.UUID(str(parsed_response["approval_id"]))
                )
                if approval.status == "approved":
                    # Wait to mark consumed until _make_approval_checker executes it;
                    # if not yet in checkpoint hashes, _make_approval_checker will find
                    # the unconsumed DB approval and stamp consumed_at.
                    pass
            except Exception:
                pass

        sandbox: SandboxSession | None = None
        if sandbox_id and self._sandbox_registry is not None:
            sandbox = self._sandbox_registry.pop(str(sandbox_id))

        if sandbox is None:
            remaining = max(
                60,
                int(self._usage_tracker.get_remaining_active_seconds(task_run, policy)),
            )
            sandbox = await self._sandbox_provider.create_sandbox(
                org_id,
                task_id,
                timeout_seconds=remaining,
                network_egress_mode=policy.network_egress_mode,
                allowed_egress_domains=policy.allowed_egress_domains,
            )
            workspace = SandboxWorkspace(
                sandbox,
                task_id,
                self._event_streamer,
                policy=policy,
                policy_evaluator=self._policy_evaluator,
                cycle_number=cycle_number,
                approval_checker=self._make_approval_checker(
                    org_id, task_id, approved_hashes
                ),
            )
            await workspace.init_workspace(
                repo_url_with_read_token=None,
                base_branch=task.base_branch,
                work_branch=work_branch,
                protected_branches=policy.protected_branches,
            )
            # Rehydrate uncommitted partial_diff when resumed on a different worker
            if isinstance(partial_diff, str) and partial_diff.strip():
                await sandbox.write_file(".aoa_partial.patch", partial_diff)
                await sandbox.execute_command(
                    "git apply --whitespace=nowarn .aoa_partial.patch "
                    "&& rm -f .aoa_partial.patch"
                )
        else:
            workspace = SandboxWorkspace(
                sandbox,
                task_id,
                self._event_streamer,
                policy=policy,
                policy_evaluator=self._policy_evaluator,
                cycle_number=cycle_number,
                approval_checker=self._make_approval_checker(
                    org_id, task_id, approved_hashes
                ),
            )

        test_command = options.get("test_command") or repo.config.get(
            "test_command", "pytest"
        )
        await self._task_run_repo.set_status(org_id, task_run.id, "running")
        await self._commit_if_isolated()

        release_without_terminate = False
        try:
            final_task, paused = await self._run_cycles(
                org_id=org_id,
                task=task,
                repo=repo,
                policy=policy,
                task_run=task_run,
                sandbox=sandbox,
                workspace=workspace,
                test_command=test_command,
                work_branch=work_branch,
                options=options,
                start_cycle=cycle_number,
                previous_review=previous_review,
                resume_response=parsed_response,
                saved_langgraph_state=saved_langgraph,
                approved_hashes=approved_hashes,
            )
            if paused:
                release_without_terminate = True
            return final_task
        finally:
            if not release_without_terminate:
                if self._sandbox_registry is not None:
                    self._sandbox_registry.pop(sandbox.id)
                await sandbox.terminate()

    async def _collect_guidance_messages(
        self, org_id: uuid.UUID, task_id: uuid.UUID
    ) -> list[str]:
        """Collect unapplied developer guidance messages and mark them applied."""
        if not self._task_intervention_repo:
            return []
        interventions = await self._task_intervention_repo.list_by_task(org_id, task_id)
        messages: list[str] = []
        for iv in interventions:
            if iv.intervention_type == "guidance" and iv.applied_at is None:
                msg = iv.payload.get("message")
                if isinstance(msg, str) and msg.strip():
                    messages.append(msg)
                await self._task_intervention_repo.mark_applied(org_id, iv.id)
        return messages

    async def _run_cycles(
        self,
        *,
        org_id: uuid.UUID,
        task: Task,
        repo: Repository,
        policy: EffectiveGuardrailPolicy,
        task_run: TaskRun,
        sandbox: SandboxSession,
        workspace: SandboxWorkspace,
        test_command: str,
        work_branch: str,
        options: dict[str, Any],
        start_cycle: int = 1,
        previous_review: dict[str, Any] | None = None,
        resume_response: str | dict[str, Any] | None = None,
        saved_langgraph_state: dict[str, Any] | None = None,
        approved_hashes: set[str] | None = None,
    ) -> tuple[Task, bool]:
        """Execute cyclical LangGraph Forge + Reviewer + Host Publish loop."""
        max_cycles = policy.max_cycles
        cycle_number = start_cycle
        current_run = task_run
        active_approved_hashes = (
            approved_hashes if approved_hashes is not None else set()
        )

        async def _preflight_hook() -> None:
            halt = await self._usage_tracker.check_preflight(
                org_id, policy, task_run=current_run
            )
            if halt == "budget_exceeded":
                raise BudgetExceededError("Spending cap reached before model call")
            if halt == "timeout_exceeded":
                raise TaskTimeoutError("Active runtime cap reached before model call")

        async def _record_usage(
            operation_type: str,
            provider: str,
            model: str,
            prompt_tokens: int,
            completion_tokens: int,
        ) -> None:
            result, halt_reason = await self._usage_tracker.record_call_and_check(
                org_id=org_id,
                provider=provider,
                model=model,
                operation_type=operation_type,
                prompt_tokens=prompt_tokens,
                completion_tokens=completion_tokens,
                policy=policy,
                task_id=task.id,
                task_run=current_run,
            )
            current_run.prompt_tokens += prompt_tokens
            current_run.completion_tokens += completion_tokens
            current_run.tokens_used = result.task_run_tokens_used
            current_run.estimated_cost_cents = result.task_run_cost_cents

            if self._event_streamer:
                await self._event_streamer.append_event(
                    task.id,
                    "task.budget_updated",
                    {
                        "task_cost_cents": result.task_run_cost_cents,
                        "max_task_cost_cents": policy.max_task_cost_cents,
                        "tokens_used": result.task_run_tokens_used,
                        "org_month_cost_cents": result.org_month_cost_cents,
                        "max_monthly_org_cost_cents": policy.max_monthly_org_cost_cents,
                    },
                )
            if halt_reason == "budget_exceeded":
                raise BudgetExceededError("Spending cap exceeded after model call")
            if halt_reason == "timeout_exceeded":
                raise TaskTimeoutError("Active runtime cap exceeded after model call")

        async def _on_forge_usage(res: ForgeResult) -> None:
            await _record_usage(
                "forge",
                res.provider,
                res.model,
                res.prompt_tokens,
                res.completion_tokens,
            )

        async def _on_reviewer_usage(res: ReviewerResult) -> None:
            await _record_usage(
                "reviewer",
                res.provider,
                res.model,
                res.prompt_tokens,
                res.completion_tokens,
            )

        checkpointer = PostgresTaskCheckpointSaver()
        graph = build_task_cycle_graph(
            self._forge_agent,
            self._reviewer_critic,
            workspace,
            checkpointer,
            github_gateway=self._github_gateway,
            policy=policy,
            preflight_hook=_preflight_hook,
            on_forge_usage=_on_forge_usage,
            on_reviewer_usage=_on_reviewer_usage,
            approval_checker=self._make_approval_checker(
                org_id, task.id, active_approved_hashes
            ),
        )

        final_graph_output: dict[str, Any] = {}
        while cycle_number <= max_cycles:
            workspace.cycle_number = cycle_number
            cur_task = await self._task_repo.get_by_id(org_id, task.id)
            if cur_task.status == "cancelled":
                return cur_task, False

            guidance_messages = await self._collect_guidance_messages(org_id, task.id)

            task_context = {
                "task_id": str(task.id),
                "title": task.title,
                "description": task.description,
                "repo_full_name": repo.full_name,
                "github_installation_id": repo.github_installation_id,
                "base_branch": task.base_branch,
                "work_branch": work_branch,
                "test_command": test_command,
                "cycle_number": cycle_number,
                "target_file": options.get("target_file", "src/solution.py"),
                "force_review_critical": options.get("force_review_critical", False),
                "force_push": options.get("force_push", False),
            }
            for opt_key in (
                "risky_command",
                "risky_write_path",
                "risky_write_content",
                "simulated_model",
                "simulated_prompt_tokens",
                "simulated_completion_tokens",
                "simulated_reviewer_prompt_tokens",
                "simulated_reviewer_completion_tokens",
            ):
                if opt_key in options:
                    task_context[opt_key] = options[opt_key]

            thread_id = f"{task_run.id}:cycle:{cycle_number}"
            config: Any = {"configurable": {"thread_id": thread_id}}

            is_resuming_cycle = (
                resume_response is not None
                and saved_langgraph_state is not None
                and cycle_number == start_cycle
            )

            if self._event_streamer:
                await self._event_streamer.append_event(
                    task.id,
                    "task.step",
                    {
                        "node": "forge_react_loop",
                        "status": "running",
                        "cycle": cycle_number,
                    },
                )

            remaining_seconds = self._usage_tracker.get_remaining_active_seconds(
                current_run, policy
            )
            if remaining_seconds <= 0:
                halted = await self._halt_with_failure(
                    org_id=org_id,
                    task=task,
                    current_run=current_run,
                    workspace=workspace,
                    failure_reason="timeout_exceeded",
                    action_name="task_failed_timeout",
                )
                return halted, False

            try:
                if is_resuming_cycle and saved_langgraph_state is not None:
                    checkpointer.import_thread_state(thread_id, saved_langgraph_state)
                    graph_output = await asyncio.wait_for(
                        graph.ainvoke(
                            Command(resume=resume_response),
                            config=config,
                        ),
                        timeout=remaining_seconds,
                    )
                    resume_response = None
                    saved_langgraph_state = None
                else:
                    needs_clarification = bool(
                        options.get("simulate_clarification")
                        and cycle_number == 1
                        and resume_response is None
                    )
                    prompt = str(
                        options.get(
                            "clarification_prompt",
                            "Please confirm target database dialect.",
                        )
                    )
                    opts = list(
                        options.get("clarification_options", ["PostgreSQL", "SQLite"])
                    )
                    initial_state: TaskGraphState = {
                        "task_id": str(task.id),
                        "org_id": str(org_id),
                        "cycle_number": cycle_number,
                        "task_context": task_context,
                        "previous_review": previous_review,
                        "clarification_needed": needs_clarification,
                        "clarification_prompt": prompt,
                        "clarification_options": opts,
                        "clarification_response": None,
                        "guidance_messages": guidance_messages,
                        "approved_action_hashes": sorted(active_approved_hashes),
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
                    }
                    graph_output = await asyncio.wait_for(
                        graph.ainvoke(initial_state, config=config),
                        timeout=remaining_seconds,
                    )
            except BudgetExceededError:
                halted = await self._halt_with_failure(
                    org_id=org_id,
                    task=task,
                    current_run=current_run,
                    workspace=workspace,
                    failure_reason="budget_exceeded",
                    action_name="task_failed_budget_exceeded",
                )
                return halted, False
            except (TimeoutError, TaskTimeoutError):
                halted = await self._halt_with_failure(
                    org_id=org_id,
                    task=task,
                    current_run=current_run,
                    workspace=workspace,
                    failure_reason="timeout_exceeded",
                    action_name="task_failed_timeout",
                )
                return halted, False
            except ProtectedBranchError as exc:
                halted = await self._halt_with_failure(
                    org_id=org_id,
                    task=task,
                    current_run=current_run,
                    workspace=workspace,
                    failure_reason="protected_branch_blocked",
                    action_name="task_failed_protected_branch",
                    extra_audit={"details": str(exc), "branch": work_branch},
                )
                return halted, False
            except GuardrailBlockedError as exc:
                halted = await self._halt_with_failure(
                    org_id=org_id,
                    task=task,
                    current_run=current_run,
                    workspace=workspace,
                    failure_reason=exc.reason,
                    action_name="task_failed_guardrail_blocked",
                    extra_audit={"details": str(exc)},
                )
                return halted, False

            if "__interrupt__" in graph_output:
                interrupts = graph_output["__interrupt__"]
                interrupt_payload = (
                    interrupts[0].value
                    if interrupts and hasattr(interrupts[0], "value")
                    else {}
                )
                prompt = str(
                    interrupt_payload.get(
                        "prompt", "Please confirm target database dialect."
                    )
                )
                opts = list(interrupt_payload.get("options", ["PostgreSQL", "SQLite"]))
                interruption_type = str(
                    interrupt_payload.get("interruption_type", "clarification")
                )

                if (
                    options.get("auto_resume_delay") is not None
                    and interruption_type != "approval"
                ):
                    expires_at = datetime.now(UTC) + timedelta(
                        seconds=settings.INTERRUPTION_TIMEOUT_SECONDS
                    )
                    await self._task_repo.set_interruption(
                        org_id=org_id,
                        task_id=task.id,
                        prompt=prompt,
                        interruption_type=interruption_type,
                        options=opts,
                        expires_at=expires_at,
                    )
                    if self._event_streamer:
                        await self._event_streamer.append_event(
                            task.id,
                            "task.interrupted",
                            {
                                "prompt": prompt,
                                "options": opts,
                                "interruption_type": interruption_type,
                                "expires_at": expires_at.isoformat(),
                            },
                        )
                    await asyncio.sleep(float(options["auto_resume_delay"]))
                    await self._task_repo.clear_interruption(
                        org_id, task.id, new_status="in_progress"
                    )
                    answer = str(options.get("auto_resume_answer", "PostgreSQL"))
                    if self._event_streamer:
                        await self._event_streamer.append_event(
                            task.id,
                            "task.resumed",
                            {"response": answer},
                        )
                    graph_output = await graph.ainvoke(
                        Command(resume=answer),
                        config=config,
                    )
                else:
                    default_timeout = (
                        settings.approval_timeout_seconds
                        if interruption_type == "approval"
                        else settings.INTERRUPTION_TIMEOUT_SECONDS
                    )
                    timeout_seconds = int(
                        options.get("interruption_timeout_seconds", default_timeout)
                    )
                    await sandbox.extend_timeout(timeout_seconds)
                    await self._sandbox_run_repo.update_timeout(
                        org_id, current_run.id, timeout_seconds
                    )
                    if self._sandbox_registry is not None:
                        self._sandbox_registry.register(sandbox.id, sandbox)

                    partial_diff = ""
                    try:
                        partial_diff = await workspace.get_diff()
                    except Exception:
                        partial_diff = ""

                    expires_at = datetime.now(UTC) + timedelta(seconds=timeout_seconds)
                    exported_graph = checkpointer.export_thread_state(thread_id)
                    checkpoint_payload = {
                        "cycle_number": cycle_number,
                        "work_branch": work_branch,
                        "sandbox_id": sandbox.id,
                        "options": options,
                        "previous_review": previous_review,
                        "partial_diff": partial_diff,
                        "approved_action_hashes": sorted(active_approved_hashes),
                        "paused_at": datetime.now(UTC).isoformat(),
                        "langgraph": exported_graph,
                    }
                    current_run = await self._task_run_repo.update_checkpoint(
                        org_id=org_id,
                        task_run_id=current_run.id,
                        checkpoint_state=checkpoint_payload,
                        expected_version=current_run.version,
                    )
                    await self._task_run_repo.set_status(
                        org_id, current_run.id, "awaiting_input"
                    )

                    approval_id_str: str | None = None
                    if (
                        interruption_type == "approval"
                        and self._task_approval_repo is not None
                    ):
                        risk_cat = str(
                            interrupt_payload.get("risk_category", "destructive_shell")
                        )
                        act_type = str(
                            interrupt_payload.get("action_type", "sandbox_command")
                        )
                        act_hash = str(interrupt_payload.get("action_hash", ""))
                        act_summary = str(
                            interrupt_payload.get("action_summary", prompt)
                        )
                        act_payload = dict(
                            interrupt_payload.get("action_payload") or {}
                        )
                        approval = await self._task_approval_repo.create_pending(
                            org_id=org_id,
                            task_id=task.id,
                            task_run_id=current_run.id,
                            risk_category=risk_cat,
                            action_type=act_type,
                            action_hash=act_hash,
                            action_summary=act_summary,
                            action_payload=act_payload,
                            expires_at=expires_at,
                        )
                        approval_id_str = str(approval.id)
                        await self._audit_log_repo.record_event(
                            org_id=org_id,
                            actor_type="system",
                            actor_id="agentsonair_engine",
                            action="task_approval_requested",
                            target_type="task_approval",
                            target_id=approval.id,
                            payload_after={
                                "task_id": str(task.id),
                                "risk_category": risk_cat,
                                "action_type": act_type,
                                "action_hash": act_hash,
                                "action_summary": act_summary,
                            },
                        )

                    await self._task_repo.set_interruption(
                        org_id=org_id,
                        task_id=task.id,
                        prompt=prompt,
                        interruption_type=interruption_type,
                        options=opts,
                        expires_at=expires_at,
                    )
                    if self._event_streamer:
                        if interruption_type == "approval":
                            await self._event_streamer.append_event(
                                task.id,
                                "task.approval_requested",
                                {
                                    "approval_id": approval_id_str,
                                    "risk_category": interrupt_payload.get(
                                        "risk_category"
                                    ),
                                    "action_type": interrupt_payload.get("action_type"),
                                    "action_summary": interrupt_payload.get(
                                        "action_summary", prompt
                                    ),
                                    "action_payload": interrupt_payload.get(
                                        "action_payload", {}
                                    ),
                                    "expires_at": expires_at.isoformat(),
                                },
                            )
                        await self._event_streamer.append_event(
                            task.id,
                            "task.interrupted",
                            {
                                "prompt": prompt,
                                "options": opts,
                                "interruption_type": interruption_type,
                                "approval_id": approval_id_str,
                                "expires_at": expires_at.isoformat(),
                            },
                        )
                    if self._task_queue is not None:
                        await self._task_queue.schedule_interruption_watchdog(
                            org_id=org_id,
                            task_id=task.id,
                            expires_at=expires_at,
                            delay_seconds=timeout_seconds,
                        )

                    paused_task = await self._task_repo.get_by_id(org_id, task.id)
                    return paused_task, True

            if self._event_streamer:
                await self._event_streamer.append_event(
                    task.id,
                    "task.step",
                    {
                        "node": "reviewer_evaluating",
                        "status": "running",
                        "cycle": cycle_number,
                    },
                )

            final_forge_result = ForgeResult(
                completed=bool(graph_output.get("forge_completed", True)),
                summary=str(graph_output.get("forge_summary", "")),
                steps_taken=int(graph_output.get("forge_steps_taken", 0)),
                test_output=str(graph_output.get("forge_test_output", "")),
                diff=str(graph_output.get("forge_diff", "")),
            )

            checkpoint = {
                "cycle_number": cycle_number,
                "steps": final_forge_result.steps_taken,
                "diff": final_forge_result.diff,
                "approved_action_hashes": sorted(active_approved_hashes),
            }
            current_run = await self._task_run_repo.update_checkpoint(
                org_id=org_id,
                task_run_id=current_run.id,
                checkpoint_state=checkpoint,
                expected_version=current_run.version,
            )
            await self._commit_if_isolated()

            blocking_count = int(graph_output.get("review_blocking_count", 0))
            non_blocking_count = int(graph_output.get("review_non_blocking_count", 0))
            verdict = str(graph_output.get("review_verdict", "approved"))
            review_summary = str(graph_output.get("review_summary", ""))
            findings = list(graph_output.get("review_findings", []))

            await self._review_iteration_repo.create(
                org_id=org_id,
                task_run_id=current_run.id,
                cycle_number=cycle_number,
                verdict=verdict,
                summary=review_summary,
                findings=findings,
                blocking_count=blocking_count,
                non_blocking_count=non_blocking_count,
                diff_snapshot=final_forge_result.diff,
            )

            if blocking_count > 0:
                if cycle_number < max_cycles:
                    cycle_number += 1
                    previous_review = {
                        "verdict": verdict,
                        "summary": review_summary,
                        "findings": findings,
                    }
                    if options.get("clear_critical_on_cycle_2") and cycle_number == 2:
                        options["force_review_critical"] = False
                    continue
                halted = await self._halt_with_failure(
                    org_id=org_id,
                    task=task,
                    current_run=current_run,
                    workspace=workspace,
                    failure_reason="review_cycle_limit_exhausted",
                    action_name="task_failed_cycle_limit",
                    extra_audit={"cycles": max_cycles, "findings": findings},
                )
                return halted, False

            final_graph_output = graph_output
            break

        # 7. Finalize PR details produced by host_publish_node
        pr_url = str(final_graph_output.get("pr_url") or "")
        pr_number = int(final_graph_output.get("pr_number") or 0)
        commit_sha = str(final_graph_output.get("commit_sha") or "")

        await self._task_repo.update_pr_details(
            org_id=org_id,
            task_id=task.id,
            pr_url=pr_url,
            head_commit_sha=commit_sha,
            pr_review_status="approved",
            pr_number=pr_number,
            branch_name=work_branch,
        )
        await self._task_repo.update_status(
            org_id=org_id,
            task_id=task.id,
            status="completed",
            branch_name=work_branch,
            pr_number=pr_number,
        )
        run_tokens, run_cost_cents = await self._usage_repo.get_task_run_usage(
            org_id, current_run.id
        )
        await self._task_run_repo.complete_run(
            org_id=org_id,
            task_run_id=current_run.id,
            status="completed",
            prompt_tokens=current_run.prompt_tokens,
            completion_tokens=current_run.completion_tokens,
            estimated_cost_cents=max(run_cost_cents, current_run.estimated_cost_cents),
        )
        await self._audit_log_repo.record_event(
            org_id=org_id,
            actor_type="system",
            actor_id="agentsonair_engine",
            action="task_completed_pr_created",
            target_type="task",
            target_id=task.id,
            payload_after={
                "pr_url": pr_url,
                "commit_sha": commit_sha,
                "branch": work_branch,
                "cycles": cycle_number,
                "tokens_used": max(run_tokens, current_run.tokens_used),
                "estimated_cost_cents": max(
                    run_cost_cents, current_run.estimated_cost_cents
                ),
            },
        )

        # Archive execution transcript to database if repository available
        if self._task_transcript_repo and self._event_streamer:
            try:
                (
                    terminal_text,
                    events_json,
                    total_lines,
                ) = await self._event_streamer.get_stream_transcript(task.id)
                compressed = gzip.compress(terminal_text.encode("utf-8"))
                await self._task_transcript_repo.create_or_update(
                    org_id=org_id,
                    task_id=task.id,
                    task_run_id=current_run.id,
                    terminal_log=compressed,
                    events_json=events_json,
                    total_lines=total_lines,
                )
            except Exception:
                pass

        if self._event_streamer:
            await self._event_streamer.append_event(
                task.id,
                "task.status",
                {"status": "completed", "pr_url": pr_url},
            )

        return await self._task_repo.get_by_id(org_id, task.id), False
