"""LangGraph human in the loop execution state machine with Postgres persistence."""

import base64
from collections import defaultdict
from typing import Any, TypedDict

from langgraph.checkpoint.memory import InMemorySaver
from langgraph.graph import END, START, StateGraph
from langgraph.types import Command, interrupt

from app.application.ports.model_gateway import ForgeAgent, ReviewerCritic
from app.application.services.sandbox_workspace import SandboxWorkspace


class TaskGraphState(TypedDict):
    """Typed LangGraph state for a single autonomous engineer + reviewer cycle."""

    task_id: str
    org_id: str
    cycle_number: int
    task_context: dict[str, Any]
    previous_review: dict[str, Any] | None
    clarification_needed: bool
    clarification_prompt: str
    clarification_options: list[str]
    clarification_response: str | None
    guidance_messages: list[str]
    forge_completed: bool
    forge_summary: str
    forge_steps_taken: int
    forge_test_output: str
    forge_diff: str
    review_verdict: str
    review_summary: str
    review_findings: list[dict[str, Any]]
    review_blocking_count: int
    review_non_blocking_count: int


class PostgresTaskCheckpointSaver(InMemorySaver):
    """InMemorySaver adapter that serializes checkpoints to/from TaskRun JSONB."""

    def export_thread_state(self, thread_id: str) -> dict[str, Any]:
        """Serialize all checkpoints and pending writes for a thread to JSON."""
        thread_storage = self.storage.get(thread_id, {})
        serialized_storage: dict[str, dict[str, dict[str, Any]]] = {}
        for ns, checkpoints in thread_storage.items():
            serialized_storage[ns] = {}
            for cid, (cp_tuple, meta_tuple, parent_id) in checkpoints.items():
                serialized_storage[ns][cid] = {
                    "checkpoint": [
                        cp_tuple[0],
                        base64.b64encode(cp_tuple[1]).decode("ascii"),
                    ],
                    "metadata": [
                        meta_tuple[0],
                        base64.b64encode(meta_tuple[1]).decode("ascii"),
                    ],
                    "parent_id": parent_id,
                }

        serialized_writes: dict[str, list[dict[str, Any]]] = {}
        for (tid, ns, cid), write_map in self.writes.items():
            if tid != thread_id:
                continue
            key = f"{ns}||{cid}"
            serialized_writes[key] = []
            for (task_id, idx), (
                w_task_id,
                channel,
                val_tuple,
                task_path,
            ) in write_map.items():
                serialized_writes[key].append(
                    {
                        "task_id": task_id,
                        "idx": idx,
                        "w_task_id": w_task_id,
                        "channel": channel,
                        "value": [
                            val_tuple[0],
                            base64.b64encode(val_tuple[1]).decode("ascii"),
                        ],
                        "task_path": task_path,
                    }
                )

        return {
            "storage": serialized_storage,
            "writes": serialized_writes,
        }

    def import_thread_state(self, thread_id: str, payload: dict[str, Any]) -> None:
        """Restore serialized checkpoints and writes for a thread from JSONB."""
        raw_storage = payload.get("storage", {})
        if isinstance(raw_storage, dict):
            self.storage[thread_id] = defaultdict(dict)
            for ns, checkpoints in raw_storage.items():
                if not isinstance(checkpoints, dict):
                    continue
                for cid, entry in checkpoints.items():
                    cp_raw = entry["checkpoint"]
                    meta_raw = entry["metadata"]
                    self.storage[thread_id][ns][cid] = (
                        (cp_raw[0], base64.b64decode(cp_raw[1])),
                        (meta_raw[0], base64.b64decode(meta_raw[1])),
                        entry.get("parent_id"),
                    )

        raw_writes = payload.get("writes", {})
        if isinstance(raw_writes, dict):
            for key, items in raw_writes.items():
                if "||" not in key or not isinstance(items, list):
                    continue
                ns, cid = key.split("||", 1)
                write_key = (thread_id, ns, cid)
                self.writes[write_key] = {}
                for item in items:
                    val_raw = item["value"]
                    self.writes[write_key][(item["task_id"], item["idx"])] = (
                        item["w_task_id"],
                        item["channel"],
                        (val_raw[0], base64.b64decode(val_raw[1])),
                        item.get("task_path", ""),
                    )


def build_task_cycle_graph(
    forge_agent: ForgeAgent,
    reviewer_critic: ReviewerCritic,
    workspace: SandboxWorkspace,
    checkpointer: PostgresTaskCheckpointSaver,
):
    """Compile a LangGraph StateGraph supporting human in the loop interrupt/resume."""

    async def clarification_gate(state: TaskGraphState) -> dict[str, Any]:
        if state.get("clarification_needed") and not state.get(
            "clarification_response"
        ):
            human_answer = interrupt(
                {
                    "prompt": state["clarification_prompt"],
                    "options": state["clarification_options"],
                    "interruption_type": "clarification",
                }
            )
            return {
                "clarification_needed": False,
                "clarification_response": str(human_answer),
            }
        return {}

    async def forge_node(state: TaskGraphState) -> dict[str, Any]:
        context = dict(state["task_context"])
        if state.get("clarification_response"):
            context["clarification_response"] = state["clarification_response"]
        if state.get("guidance_messages"):
            context["guidance_messages"] = state["guidance_messages"]

        result = await forge_agent.run_cycle(
            context,
            state.get("previous_review"),
            workspace,
        )
        return {
            "forge_completed": result.completed,
            "forge_summary": result.summary,
            "forge_steps_taken": result.steps_taken,
            "forge_test_output": result.test_output,
            "forge_diff": result.diff,
        }

    async def reviewer_node(state: TaskGraphState) -> dict[str, Any]:
        result = await reviewer_critic.evaluate(
            state["task_context"],
            state["forge_diff"],
            state["forge_test_output"],
        )
        return {
            "review_verdict": result.verdict,
            "review_summary": result.summary,
            "review_findings": result.findings,
            "review_blocking_count": result.blocking_count,
            "review_non_blocking_count": result.non_blocking_count,
        }

    builder = StateGraph(TaskGraphState)
    builder.add_node("clarification_gate", clarification_gate)
    builder.add_node("forge_node", forge_node)
    builder.add_node("reviewer_node", reviewer_node)

    builder.add_edge(START, "clarification_gate")
    builder.add_edge("clarification_gate", "forge_node")
    builder.add_edge("forge_node", "reviewer_node")
    builder.add_edge("reviewer_node", END)

    return builder.compile(checkpointer=checkpointer)


__all__ = [
    "Command",
    "PostgresTaskCheckpointSaver",
    "TaskGraphState",
    "build_task_cycle_graph",
]
