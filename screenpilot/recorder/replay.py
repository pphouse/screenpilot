"""Workflow replay engine with vision-based adaptation."""

from __future__ import annotations

import logging
import time

from screenpilot.config import ExecutorConfig, LLMConfig
from screenpilot.executor.executor import ActionExecutor, ActionResult
from screenpilot.planner.planner import Action, ActionType
from screenpilot.recorder.recorder import RecordedEvent, Workflow
from screenpilot.vision.analyzer import ScreenAnalyzer
from screenpilot.vision.capture import ScreenCapture

logger = logging.getLogger(__name__)


class WorkflowReplayer:
    """Replays recorded workflows with optional vision-based adaptation.

    Two modes:
    1. Exact replay: Replays actions at exact coordinates with timing
    2. Adaptive replay: Uses vision to find elements even if UI has changed
    """

    def __init__(
        self,
        llm_config: LLMConfig | None = None,
        executor_config: ExecutorConfig | None = None,
        adaptive: bool = True,
    ):
        self.executor = ActionExecutor(executor_config)
        self.capture = ScreenCapture()
        self.adaptive = adaptive
        self._analyzer: ScreenAnalyzer | None = None
        if adaptive and llm_config:
            self._analyzer = ScreenAnalyzer(llm_config)
        self._running = False
        self._results: list[ActionResult] = []

    def replay(
        self,
        workflow: Workflow,
        speed: float = 1.0,
        adaptive: bool | None = None,
    ) -> list[ActionResult]:
        """Replay a recorded workflow.

        Args:
            workflow: The workflow to replay
            speed: Replay speed multiplier (1.0 = original speed, 2.0 = double)
            adaptive: Override adaptive mode for this replay
        """
        use_adaptive = adaptive if adaptive is not None else self.adaptive
        self._running = True
        self._results = []

        logger.info(
            "Replaying workflow '%s' (%d events, speed=%.1fx, adaptive=%s)",
            workflow.name,
            len(workflow.events),
            speed,
            use_adaptive,
        )

        prev_timestamp = None

        for i, event in enumerate(workflow.events):
            if not self._running:
                logger.info("Replay stopped at event %d", i)
                break

            # Apply timing delay
            if prev_timestamp is not None and speed > 0:
                delay = (event.timestamp - prev_timestamp) / speed
                delay = min(delay, 5.0)  # Cap at 5 seconds
                if delay > 0:
                    time.sleep(delay)
            prev_timestamp = event.timestamp

            # Convert event to action
            action = self._event_to_action(event)
            if action is None:
                continue

            # Adaptive mode: use vision to verify/adjust coordinates
            if use_adaptive and self._analyzer and action.x is not None:
                action = self._adapt_action(event, action)

            # Execute
            result = self.executor.execute(action)
            self._results.append(result)

            if not result.success:
                logger.warning("Action failed at event %d: %s", i, result.error)

        self._running = False
        return self._results

    def stop(self) -> None:
        """Stop the current replay."""
        self._running = False

    def _event_to_action(self, event: RecordedEvent) -> Action | None:
        """Convert a recorded event to an executable action."""
        match event.event_type:
            case "click":
                return Action(
                    action_type=ActionType.CLICK,
                    x=event.x,
                    y=event.y,
                )
            case "double_click":
                return Action(
                    action_type=ActionType.DOUBLE_CLICK,
                    x=event.x,
                    y=event.y,
                )
            case "right_click":
                return Action(
                    action_type=ActionType.RIGHT_CLICK,
                    x=event.x,
                    y=event.y,
                )
            case "type":
                return Action(
                    action_type=ActionType.TYPE,
                    text=event.text,
                )
            case "key":
                return Action(
                    action_type=ActionType.KEY,
                    keys=event.key,
                )
            case "scroll":
                direction = "up" if (event.scroll_dy or 0) > 0 else "down"
                return Action(
                    action_type=ActionType.SCROLL,
                    x=event.x,
                    y=event.y,
                    direction=direction,
                    amount=abs(event.scroll_dy or 3),
                )
            case _:
                logger.warning("Unknown event type: %s", event.event_type)
                return None

    def _adapt_action(self, event: RecordedEvent, action: Action) -> Action:
        """Use vision to adapt an action to the current screen state."""
        if self._analyzer is None or event.screenshot_path is None:
            return action

        # Only adapt click-type actions
        if action.action_type not in (ActionType.CLICK, ActionType.DOUBLE_CLICK, ActionType.RIGHT_CLICK):
            return action

        try:
            # Take current screenshot
            current_screenshot = self.capture.capture()

            # Ask the LLM to find the same element in the current screenshot
            # We use the recorded screenshot as reference context
            target_desc = f"the UI element that was at pixel coordinates ({event.x}, {event.y}) in the recorded screenshot"
            element = self._analyzer.find_element(current_screenshot, target_desc)

            if element and element.confidence > 0.5:
                logger.info(
                    "Adapted click from (%s, %s) to (%s, %s) [%s]",
                    action.x,
                    action.y,
                    element.x,
                    element.y,
                    element.label,
                )
                action.x = element.x
                action.y = element.y

        except Exception as e:
            logger.warning("Adaptive mode failed, using original coords: %s", e)

        return action

    @property
    def results(self) -> list[ActionResult]:
        return self._results
