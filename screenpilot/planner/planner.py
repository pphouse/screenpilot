"""LLM-based task planner that decomposes goals into executable actions."""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from enum import Enum
from typing import Any

from screenpilot.config import LLMConfig
from screenpilot.vision.capture import Screenshot

logger = logging.getLogger(__name__)


class ActionType(str, Enum):
    """Types of actions the agent can perform."""

    CLICK = "click"
    DOUBLE_CLICK = "double_click"
    RIGHT_CLICK = "right_click"
    TYPE = "type"
    KEY = "key"  # keyboard shortcut
    SCROLL = "scroll"
    DRAG = "drag"
    WAIT = "wait"
    SCREENSHOT = "screenshot"
    FIND_AND_CLICK = "find_and_click"  # Vision-based: find element then click
    FIND_AND_TYPE = "find_and_type"  # Vision-based: find element then type
    DONE = "done"
    FAIL = "fail"


@dataclass
class Action:
    """A single action to execute."""

    action_type: ActionType
    target: str | None = None  # UI element description for find_and_*
    x: int | None = None
    y: int | None = None
    text: str | None = None  # For type actions
    keys: str | None = None  # For key actions (e.g., "ctrl+c")
    direction: str | None = None  # For scroll: "up", "down"
    amount: int | None = None  # For scroll: number of clicks
    duration: float | None = None  # For wait
    reasoning: str = ""  # Why this action was chosen
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict:
        """Convert to dictionary."""
        return {k: v for k, v in self.__dict__.items() if v is not None}


@dataclass
class Plan:
    """A plan consisting of multiple actions."""

    goal: str
    actions: list[Action]
    reasoning: str = ""
    current_step: int = 0

    @property
    def is_complete(self) -> bool:
        return self.current_step >= len(self.actions)

    @property
    def next_action(self) -> Action | None:
        if self.is_complete:
            return None
        return self.actions[self.current_step]

    def advance(self) -> None:
        self.current_step += 1


PLANNER_SYSTEM_PROMPT = """You are ScreenPilot, an AI assistant that controls a computer by looking at screenshots and performing mouse/keyboard actions.

You receive a task goal and a screenshot of the current screen state. Your job is to determine the NEXT SINGLE ACTION to take toward completing the goal.

## Available Actions

- click: Click at coordinates (x, y)
- double_click: Double-click at coordinates (x, y)
- right_click: Right-click at coordinates (x, y)
- type: Type text at the current cursor position
- key: Press a keyboard shortcut (e.g., "ctrl+c", "enter", "tab")
- scroll: Scroll up or down
- drag: Drag from one point to another
- wait: Wait for a specified duration
- find_and_click: Describe a UI element to find and click (uses vision to locate)
- find_and_type: Describe a UI element to find, click, and type into
- done: Task is complete
- fail: Task cannot be completed

## Response Format

Respond with ONLY a JSON object (no markdown, no code fences):
{
  "reasoning": "Step-by-step reasoning about what you see and what to do next",
  "action_type": "click|type|key|scroll|find_and_click|find_and_type|done|fail",
  "target": "description of UI element (for find_and_* actions)",
  "x": 100,
  "y": 200,
  "text": "text to type (for type/find_and_type actions)",
  "keys": "ctrl+c (for key actions)",
  "direction": "up|down (for scroll)",
  "amount": 3
}

## Guidelines

1. Be PRECISE with coordinates. The screenshot is the full screen. Look carefully at where UI elements are positioned.
2. Always explain your reasoning, describing what you see on screen FIRST, then what action to take.
3. If you can't find a target element, try scrolling or looking elsewhere.
4. Use find_and_click when you're unsure of exact coordinates — it uses vision to locate the element precisely.
5. Use keyboard shortcuts when they're more efficient.
6. Return "done" when the task is clearly complete (verify by examining the current screen).
7. Return "fail" with reasoning if the task is impossible.

## CRITICAL: Avoid Repeating Failed Actions

- Check the task history carefully. If you already tried clicking a coordinate and the screen didn't change, DO NOT click the same coordinates again.
- If an action didn't work, try a DIFFERENT approach: use find_and_click instead of click, try different coordinates, scroll to reveal the element, or use keyboard navigation.
- After 2 failed attempts at the same target, switch to an entirely different strategy (keyboard shortcut, scrolling, etc.)."""


PLANNER_USER_PROMPT = """## Screen Information
The screenshot is {screen_width}x{screen_height} pixels. Coordinates (0,0) is top-left, ({screen_max_x},{screen_max_y}) is bottom-right.

## Current Task
{goal}

## Task History (most recent actions)
{history}
{stuck_warning}
## Instructions
Look at the current screenshot and determine the NEXT SINGLE ACTION to take.
Be very careful with Y coordinates — look at the vertical position of elements precisely.
Respond with ONLY a JSON object (no markdown code fences)."""


