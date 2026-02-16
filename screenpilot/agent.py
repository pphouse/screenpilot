"""Main ScreenPilot agent that orchestrates vision, planning, and execution."""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field
from typing import Any, Callable

from screenpilot.config import ScreenPilotConfig
from screenpilot.executor.executor import ActionExecutor, ActionResult
from screenpilot.planner.planner import Action, ActionType, TaskPlanner
from screenpilot.vision.analyzer import ScreenAnalyzer
from screenpilot.vision.capture import ScreenCapture, Screenshot

logger = logging.getLogger(__name__)


@dataclass
class StepResult:
    """Result of a single agent step."""

    step_number: int
    action: Action
    action_result: ActionResult
    screenshot_before: Screenshot | None = None
    screenshot_after: Screenshot | None = None
    timestamp: float = 0.0


@dataclass
class TaskResult:
    """Result of running a complete task."""

    goal: str
    success: bool
    steps: list[StepResult] = field(default_factory=list)
    total_time: float = 0.0
    error: str | None = None

    @property
    def num_steps(self) -> int:
        return len(self.steps)


class ScreenPilotAgent:
    """The main agent that orchestrates the automation loop.

    Loop:
    1. Capture screenshot
    2. Send to LLM planner with goal + history
    3. Get next action
    4. If find_and_* action, use vision to resolve coordinates
    5. Execute action
    6. Repeat until done/fail/max_steps
    """

    def __init__(self, config: ScreenPilotConfig | None = None):
        self.config = config or ScreenPilotConfig()
        self.capture = ScreenCapture(self.config.capture)
        self.analyzer = ScreenAnalyzer(self.config.llm)
        self.planner = TaskPlanner(self.config.llm)
        self.executor = ActionExecutor(self.config.executor)
        self._running = False
        self._on_step: Callable[[StepResult], None] | None = None
        self._on_screenshot: Callable[[Screenshot], None] | None = None

    def on_step(self, callback: Callable[[StepResult], None]) -> None:
        """Register a callback for each step."""
        self._on_step = callback

    def on_screenshot(self, callback: Callable[[Screenshot], None]) -> None:
        """Register a callback for each screenshot."""
        self._on_screenshot = callback

    def run(self, goal: str, max_steps: int = 50) -> TaskResult:
        """Run the agent to complete a goal.

        Args:
            goal: Natural language description of what to accomplish
            max_steps: Maximum number of actions before giving up
        """
        self._running = True
        self.planner.reset()
        start_time = time.time()
        steps: list[StepResult] = []

        logger.info("Starting task: %s (max_steps=%d)", goal, max_steps)

        for step_num in range(1, max_steps + 1):
            if not self._running:
                logger.info("Task stopped by user at step %d", step_num)
                return TaskResult(
                    goal=goal,
                    success=False,
                    steps=steps,
                    total_time=time.time() - start_time,
                    error="Stopped by user",
                )

            # 1. Capture screenshot
            try:
                screenshot = self.capture.capture()
            except Exception as e:
                logger.error("Screenshot capture failed: %s", e)
                return TaskResult(
                    goal=goal,
                    success=False,
                    steps=steps,
                    total_time=time.time() - start_time,
                    error=f"Screenshot failed: {e}",
                )

            if self._on_screenshot:
                self._on_screenshot(screenshot)

            # 2. Get next action from planner
            try:
                action = self.planner.get_next_action(goal, screenshot)
            except Exception as e:
                logger.error("Planning failed: %s", e)
                return TaskResult(
                    goal=goal,
                    success=False,
                    steps=steps,
                    total_time=time.time() - start_time,
                    error=f"Planning failed: {e}",
                )

            logger.info(
                "Step %d: %s (target=%s, reasoning=%s)",
                step_num,
                action.action_type.value,
                action.target,
                action.reasoning[:100] if action.reasoning else "",
            )

            # 3. Check for terminal actions
            if action.action_type == ActionType.DONE:
                step_result = StepResult(
                    step_number=step_num,
                    action=action,
                    action_result=ActionResult(success=True, action=action),
                    screenshot_before=screenshot,
                    timestamp=time.time(),
                )
                steps.append(step_result)
                if self._on_step:
                    self._on_step(step_result)

                return TaskResult(
                    goal=goal,
                    success=True,
                    steps=steps,
                    total_time=time.time() - start_time,
                )

            if action.action_type == ActionType.FAIL:
                step_result = StepResult(
                    step_number=step_num,
                    action=action,
                    action_result=ActionResult(success=False, action=action, error=action.reasoning),
                    screenshot_before=screenshot,
                    timestamp=time.time(),
                )
                steps.append(step_result)
                if self._on_step:
                    self._on_step(step_result)

                return TaskResult(
                    goal=goal,
                    success=False,
                    steps=steps,
                    total_time=time.time() - start_time,
                    error=action.reasoning,
                )

            # 4. Resolve vision-based actions
            if action.action_type in (ActionType.FIND_AND_CLICK, ActionType.FIND_AND_TYPE):
                if action.target and (action.x is None or action.y is None):
                    try:
                        element = self.analyzer.find_element(screenshot, action.target)
                        if element:
                            action.x = element.center[0]
                            action.y = element.center[1]
                            logger.info("Resolved '%s' to (%d, %d)", action.target, action.x, action.y)
                        else:
                            logger.warning("Could not find element: %s", action.target)
                    except Exception as e:
                        logger.warning("Vision resolution failed: %s", e)

            # 5. Execute action
            action_result = self.executor.execute(action)

            # 6. Take post-action screenshot
            screenshot_after = None
            if self.config.executor.screenshot_after_action:
                try:
                    time.sleep(0.3)  # Brief wait for UI to update
                    screenshot_after = self.capture.capture()
                except Exception:
                    pass

            step_result = StepResult(
                step_number=step_num,
                action=action,
                action_result=action_result,
                screenshot_before=screenshot,
                screenshot_after=screenshot_after,
                timestamp=time.time(),
            )
            steps.append(step_result)

            if self._on_step:
                self._on_step(step_result)

            if not action_result.success:
                logger.warning("Action failed: %s", action_result.error)
                # Don't stop on failure - let the planner adapt

        # Max steps reached
        return TaskResult(
            goal=goal,
            success=False,
            steps=steps,
            total_time=time.time() - start_time,
            error=f"Max steps ({max_steps}) reached without completing the task",
        )

    def stop(self) -> None:
        """Stop the running agent."""
        self._running = False

    def run_action(self, action: Action) -> ActionResult:
        """Execute a single action directly (for manual control)."""
        if action.action_type in (ActionType.FIND_AND_CLICK, ActionType.FIND_AND_TYPE):
            if action.target and (action.x is None or action.y is None):
                screenshot = self.capture.capture()
                element = self.analyzer.find_element(screenshot, action.target)
                if element:
                    action.x = element.center[0]
                    action.y = element.center[1]

        return self.executor.execute(action)
