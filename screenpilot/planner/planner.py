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
- find_and_click: Describe a UI element to find and click
- find_and_type: Describe a UI element to find, click, and type into
- done: Task is complete
- fail: Task cannot be completed

## Response Format

Respond with a single JSON object:
{
  "reasoning": "Step-by-step reasoning about what you see and what to do",
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

1. Be PRECISE with coordinates - count pixels carefully
2. Always explain your reasoning
3. If you can't find a target element, try scrolling or looking elsewhere
4. Use find_and_click/find_and_type when you need vision-based element finding
5. Use keyboard shortcuts when they're more efficient
6. Return "done" when the task is clearly complete
7. Return "fail" with reasoning if the task is impossible"""


PLANNER_USER_PROMPT = """## Current Task
{goal}

## Task History
{history}

## Instructions
Look at the current screenshot and determine the NEXT SINGLE ACTION to take.
Respond with a JSON object as specified."""


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

    def get_next_action(self, goal: str, screenshot: Screenshot) -> Action:
        """Determine the next action to take given the current screen state."""
        history_str = ""
        if self.history:
            recent = self.history[-10:]  # Keep last 10 actions for context
            history_str = "\n".join(
                f"Step {i+1}: {h['action_type']} - {h.get('reasoning', '')}"
                for i, h in enumerate(recent)
            )
        else:
            history_str = "No actions taken yet."

        user_prompt = PLANNER_USER_PROMPT.format(goal=goal, history=history_str)

        response = self._call_llm(screenshot, PLANNER_SYSTEM_PROMPT, user_prompt)
        logger.debug("Planner response: %s", response)

        try:
            action = self._parse_action(response)
        except (json.JSONDecodeError, ValueError, KeyError) as e:
            logger.error("Failed to parse planner response: %s", e)
            return Action(
                action_type=ActionType.FAIL,
                reasoning=f"Failed to parse LLM response: {e}",
            )

        # Record in history
        self.history.append(action.to_dict())

        return action

    def create_plan(self, goal: str, screenshot: Screenshot) -> Plan:
        """Create a full plan for completing a task (multi-step)."""
        system = PLANNER_SYSTEM_PROMPT + """

SPECIAL MODE: Instead of returning a single action, create a FULL PLAN with multiple steps.

Return JSON:
{
  "reasoning": "Overall strategy for completing the task",
  "actions": [
    {"action_type": "...", "target": "...", "text": "...", "reasoning": "..."},
    ...
  ]
}"""
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