class TaskPlanner:
    """Plans and decomposes tasks using LLM reasoning."""

    def __init__(self, config: LLMConfig | None = None):
        self.config = config or LLMConfig()
        self._client = None
        self.history: list[dict] = []

    def _get_client(self):
        """Lazy-initialize the LLM client."""
        if self._client is not None:
            return self._client

        if self.config.provider == "anthropic":
            import anthropic

            self._client = anthropic.Anthropic(api_key=self.config.api_key)
        elif self.config.provider == "openai":
            import openai

            self._client = openai.OpenAI(
                api_key=self.config.api_key,
                base_url=self.config.base_url,
            )
        else:
            import litellm

            self._client = litellm
        return self._client

    def _call_llm(self, screenshot: Screenshot, system: str, user: str) -> str:
        """Call LLM with screenshot and prompts."""
        client = self._get_client()
        img_b64 = screenshot.to_base64(format="png")

        if self.config.provider == "anthropic":
            response = client.messages.create(
                model=self.config.model,
                max_tokens=self.config.max_tokens,
                temperature=self.config.temperature,
                system=system,
                messages=[
                    {
                        "role": "user",
                        "content": [
                            {
                                "type": "image",
                                "source": {
                                    "type": "base64",
                                    "media_type": "image/png",
                                    "data": img_b64,
                                },
                            },
                            {"type": "text", "text": user},
                        ],
                    }
                ],
            )
            return response.content[0].text

        elif self.config.provider == "openai":
            response = client.chat.completions.create(
                model=self.config.model,
                max_tokens=self.config.max_tokens,
                temperature=self.config.temperature,
                messages=[
                    {"role": "system", "content": system},
                    {
                        "role": "user",
                        "content": [
                            {
                                "type": "image_url",
                                "image_url": {"url": f"data:image/png;base64,{img_b64}"},
                            },
                            {"type": "text", "text": user},
                        ],
                    },
                ],
            )
            return response.choices[0].message.content

        else:
            import litellm

            response = litellm.completion(
                model=self.config.model,
                max_tokens=self.config.max_tokens,
                temperature=self.config.temperature,
                messages=[
                    {"role": "system", "content": system},
                    {
                        "role": "user",
                        "content": [
                            {
                                "type": "image_url",
                                "image_url": {"url": f"data:image/png;base64,{img_b64}"},
                            },
                            {"type": "text", "text": user},
                        ],
                    },
                ],
            )
            return response.choices[0].message.content

    def _parse_action(self, text: str) -> Action:
        """Parse an action from LLM response."""
        # Extract JSON
        if "```json" in text:
            start = text.index("```json") + 7
            end = text.index("```", start)
            text = text[start:end]
        elif "```" in text:
            start = text.index("```") + 3
            end = text.index("```", start)
            text = text[start:end]

        data = json.loads(text.strip())

        return Action(
            action_type=ActionType(data["action_type"]),
            target=data.get("target"),
            x=data.get("x"),
            y=data.get("y"),
            text=data.get("text"),
            keys=data.get("keys"),
            direction=data.get("direction"),
            amount=data.get("amount"),
            duration=data.get("duration"),
            reasoning=data.get("reasoning", ""),
        )

    def _detect_stuck(self) -> str:
        """Detect if the agent is stuck repeating the same action."""
        if len(self.history) < 2:
            return ""

        recent = self.history[-3:]
        # Check if last 3 actions have the same coordinates
        coords = []
        for h in recent:
            x, y = h.get("x"), h.get("y")
            if x is not None and y is not None:
                coords.append((x, y))

        if len(coords) >= 2 and len(set(coords)) == 1:
            return (
                "\n⚠️ WARNING: You have been clicking the same coordinates "
                f"({coords[0][0]}, {coords[0][1]}) repeatedly without the screen changing. "
                "This action is NOT working. You MUST try a completely different approach:\n"
                "- Use find_and_click with a text description of the element\n"
                "- Try keyboard navigation (Tab, Enter, arrow keys)\n"
                "- Click at significantly different coordinates\n"
                "- Scroll to reveal the element if it's not visible\n"
            )

        # Check if same action type repeated 3+ times
        action_types = [h.get("action_type") for h in recent]
        if len(action_types) >= 3 and len(set(action_types)) == 1:
            return (
                "\n⚠️ WARNING: You have been repeating the same action type "
                f"'{action_types[0]}' multiple times. If the screen hasn't changed, "
                "try a completely different approach.\n"
            )

        return ""

    def _format_history(self) -> str:
        """Format action history with coordinates and results."""
        if not self.history:
            return "No actions taken yet."

        recent = self.history[-10:]
        lines = []
        for i, h in enumerate(recent):
            action_type = h.get("action_type", "?")
            parts = [f"Step {i + 1}: {action_type}"]

            # Include coordinates if present
            x, y = h.get("x"), h.get("y")
            if x is not None and y is not None:
                parts.append(f"at ({x}, {y})")

            # Include target if present
            target = h.get("target")
            if target:
                parts.append(f'target="{target}"')

            # Include text if present
            text = h.get("text")
            if text:
                parts.append(f'text="{text[:30]}"')

            # Include brief reasoning
            reasoning = h.get("reasoning", "")
            if reasoning:
                parts.append(f"— {reasoning[:80]}")

            lines.append(" ".join(parts))

        return "\n".join(lines)

    # Resolution to send to LLM (smaller = more accurate coordinates)
    LLM_MAX_WIDTH = 1280
    LLM_MAX_HEIGHT = 720

    def get_next_action(self, goal: str, screenshot: Screenshot) -> Action:
        """Determine the next action to take given the current screen state."""
        history_str = self._format_history()
        stuck_warning = self._detect_stuck()

        # Resize screenshot for LLM (smaller images = better coordinate accuracy)
        original_width = screenshot.width
        original_height = screenshot.height
        llm_screenshot = screenshot.resize(self.LLM_MAX_WIDTH, self.LLM_MAX_HEIGHT)
        scale_x = original_width / llm_screenshot.width
        scale_y = original_height / llm_screenshot.height

        user_prompt = PLANNER_USER_PROMPT.format(
            goal=goal,
            history=history_str,
            stuck_warning=stuck_warning,
            screen_width=llm_screenshot.width,
            screen_height=llm_screenshot.height,
            screen_max_x=llm_screenshot.width - 1,
            screen_max_y=llm_screenshot.height - 1,
        )

        response = self._call_llm(llm_screenshot, PLANNER_SYSTEM_PROMPT, user_prompt)
        logger.debug("Planner response: %s", response)

        try:
            action = self._parse_action(response)
        except (json.JSONDecodeError, ValueError, KeyError) as e:
            logger.error("Failed to parse planner response: %s", e)
            return Action(
                action_type=ActionType.FAIL,
                reasoning=f"Failed to parse LLM response: {e}",
            )

        # Scale coordinates back to original screen resolution
        if action.x is not None:
            action.x = int(action.x * scale_x)
        if action.y is not None:
            action.y = int(action.y * scale_y)

        logger.debug(
            "Coordinate scaling: LLM(%dx%d) -> Screen(%dx%d), scale=(%.2f, %.2f)",
            llm_screenshot.width,
            llm_screenshot.height,
            original_width,
            original_height,
            scale_x,
            scale_y,
        )

        # Record in history
        self.history.append(action.to_dict())

        return action

    def create_plan(self, goal: str, screenshot: Screenshot) -> Plan:
        """Create a full plan for completing a task (multi-step)."""
        system = (
            PLANNER_SYSTEM_PROMPT
            + """

SPECIAL MODE: Instead of returning a single action, create a FULL PLAN with multiple steps.

Return JSON:
{
  "reasoning": "Overall strategy for completing the task",
  "actions": [
    {"action_type": "...", "target": "...", "text": "...", "reasoning": "..."},
    ...
  ]
}"""
        )
        user = f"## Task\n{goal}\n\nCreate a full plan with all steps needed."

        response = self._call_llm(screenshot, system, user)
        logger.debug("Plan response: %s", response)

        try:
            if "```json" in response:
                start = response.index("```json") + 7
                end = response.index("```", start)
                json_str = response[start:end]
            elif "```" in response:
                start = response.index("```") + 3
                end = response.index("```", start)
                json_str = response[start:end]
            else:
                json_str = response

            data = json.loads(json_str.strip())

            actions = []
            for a_data in data.get("actions", []):
                actions.append(
                    Action(
                        action_type=ActionType(a_data["action_type"]),
                        target=a_data.get("target"),
                        x=a_data.get("x"),
                        y=a_data.get("y"),
                        text=a_data.get("text"),
                        keys=a_data.get("keys"),
                        direction=a_data.get("direction"),
                        amount=a_data.get("amount"),
                        reasoning=a_data.get("reasoning", ""),
                    )
                )

            return Plan(
                goal=goal,
                actions=actions,
                reasoning=data.get("reasoning", ""),
            )
        except (json.JSONDecodeError, ValueError, KeyError) as e:
            logger.error("Failed to parse plan: %s", e)
            return Plan(goal=goal, actions=[], reasoning=f"Failed to create plan: {e}")

    def reset(self) -> None:
        """Reset the planner history."""
        self.history = []
