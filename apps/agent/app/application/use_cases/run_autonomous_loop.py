"""Cyclical autonomous engineer and reviewer execution loop use case."""

import uuid

from app.application.ports.audit_log_repository import AuditLogRepository
from app.application.ports.event_streamer import EventStreamer
from app.application.ports.github_gateway import GitHubGateway
from app.application.ports.model_gateway import ForgeAgent, ReviewerCritic
from app.application.ports.repository_repository import RepositoryRepository
from app.application.ports.review_iteration_repository import (
    ReviewIterationRepository,
)
from app.application.ports.sandbox import SandboxProvider
from app.application.ports.sandbox_run_repository import SandboxRunRepository
from app.application.ports.task_repository import TaskRepository
from app.application.ports.task_run_repository import TaskRunRepository
from app.application.services.sandbox_workspace import SandboxWorkspace
from app.domain.entities.task import Task
from app.domain.exceptions import BaselineTestFailedError


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

    async def execute(
        self,
        org_id: uuid.UUID,
        task_id: uuid.UUID,
        options: dict | None = None,
    ) -> Task:
        options = options or {}

        # 1. Fetch task and repository context
        task = await self._task_repo.get_by_id(org_id, task_id)
        repo = await self._repository_repo.get_by_id(org_id, task.repo_id)

        # 2. Transition task to in_progress and create run
        await self._task_repo.update_status(org_id, task_id, status="in_progress")
        task_run = await self._task_run_repo.create_run(org_id, task_id)

        # 3. Sub-state allocating_sandbox (AC-3)
        sandbox = await self._sandbox_provider.create_sandbox(org_id, task_id)
        await self._sandbox_run_repo.record_allocation(
            org_id=org_id,
            task_run_id=task_run.id,
            provider=sandbox.provider,
            sandbox_id=sandbox.id,
        )

        workspace = SandboxWorkspace(sandbox, task_id, self._event_streamer)

        try:
            # 4. Sub-state workspace_init (AC-3)
            work_branch = (
                task.branch_name or f"agentsonair/task-{task.id.hex[:8]}-issue-1"
            )
            await workspace.init_workspace(
                repo_url_with_read_token=None,
                base_branch=task.base_branch,
                work_branch=work_branch,
            )

            # 5. Sub-state baseline_testing (AC-3)
            test_command = options.get("test_command") or repo.config.get(
                "test_command", "pytest"
            )

            try:
                await workspace.run_baseline_tests(test_command)
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
                return await self._task_repo.get_by_id(org_id, task_id)

            # 6. Cyclical LangGraph loop (Forge coder + Reviewer critic) (AC-2, AC-4)
            max_cycles = 3
            cycle_number = 1
            previous_review = None
            final_forge_result = None

            while cycle_number <= max_cycles:
                task_context = {
                    "task_id": str(task.id),
                    "title": task.title,
                    "description": task.description,
                    "base_branch": task.base_branch,
                    "work_branch": work_branch,
                    "test_command": test_command,
                    "cycle_number": cycle_number,
                    "target_file": options.get("target_file", "src/solution.py"),
                    "force_review_critical": options.get(
                        "force_review_critical", False
                    ),
                }

                # Sub-state forge_react_loop
                forge_result = await self._forge_agent.run_cycle(
                    task_context, previous_review, workspace
                )
                final_forge_result = forge_result

                checkpoint = {
                    "cycle_number": cycle_number,
                    "steps": forge_result.steps_taken,
                    "diff": forge_result.diff,
                }
                await self._task_run_repo.update_checkpoint(
                    org_id=org_id,
                    task_run_id=task_run.id,
                    checkpoint_state=checkpoint,
                    expected_version=cycle_number,
                )

                # Sub-state reviewer_evaluating
                review_result = await self._reviewer_critic.evaluate(
                    task_context,
                    forge_result.diff,
                    forge_result.test_output,
                )

                await self._review_iteration_repo.create(
                    org_id=org_id,
                    task_run_id=task_run.id,
                    cycle_number=cycle_number,
                    verdict=review_result.verdict,
                    summary=review_result.summary,
                    findings=review_result.findings,
                    blocking_count=review_result.blocking_count,
                    non_blocking_count=review_result.non_blocking_count,
                    diff_snapshot=forge_result.diff,
                )

                if review_result.blocking_count > 0:
                    if cycle_number < max_cycles:
                        # Outer repair cycle triggered
                        cycle_number += 1
                        previous_review = {
                            "verdict": review_result.verdict,
                            "summary": review_result.summary,
                            "findings": review_result.findings,
                        }
                        # If a multi-cycle simulation was testing loop iteration repair,
                        # clear force_review_critical on subsequent cycle
                        if (
                            options.get("clear_critical_on_cycle_2")
                            and cycle_number == 2
                        ):
                            options["force_review_critical"] = False
                        continue
                    else:
                        # Cycle limit cap exhausted
                        await self._task_run_repo.complete_run(
                            org_id=org_id,
                            task_run_id=task_run.id,
                            status="failed",
                            failure_reason="review_cycle_limit_exhausted",
                        )
                        await self._task_repo.update_status(
                            org_id=org_id, task_id=task_id, status="failed"
                        )
                        await self._audit_log_repo.record_event(
                            org_id=org_id,
                            actor_type="system",
                            actor_id="agentsonair_engine",
                            action="task_failed_cycle_limit",
                            target_type="task",
                            target_id=task.id,
                            payload_after={
                                "reason": "review_cycle_limit_exhausted",
                                "cycles": max_cycles,
                                "findings": review_result.findings,
                            },
                        )
                        return await self._task_repo.get_by_id(org_id, task_id)
                else:
                    # Approved with 0 blocking findings
                    break

            # 7. Sub-state host_commit_push and Pull Request creation (AC-5)
            diff_text = final_forge_result.diff if final_forge_result else ""
            write_token = await self._github_gateway.get_installation_token(
                repo.github_installation_id, write_access=True
            )
            commit_msg = (
                f"fix: {task.title}\n\n"
                f"Co-authored-by: agentsonair[bot] <bot@agentsonair.dev>"
            )
            commit_sha = await self._github_gateway.push_branch(
                repo.full_name,
                work_branch,
                commit_msg,
                write_token,
                diff_text,
            )

            pr_title = f"fix: {task.title}"
            pr_body = (
                f"## Summary\n\n"
                f"Automated verified fix implemented by agentsOnAir.\n\n"
                f"### Task\n{task.description}\n\n"
                f"### Changes\n"
                f"{final_forge_result.summary if final_forge_result else ''}\n\n"
                f"### Review Verdict\n"
                f"Approved on cycle {cycle_number} with zero blocking findings."
            )
            pr_data = await self._github_gateway.create_pull_request(
                repo.full_name,
                task.base_branch,
                work_branch,
                pr_title,
                pr_body,
                write_token,
            )

            # Update task and run to completed
            await self._task_repo.update_pr_details(
                org_id=org_id,
                task_id=task_id,
                pr_url=str(pr_data["pr_url"]),
                head_commit_sha=commit_sha,
                pr_review_status="approved",
                pr_number=int(pr_data["pr_number"]),
                branch_name=work_branch,
            )
            await self._task_repo.update_status(
                org_id=org_id,
                task_id=task_id,
                status="completed",
                branch_name=work_branch,
                pr_number=int(pr_data["pr_number"]),
            )
            await self._task_run_repo.complete_run(
                org_id=org_id,
                task_run_id=task_run.id,
                status="completed",
            )
            await self._audit_log_repo.record_event(
                org_id=org_id,
                actor_type="system",
                actor_id="agentsonair_engine",
                action="task_completed_pr_created",
                target_type="task",
                target_id=task.id,
                payload_after={
                    "pr_url": pr_data["pr_url"],
                    "commit_sha": commit_sha,
                    "branch": work_branch,
                    "cycles": cycle_number,
                },
            )

            return await self._task_repo.get_by_id(org_id, task_id)
        finally:
            await sandbox.terminate()
