"""Hierarchical task planner with SoM-enhanced vision.

Implements a two-level planning architecture inspired by Agent S2/S3:
1. High-level planner: Decomposes goals into subtasks
2. Step executor: Determines precise actions using SoM-annotated screenshots

This compositional approach outperforms monolithic planners, as shown by
Agent S3 achieving 69.9% on OSWorld (vs ~22% for monolithic approaches).
"""

from __future__ import annotations

import json
import logging

from screenpilot.config import LLMConfig
from screenpilot.planner.memory import TaskMemoryTree
from screenpilot.planner.planner import Action, ActionType
from screenpilot.vision.capture import Screenshot
from screenpilot.vision.som import (
    SoMResult,
)

logger = logging.getLogger(__name__)


DECOMPOSE_PROMPT = """You are a task decomposition specialist. Given a high-level goal and the current screen state, break down the goal into 3-8 ordered subtasks.

## Goal
{goal}

## Current Task Memory
{memory_context}

## Instructions
Decompose the remaining work into concrete, actionable subtasks. Each subtask should be:
- A single logical step (e.g., "Click the File menu", "Type the search query")
- Ordered correctly
- Specific enough to execute

Return JSON:
{{
  "reasoning": "Overall strategy",
  "subtasks": [
    {{"description": "Step 1: ...", "type": "interaction|verification|navigation"}},
    {{"description": "Step 2: ...", "type": "interaction|verification|navigation"}}
  ]
}}"""


STEP_EXECUTE_PROMPT = """You are a precise action executor. Look at this SoM-annotated screenshot where UI elements are marked with numbered bounding boxes.

## Current Subtask
{subtask}

## Task Memory
{memory_context}

## Instructions
Determine the exact action to perform for this subtask. Reference elements by their mark number.

Return JSON:
{{
  "reasoning": "What I see and what I should do",
  "action_type": "click|double_click|right_click|type|key|scroll|wait|done|fail",
  "mark_id": <mark number to interact with, if applicable>,
  "text": "text to type, if applicable",
  "keys": "keyboard shortcut, if applicable",
  "direction": "up|down, for scrolling",
  "subtask_complete": true/false,
  "observation": "what happened or what I observe on screen"
}}"""


VERIFY_PROMPT = """Look at this screenshot. The previous action was: {action_description}

Did the action succeed? What changed on screen?

Return JSON:
{{
  "success": true/false,
  "observation": "what changed or what went wrong",
  "screen_state": "brief description of current screen"
}}"""


