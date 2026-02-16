"""Enhanced ScreenPilot agent with hierarchical planning and SoM grounding.

This is the v2 agent that incorporates key research findings:
1. Set-of-Mark (SoM) visual prompting for precise grounding
2. Hierarchical task decomposition (high-level planner + step executor)
3. Task Memory Tree for structured state management
4. Action verification with adaptive recovery

Based on patterns from Agent S2/S3, OmniParser, and TME.
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field
from typing import Callable

from screenpilot.config import ScreenPilotConfig
from screenpilot.executor.executor import ActionExecutor, ActionResult
from screenpilot.planner.hierarchical import HierarchicalPlanner
from screenpilot.planner.memory import TaskNodeStatus
from screenpilot.planner.planner import Action, ActionType
from screenpilot.vision.capture import ScreenCapture, Screenshot
from screenpilot.vision.som import SoMResult, create_grid_marks

logger = logging.getLogger(__name__)


@dataclass
class StepResult:
    """Result of a single agent step."""

    step_number: int
    action: Action
    action_result: ActionResult
    screenshot_before: Screenshot | None = None
    screenshot_after: Screenshot | None = None
    som_result: SoMResult | None = None
    verified: bool | None = None
    timestamp: float = 0.0


@dataclass
class TaskResult:
    """Result of running a complete task."""

    goal: str
    success: bool
    steps: list[StepResult] = field(default_factory=list)
    total_time: float = 0.0
    error: str | None = None
    memory_dump: dict | None = None

    @property
    def num_steps(self) -> int:
        return len(self.steps)


class ScreenPilotAgentV2:
    """Enhanced agent with hierarchical planning and SoM grounding.

    Architecture:
    1. Capture screenshot
    2. Apply SoM annotations (numbered bounding boxes)
    3. If no subtasks yet, decompose goal into subtasks
    4. Get next action from hierarchical planner using SoM-annotated image
    5. Resolve mark IDs to coordinates
    6. Execute action
    7. Verify result with post-action screenshot
    8. Update task memory
    9. Repeat until done
    """

    def __init__(self, config: ScreenPilotConfig | None = None):
        self.config = config or ScreenPilotConfig()
        self.capture = ScreenCapture(self.config.capture)
        self.planner = HierarchicalPlanner(self.config.llm)
        self.executor = ActionExecutor(self.config.executor)
        self._running = False
        self._on_step: Callable[[StepResult], None] | None = None

    def on_step(self, callback: Callable[[StepResult], None]) -> None:
        """Register a callback for each step."""
        self._on_step = callback

    def run(self, goal: str, max_steps: int = 50) -> TaskResult:
        """Run the enhanced agent to complete a goal."""
        self._running = True
        self.planner.initialize(goal)
        start_time = time.time()
        steps: list[StepResult] = []
        decomposed = False
        consecutive_failures = 0

        logger.info("Starting task (v2): %s (max_steps=%d)", goal, max_steps)

        for step_num in range(1, max_steps + 1):
            if not self._running:
                return self._make_result(goal, False, steps, start_time, "Stopped by user")

            # 1. Capture screenshot
            try:
                screenshot = self.capture.capture()
            except Exception as e:
                return self._make_result(goal, False, steps, start_time, f"Screenshot failed: {e}")

            # 2. Apply SoM annotations
            som_result = create_grid_marks(screenshot.image)

            # 3. Decompose if not yet done
            if not decomposed:
                logger.info("Decomposing goal into subtasks...")
                subtask_ids = self.planner.decompose(goal, screenshot)
                if subtask_ids:
                    # Start the first subtask
                    self.planner.memory.start_task(subtask_ids[0])
                    decomposed = True
                    logger.info("Decomposed into %d subtasks", len(subtask_ids))
                else:
                    logger.warning("Failed to decompose, falling back to direct execution")
                    decomposed = True  # Proceed anyway

            # 4. Get next action
            try:
                action, subtask_complete = self.planner.get_next_action(screenshot, som_result)
            except Exception as e:
                logger.error("Planning failed: %s", e)
                return self._make_result(goal, False, steps, start_time, f"Planning failed: {e}")

            logger.info(
                "Step %d: %s (reasoning=%s)",
                step_num,
                action.action_type.value,
                action.reasoning[:80] if action.reasoning else "",
            )

            # 5. Check terminal actions
            if action.action_type == ActionType.DONE:
                step_result = StepResult(
                    step_number=step_num,
                    action=action,
                    action_result=ActionResult(success=True, action=action),
                    screenshot_before=screenshot,
                    som_result=som_result,
                    timestamp=time.time(),
                )
                steps.append(step_result)
                if self._on_step:
                    self._on_step(step_result)
                return self._make_result(goal, True, steps, start_time)

            if action.action_type == ActionType.FAIL:
                step_result = StepResult(
                    step_number=step_num,
                    action=action,
                    action_result=ActionResult(
                        success=False, action=action, error=action.reasoning
                    ),
                    screenshot_before=screenshot,
                    som_result=som_result,
                    timestamp=time.time(),
                )
                steps.append(step_result)
                if self._on_step:
                    self._on_step(step_result)
                consecutive_failures += 1
                if consecutive_failures >= 3:
                    return self._make_result(
                        goal, False, steps, start_time, "Too many consecutive failures"
                    )
                continue

            # 6. Execute action
            action_result = self.executor.execute(action)

            # 7. Verify with post-action screenshot
            verified = None
            screenshot_after = None
            if self.config.executor.screenshot_after_action:
                time.sleep(0.3)
                try:
                    screenshot_after = self.capture.capture()
                    action_desc = f"{action.action_type.value}"
                    if action.text:
                        action_desc += f" '{action.text}'"
                    if action.x is not None:
                        action_desc += f" at ({action.x}, {action.y})"

                    verification = self.planner.verify_action(screenshot_after, action_desc)
                    verified = verification.get("success", True)
                except Exception:
                    pass

            step_result = StepResult(
                step_number=step_num,
                action=action,
                action_result=action_result,
                screenshot_before=screenshot,
                screenshot_after=screenshot_after,
                som_result=som_result,
                verified=verified,
                timestamp=time.time(),
            )
            steps.append(step_result)

            if self._on_step:
                self._on_step(step_result)

            # Track failures
            if action_result.success:
                consecutive_failures = 0
            else:
                consecutive_failures += 1
                if consecutive_failures >= 3:
                    return self._make_result(
                        goal, False, steps, start_time, "Too many consecutive failures"
                    )

            # 8. Advance to next subtask if current is complete
            if subtask_complete and self.planner.memory:
                memory = self.planner.memory
                # Find next pending subtask
                root = memory.root
                next_started = False
                for child_id in root.children:
                    child = memory._nodes.get(child_id)
                    if child and child.status == TaskNodeStatus.PENDING:
                        memory.start_task(child_id)
                        logger.info("Moving to next subtask: %s", child.description)
                        next_started = True
                        break

                if not next_started:
                    # All subtasks done
                    all_complete = all(
                        memory._nodes[cid].status
                        in (TaskNodeStatus.COMPLETED, TaskNodeStatus.SKIPPED)
                        for cid in root.children
                        if cid in memory._nodes
                    )
                    if all_complete:
                        return self._make_result(goal, True, steps, start_time)

        return self._make_result(goal, False, steps, start_time, f"Max steps ({max_steps}) reached")

    def _make_result(
        self,
        goal: str,
        success: bool,
        steps: list[StepResult],
        start_time: float,
        error: str | None = None,
    ) -> TaskResult:
        """Build a TaskResult."""
        memory_dump = None
        if self.planner.memory:
            memory_dump = self.planner.memory.to_dict()
        return TaskResult(
            goal=goal,
            success=success,
            steps=steps,
            total_time=time.time() - start_time,
            error=error,
            memory_dump=memory_dump,
        )

    def stop(self) -> None:
        """Stop the running agent."""
        self._running = False
