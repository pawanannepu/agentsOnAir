"""Cyclical autonomous engineer and reviewer execution loop use case."""

import asyncio
import gzip
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
)
from app.application.ports.repository_repository import RepositoryRepository
from app.application.ports.review_iteration_repository import (
    ReviewIterationRepository,
)
from app.application.ports.sandbox import SandboxProvider, SandboxSession
from app.application.ports.sandbox_run_repository import SandboxRunRepository
from app.application.ports.task_intervention_repository import (
    TaskInterventionRepository,
)
from app.application.ports.task_queue import TaskQueue
from app.application.ports.task_repository import TaskRepository
from app.application.ports.task_run_repository import TaskRunRepository
from app.application.ports.task_transcript_repository import (
    TaskTranscriptRepository,
)
from app.application.services.sandbox_workspace import SandboxWorkspace
from app.core.config import settings
from app.domain.entities.repository import Repository
from app.domain.entities.task import Task
from app.domain.entities.task_run import TaskRun
from app.domain.exceptions import BaselineTestFailedError
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

    async def execute(
        self,
        org_id: uuid.UUID,
        task_id: uuid.UUID,
        options: dict[str, Any] | None = None,
    ) -> Task:
        options = dict(options or {})

        # 1. Fetch task and repository context
        task = await self._task_repo.get_by_id(org_id, task_id)
        repo = await self._repository_repo.get_by_id(org_id, task.repo_id)

        # 2. Transition task to in_progress and create run
        await self._task_repo.update_status(org_id, task_id, status="in_progress")
        task_run = await self._task_run_repo.create_run(org_id, task_id)

        # 3. Sub-state allocating_sandbox (AC-3)
        if self._event_streamer:
            await self._event_streamer.append_event(
                task_id,
                "task.step",
                {"node": "sandbox_allocate", "status": "running"},
            )

        sandbox = await self._sandbox_provider.create_sandbox(org_id, task_id)
        await self._sandbox_run_repo.record_allocation(
            org_id=org_id,
            task_run_id=task_run.id,
            provider=sandbox.provider,
            sandbox_id=sandbox.id,
        )

        if self._event_streamer:
            await self._event_streamer.append_event(
                task_id,
                "task.step",
                {"node": "sandbox_allocate", "status": "completed"},
            )

        workspace = SandboxWorkspace(sandbox, task_id, self._event_streamer)
        release_without_terminate = False

        try:
            # 4. Sub-state workspace_init (AC-3)
            work_branch = (
                task.branch_name or f"agentsonair/task-{task.id.hex[:8]}-issue-1"
            )
            if self._event_streamer:
                await self._event_streamer.append_event(
                    task_id,
                    "task.step",
                    {"node": "repo_checkout", "status": "running"},
                )

            await workspace.init_workspace(
                repo_url_with_read_token=None,
                base_branch=task.base_branch,
                work_branch=work_branch,
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
                await workspace.run_baseline_tests(test_command)
                if self._event_streamer:
                    await self._event_streamer.append_event(
                        task_id,
                        "task.step",
                        {"node": "baseline_testing", "status": "completed"},
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
                        {"status": "failed", "reason": "baseline_tests_failed"},
                    )
                return await self._task_repo.get_by_id(org_id, task_id)

            final_task, paused = await self._run_cycles(
                org_id=org_id,
                task=task,
                repo=repo,
                task_run=task_run,
                sandbox=sandbox,
                workspace=workspace,
                test_command=test_command,
                work_branch=work_branch,
                options=options,
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
        response: str,
        intervention_id: uuid.UUID | None = None,
    ) -> Task:
        """Resume an interrupted task from its saved LangGraph checkpoint."""
        task = await self._task_repo.get_by_id(org_id, task_id)
        repo = await self._repository_repo.get_by_id(org_id, task.repo_id)
        task_run = await self._task_run_repo.get_latest_by_task(org_id, task_id)

        if intervention_id and self._task_intervention_repo:
            await self._task_intervention_repo.mark_applied(org_id, intervention_id)

        cp = dict(task_run.checkpoint_state or {})
        cycle_number = int(cp.get("cycle_number", 1))
        work_branch = str(
            cp.get("work_branch")
            or task.branch_name
            or f"agentsonair/task-{task.id.hex[:8]}-issue-1"
        )
        options = dict(cp.get("options") or {})
        previous_review = cp.get("previous_review")
        saved_langgraph = cp.get("langgraph")
        sandbox_id = cp.get("sandbox_id")

        sandbox: SandboxSession | None = None
        if sandbox_id and self._sandbox_registry is not None:
            sandbox = self._sandbox_registry.pop(str(sandbox_id))

        if sandbox is None:
            sandbox = await self._sandbox_provider.create_sandbox(org_id, task_id)
            workspace = SandboxWorkspace(sandbox, task_id, self._event_streamer)
            await workspace.init_workspace(
                repo_url_with_read_token=None,
                base_branch=task.base_branch,
                work_branch=work_branch,
            )
        else:
            workspace = SandboxWorkspace(sandbox, task_id, self._event_streamer)

        test_command = options.get("test_command") or repo.config.get(
            "test_command", "pytest"
        )
        await self._task_run_repo.set_status(org_id, task_run.id, "running")

        release_without_terminate = False
        try:
            final_task, paused = await self._run_cycles(
                org_id=org_id,
                task=task,
                repo=repo,
                task_run=task_run,
                sandbox=sandbox,
                workspace=workspace,
                test_command=test_command,
                work_branch=work_branch,
                options=options,
                start_cycle=cycle_number,
                previous_review=previous_review,
                resume_response=response,
                saved_langgraph_state=saved_langgraph,
            )
            if paused:
                release_without_terminate = True
            return final_task
        finally:
            if not release_without_terminate:
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
        task_run: TaskRun,
        sandbox: SandboxSession,
        workspace: SandboxWorkspace,
        test_command: str,
        work_branch: str,
        options: dict[str, Any],
        start_cycle: int = 1,
        previous_review: dict[str, Any] | None = None,
        resume_response: str | None = None,
        saved_langgraph_state: dict[str, Any] | None = None,
    ) -> tuple[Task, bool]:
        """Execute cyclical LangGraph Forge + Reviewer loop.

        Returns (task, paused) where paused=True indicates worker release.
        """
        max_cycles = 3
        cycle_number = start_cycle
        current_run = task_run
        final_forge_result: ForgeResult | None = None

        checkpointer = PostgresTaskCheckpointSaver()
        graph = build_task_cycle_graph(
            self._forge_agent,
            self._reviewer_critic,
            workspace,
            checkpointer,
        )

        while cycle_number <= max_cycles:
            cur_task = await self._task_repo.get_by_id(org_id, task.id)
            if cur_task.status == "cancelled":
                return cur_task, False

            guidance_messages = await self._collect_guidance_messages(org_id, task.id)

            task_context = {
                "task_id": str(task.id),
                "title": task.title,
                "description": task.description,
                "base_branch": task.base_branch,
                "work_branch": work_branch,
                "test_command": test_command,
                "cycle_number": cycle_number,
                "target_file": options.get("target_file", "src/solution.py"),
                "force_review_critical": options.get("force_review_critical", False),
            }

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

            if is_resuming_cycle and saved_langgraph_state is not None:
                checkpointer.import_thread_state(thread_id, saved_langgraph_state)
                graph_output = await graph.ainvoke(
                    Command(resume=resume_response),
                    config=config,
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
                }
                graph_output = await graph.ainvoke(initial_state, config=config)

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

                if options.get("auto_resume_delay") is not None:
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
                    timeout_seconds = int(
                        options.get(
                            "interruption_timeout_seconds",
                            settings.INTERRUPTION_TIMEOUT_SECONDS,
                        )
                    )
                    await sandbox.extend_timeout(timeout_seconds)
                    await self._sandbox_run_repo.update_timeout(
                        org_id, current_run.id, timeout_seconds
                    )
                    if self._sandbox_registry is not None:
                        self._sandbox_registry.register(sandbox.id, sandbox)

                    exported_graph = checkpointer.export_thread_state(thread_id)
                    checkpoint_payload = {
                        "cycle_number": cycle_number,
                        "work_branch": work_branch,
                        "sandbox_id": sandbox.id,
                        "options": options,
                        "previous_review": previous_review,
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

                    expires_at = datetime.now(UTC) + timedelta(seconds=timeout_seconds)
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
            }
            current_run = await self._task_run_repo.update_checkpoint(
                org_id=org_id,
                task_run_id=current_run.id,
                checkpoint_state=checkpoint,
                expected_version=current_run.version,
            )

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
                else:
                    await self._task_run_repo.complete_run(
                        org_id=org_id,
                        task_run_id=current_run.id,
                        status="failed",
                        failure_reason="review_cycle_limit_exhausted",
                    )
                    await self._task_repo.update_status(
                        org_id=org_id, task_id=task.id, status="failed"
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
                            "findings": findings,
                        },
                    )
                    if self._event_streamer:
                        await self._event_streamer.append_event(
                            task.id,
                            "task.status",
                            {
                                "status": "failed",
                                "reason": "review_cycle_limit_exhausted",
                            },
                        )
                    return await self._task_repo.get_by_id(org_id, task.id), False
            else:
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

        await self._task_repo.update_pr_details(
            org_id=org_id,
            task_id=task.id,
            pr_url=str(pr_data["pr_url"]),
            head_commit_sha=commit_sha,
            pr_review_status="approved",
            pr_number=int(pr_data["pr_number"]),
            branch_name=work_branch,
        )
        await self._task_repo.update_status(
            org_id=org_id,
            task_id=task.id,
            status="completed",
            branch_name=work_branch,
            pr_number=int(pr_data["pr_number"]),
        )
        await self._task_run_repo.complete_run(
            org_id=org_id,
            task_run_id=current_run.id,
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
                {"status": "completed", "pr_url": str(pr_data["pr_url"])},
            )

        return await self._task_repo.get_by_id(org_id, task.id), False