class HierarchicalPlanner:
    """Two-level planner: high-level decomposition + precise step execution."""

    def __init__(self, config: LLMConfig | None = None):
        self.config = config or LLMConfig()
        self._client = None
        self.memory: TaskMemoryTree | None = None

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
        return self._client

    def _call_vision(self, screenshot: Screenshot, prompt: str, system: str = "") -> str:
        """Call LLM with vision."""
        client = self._get_client()
        img_b64 = screenshot.to_base64(format="png")

        if self.config.provider == "anthropic":
            kwargs = {}
            if system:
                kwargs["system"] = system
            response = client.messages.create(
                model=self.config.model,
                max_tokens=self.config.max_tokens,
                temperature=self.config.temperature,
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
                            {"type": "text", "text": prompt},
                        ],
                    }
                ],
                **kwargs,
            )
            return response.content[0].text
        else:
            messages = []
            if system:
                messages.append({"role": "system", "content": system})
            messages.append(
                {
                    "role": "user",
                    "content": [
                        {
                            "type": "image_url",
                            "image_url": {"url": f"data:image/png;base64,{img_b64}"},
                        },
                        {"type": "text", "text": prompt},
                    ],
                }
            )
            response = client.chat.completions.create(
                model=self.config.model,
                max_tokens=self.config.max_tokens,
                temperature=self.config.temperature,
                messages=messages,
            )
            return response.choices[0].message.content

    def _parse_json(self, text: str) -> dict:
        """Extract JSON from LLM response."""
        if "```json" in text:
            start = text.index("```json") + 7
            end = text.index("```", start)
            text = text[start:end]
        elif "```" in text:
            start = text.index("```") + 3
            end = text.index("```", start)
            text = text[start:end]
        return json.loads(text.strip())

    def initialize(self, goal: str) -> None:
        """Initialize the planner with a new goal."""
        self.memory = TaskMemoryTree(goal)

    def decompose(self, goal: str, screenshot: Screenshot) -> list[str]:
        """Decompose a goal into subtasks using the current screen state."""
        if self.memory is None:
            self.initialize(goal)

        memory_context = self.memory.get_context()
        prompt = DECOMPOSE_PROMPT.format(goal=goal, memory_context=memory_context)

        response = self._call_vision(screenshot, prompt)
        logger.debug("Decomposition response: %s", response)

        try:
            data = self._parse_json(response)
            subtask_ids = []
            for st in data.get("subtasks", []):
                task_id = self.memory.add_subtask(st["description"])
                subtask_ids.append(task_id)
            return subtask_ids
        except (json.JSONDecodeError, KeyError) as e:
            logger.error("Failed to decompose: %s", e)
            return []

    def get_next_action(
        self,
        screenshot: Screenshot,
        som_result: SoMResult | None = None,
    ) -> tuple[Action, bool]:
        """Get the next action using SoM-annotated screenshot.

        Returns:
            Tuple of (action, subtask_complete)
        """
        if self.memory is None:
            return Action(action_type=ActionType.FAIL, reasoning="Planner not initialized"), False

        active = self.memory.active_task
        if active is None:
            return Action(action_type=ActionType.DONE, reasoning="No active task"), True

        # Use SoM-annotated screenshot if available
        if som_result is not None:
            annotated_ss = Screenshot(
                image=som_result.annotated_image,
                timestamp=screenshot.timestamp,
                monitor_index=screenshot.monitor_index,
                width=som_result.annotated_image.width,
                height=som_result.annotated_image.height,
            )
            target_screenshot = annotated_ss
        else:
            target_screenshot = screenshot

        memory_context = self.memory.get_context()
        prompt = STEP_EXECUTE_PROMPT.format(
            subtask=active.description,
            memory_context=memory_context,
        )

        response = self._call_vision(target_screenshot, prompt)
        logger.debug("Step execution response: %s", response)

        try:
            data = self._parse_json(response)
        except (json.JSONDecodeError, ValueError) as e:
            logger.error("Failed to parse step response: %s", e)
            return Action(action_type=ActionType.FAIL, reasoning=str(e)), False

        # Resolve mark_id to coordinates
        x, y = None, None
        mark_id = data.get("mark_id")
        if mark_id is not None and som_result is not None:
            region = som_result.get_region(mark_id)
            if region:
                x, y = region.center

        action = Action(
            action_type=ActionType(data.get("action_type", "fail")),
            x=x,
            y=y,
            text=data.get("text"),
            keys=data.get("keys"),
            direction=data.get("direction"),
            reasoning=data.get("reasoning", ""),
        )

        # Record in memory
        self.memory.add_action(action.to_dict())
        if data.get("observation"):
            self.memory.add_observation(data["observation"])

        subtask_complete = data.get("subtask_complete", False)
        if subtask_complete:
            self.memory.complete_task(active.id, data.get("observation", ""))

        return action, subtask_complete

    def verify_action(self, screenshot: Screenshot, action_desc: str) -> dict:
        """Verify whether the last action succeeded."""
        prompt = VERIFY_PROMPT.format(action_description=action_desc)
        response = self._call_vision(screenshot, prompt)

        try:
            data = self._parse_json(response)
            if data.get("observation"):
                self.memory.add_observation(data["observation"])
            return data
        except (json.JSONDecodeError, ValueError):
            return {"success": True, "observation": "Verification failed to parse"}

    def reset(self) -> None:
        """Reset the planner."""
        self.memory = None
        self._client = None
