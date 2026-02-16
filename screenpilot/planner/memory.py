"""Structured Task Memory for maintaining state across long execution chains.

Inspired by the Task Memory Engine (TME) paper (arXiv:2504.08525) and
Chain-of-Memory (CoM) approach. Maintains a hierarchical tree of task states
to provide coherent context for LLM planning, even across many steps.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from enum import Enum
from typing import Any


class TaskNodeStatus(str, Enum):
    PENDING = "pending"
    IN_PROGRESS = "in_progress"
    COMPLETED = "completed"
    FAILED = "failed"
    SKIPPED = "skipped"


@dataclass
class TaskNode:
    """A node in the Task Memory Tree."""

    id: str
    description: str
    status: TaskNodeStatus = TaskNodeStatus.PENDING
    parent_id: str | None = None
    children: list[str] = field(default_factory=list)
    actions_taken: list[dict[str, Any]] = field(default_factory=list)
    observations: list[str] = field(default_factory=list)
    result: str | None = None
    created_at: float = field(default_factory=time.time)
    completed_at: float | None = None

    def to_summary(self) -> str:
        """Generate a concise summary of this task node."""
        status_icon = {
            TaskNodeStatus.PENDING: "[ ]",
            TaskNodeStatus.IN_PROGRESS: "[>]",
            TaskNodeStatus.COMPLETED: "[x]",
            TaskNodeStatus.FAILED: "[!]",
            TaskNodeStatus.SKIPPED: "[-]",
        }
        icon = status_icon.get(self.status, "[ ]")
        summary = f"{icon} {self.description}"
        if self.result:
            summary += f" -> {self.result}"
        return summary


class TaskMemoryTree:
    """Hierarchical task memory that tracks execution state.

    The tree structure allows the LLM planner to:
    - See the overall task decomposition
    - Know which subtasks are complete/in-progress
    - Access relevant observations from completed steps
    - Maintain context without linear prompt concatenation
    """

    def __init__(self, root_goal: str):
        self._nodes: dict[str, TaskNode] = {}
        self._root_id = "root"
        self._active_id: str = self._root_id

        root = TaskNode(
            id=self._root_id,
            description=root_goal,
            status=TaskNodeStatus.IN_PROGRESS,
        )
        self._nodes[self._root_id] = root
        self._next_id = 1

    def add_subtask(self, description: str, parent_id: str | None = None) -> str:
        """Add a subtask under the given parent."""
        task_id = f"task_{self._next_id}"
        self._next_id += 1

        parent = parent_id or self._active_id
        node = TaskNode(
            id=task_id,
            description=description,
            parent_id=parent,
        )
        self._nodes[task_id] = node

        if parent in self._nodes:
            self._nodes[parent].children.append(task_id)

        return task_id

    def start_task(self, task_id: str) -> None:
        """Mark a task as in-progress and set it as active."""
        if task_id in self._nodes:
            self._nodes[task_id].status = TaskNodeStatus.IN_PROGRESS
            self._active_id = task_id

    def complete_task(self, task_id: str, result: str = "") -> None:
        """Mark a task as completed."""
        if task_id in self._nodes:
            node = self._nodes[task_id]
            node.status = TaskNodeStatus.COMPLETED
            node.result = result
            node.completed_at = time.time()

            # Move active to parent
            if node.parent_id:
                self._active_id = node.parent_id

    def fail_task(self, task_id: str, error: str = "") -> None:
        """Mark a task as failed."""
        if task_id in self._nodes:
            node = self._nodes[task_id]
            node.status = TaskNodeStatus.FAILED
            node.result = error
            node.completed_at = time.time()

            if node.parent_id:
                self._active_id = node.parent_id

    def add_action(self, action: dict[str, Any], task_id: str | None = None) -> None:
        """Record an action taken for a task."""
        tid = task_id or self._active_id
        if tid in self._nodes:
            self._nodes[tid].actions_taken.append(action)

    def add_observation(self, observation: str, task_id: str | None = None) -> None:
        """Record an observation for a task."""
        tid = task_id or self._active_id
        if tid in self._nodes:
            self._nodes[tid].observations.append(observation)

    @property
    def active_task(self) -> TaskNode | None:
        return self._nodes.get(self._active_id)

    @property
    def root(self) -> TaskNode:
        return self._nodes[self._root_id]

    def get_context(self, max_depth: int = 3) -> str:
        """Generate a context string for the LLM planner.

        Shows the task tree from the root down to the active task,
        including relevant observations and action history.
        """
        lines = ["## Task Memory"]
        self._render_tree(self._root_id, lines, depth=0, max_depth=max_depth)

        # Add recent actions from active task
        active = self.active_task
        if active and active.actions_taken:
            lines.append("\n## Recent Actions")
            for action in active.actions_taken[-5:]:
                action_type = action.get("action_type", "unknown")
                reasoning = action.get("reasoning", "")[:80]
                lines.append(f"- {action_type}: {reasoning}")

        # Add recent observations
        if active and active.observations:
            lines.append("\n## Observations")
            for obs in active.observations[-3:]:
                lines.append(f"- {obs}")

        return "\n".join(lines)

    def _render_tree(self, node_id: str, lines: list[str], depth: int, max_depth: int) -> None:
        """Recursively render the task tree."""
        if depth > max_depth:
            return

        node = self._nodes.get(node_id)
        if not node:
            return

        indent = "  " * depth
        marker = ">>>" if node_id == self._active_id else "   "
        lines.append(f"{marker}{indent}{node.to_summary()}")

        for child_id in node.children:
            self._render_tree(child_id, lines, depth + 1, max_depth)

    def get_progress(self) -> dict[str, int]:
        """Get task completion statistics."""
        stats = {s.value: 0 for s in TaskNodeStatus}
        for node in self._nodes.values():
            if node.id != self._root_id:
                stats[node.status.value] += 1
        return stats

    def to_dict(self) -> dict:
        """Serialize the tree to a dictionary."""
        return {
            "root_id": self._root_id,
            "active_id": self._active_id,
            "nodes": {
                nid: {
                    "id": n.id,
                    "description": n.description,
                    "status": n.status.value,
                    "parent_id": n.parent_id,
                    "children": n.children,
                    "result": n.result,
                    "observations": n.observations,
                    "actions_taken": n.actions_taken,
                }
                for nid, n in self._nodes.items()
            },
        }
