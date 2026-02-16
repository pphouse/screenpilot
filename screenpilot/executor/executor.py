"""Cross-platform action executor for mouse/keyboard control."""

from __future__ import annotations

import logging
import platform
import time
from dataclasses import dataclass, field
from typing import Any

import pyautogui

from screenpilot.config import ExecutorConfig
from screenpilot.planner.planner import Action, ActionType

logger = logging.getLogger(__name__)

# Configure pyautogui safety
pyautogui.FAILSAFE = True  # Move mouse to corner to abort
pyautogui.PAUSE = 0.05


@dataclass
class ActionResult:
    """Result of executing an action."""

    success: bool
    action: Action
    error: str | None = None
    duration: float = 0.0
    metadata: dict[str, Any] = field(default_factory=dict)


# Mapping of key names to pyautogui key names
KEY_MAP = {
    "ctrl": "ctrl",
    "control": "ctrl",
    "alt": "alt",
    "option": "alt",
    "shift": "shift",
    "cmd": "command" if platform.system() == "Darwin" else "ctrl",
    "command": "command" if platform.system() == "Darwin" else "ctrl",
    "super": "win" if platform.system() == "Windows" else "command",
    "win": "win",
    "enter": "enter",
    "return": "enter",
    "tab": "tab",
    "escape": "escape",
    "esc": "escape",
    "backspace": "backspace",
    "delete": "delete",
    "space": "space",
    "up": "up",
    "down": "down",
    "left": "left",
    "right": "right",
    "home": "home",
    "end": "end",
    "pageup": "pageup",
    "pagedown": "pagedown",
    "f1": "f1",
    "f2": "f2",
    "f3": "f3",
    "f4": "f4",
    "f5": "f5",
    "f6": "f6",
    "f7": "f7",
    "f8": "f8",
    "f9": "f9",
    "f10": "f10",
    "f11": "f11",
    "f12": "f12",
}


class ActionExecutor:
    """Executes actions on the desktop using pyautogui."""

    def __init__(self, config: ExecutorConfig | None = None):
        self.config = config or ExecutorConfig()
        self._action_log: list[ActionResult] = []

    def execute(self, action: Action) -> ActionResult:
        """Execute a single action and return the result."""
        start_time = time.time()
        logger.info("Executing: %s (target=%s)", action.action_type.value, action.target)

        try:
            match action.action_type:
                case ActionType.CLICK:
                    result = self._click(action)
                case ActionType.DOUBLE_CLICK:
                    result = self._double_click(action)
                case ActionType.RIGHT_CLICK:
                    result = self._right_click(action)
                case ActionType.TYPE:
                    result = self._type(action)
                case ActionType.KEY:
                    result = self._key(action)
                case ActionType.SCROLL:
                    result = self._scroll(action)
                case ActionType.DRAG:
                    result = self._drag(action)
                case ActionType.WAIT:
                    result = self._wait(action)
                case ActionType.FIND_AND_CLICK:
                    # This requires vision - just click if coords are provided
                    result = self._click(action)
                case ActionType.FIND_AND_TYPE:
                    # Click then type
                    if action.x is not None and action.y is not None:
                        self._click(action)
                    result = self._type(action)
                case ActionType.DONE:
                    result = ActionResult(success=True, action=action)
                case ActionType.FAIL:
                    result = ActionResult(
                        success=False,
                        action=action,
                        error=action.reasoning,
                    )
                case _:
                    result = ActionResult(
                        success=False,
                        action=action,
                        error=f"Unknown action type: {action.action_type}",
                    )

        except pyautogui.FailSafeException:
            logger.error("FAILSAFE triggered - mouse moved to corner")
            result = ActionResult(
                success=False,
                action=action,
                error="Failsafe triggered - execution aborted for safety",
            )
        except Exception as e:
            logger.error("Action execution failed: %s", e)
            result = ActionResult(success=False, action=action, error=str(e))

        result.duration = time.time() - start_time
        self._action_log.append(result)

        if self.config.click_delay > 0:
            time.sleep(self.config.click_delay)

        return result

    def _click(self, action: Action) -> ActionResult:
        """Perform a left click."""
        if action.x is None or action.y is None:
            return ActionResult(
                success=False, action=action, error="Click requires x and y coordinates"
            )
        pyautogui.click(action.x, action.y)
        return ActionResult(success=True, action=action)

    def _double_click(self, action: Action) -> ActionResult:
        """Perform a double click."""
        if action.x is None or action.y is None:
            return ActionResult(
                success=False, action=action, error="Double click requires x and y coordinates"
            )
        pyautogui.doubleClick(action.x, action.y)
        return ActionResult(success=True, action=action)

    def _right_click(self, action: Action) -> ActionResult:
        """Perform a right click."""
        if action.x is None or action.y is None:
            return ActionResult(
                success=False, action=action, error="Right click requires x and y coordinates"
            )
        pyautogui.rightClick(action.x, action.y)
        return ActionResult(success=True, action=action)

    def _type(self, action: Action) -> ActionResult:
        """Type text."""
        if not action.text:
            return ActionResult(success=False, action=action, error="Type requires text")

        # Use write for simple text, typewrite for compatibility
        pyautogui.write(action.text, interval=self.config.type_delay)
        return ActionResult(success=True, action=action)

    def _key(self, action: Action) -> ActionResult:
        """Press a keyboard shortcut."""
        if not action.keys:
            return ActionResult(success=False, action=action, error="Key action requires keys")

        keys = [k.strip().lower() for k in action.keys.split("+")]
        mapped = [KEY_MAP.get(k, k) for k in keys]

        if len(mapped) == 1:
            pyautogui.press(mapped[0])
        else:
            pyautogui.hotkey(*mapped)

        return ActionResult(success=True, action=action)

    def _scroll(self, action: Action) -> ActionResult:
        """Scroll the screen."""
        amount = action.amount or 3
        direction = (action.direction or "down").lower()

        if direction == "up":
            pyautogui.scroll(amount)
        else:
            pyautogui.scroll(-amount)

        return ActionResult(success=True, action=action)

    def _drag(self, action: Action) -> ActionResult:
        """Drag from current position to target."""
        if action.x is None or action.y is None:
            return ActionResult(
                success=False, action=action, error="Drag requires target x and y"
            )

        end_x = action.metadata.get("end_x", action.x + 100)
        end_y = action.metadata.get("end_y", action.y + 100)

        pyautogui.moveTo(action.x, action.y)
        pyautogui.drag(end_x - action.x, end_y - action.y, duration=0.5)

        return ActionResult(success=True, action=action)

    def _wait(self, action: Action) -> ActionResult:
        """Wait for a specified duration."""
        duration = action.duration or 1.0
        time.sleep(duration)
        return ActionResult(success=True, action=action)

    @property
    def action_log(self) -> list[ActionResult]:
        """Get the log of all executed actions."""
        return self._action_log

    def clear_log(self) -> None:
        """Clear the action log."""
        self._action_log = []
