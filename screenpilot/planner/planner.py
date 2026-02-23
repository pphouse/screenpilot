"""LLM-based task planner that decomposes goals into executable actions.

v2: Inspired by OSWorld top-performing agents (O3, CoACT, UI-TARS).
Key improvements over v1:
  - Multi-turn conversation with screenshot history (agent "remembers" what it saw)
  - Observation→Thought→Action structured reasoning (O3 pattern)
  - Step counter "Step X of N" for pacing awareness
  - Explicit anti-repeat instructions
  - Parse retry with temperature adjustment
  - Sliding window for trajectory (last N screenshots as images, older as text)
"""

from __future__ import annotations

import json
import logging
import time
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
    observation: str = ""  # What the agent observed on screen
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


# =============================================================================
# System prompt: Inspired by OSWorld O3 agent's Observation→Thought→Action
# =============================================================================

PLANNER_SYSTEM_PROMPT = """You are ScreenPilot, an AI agent that controls a computer by analyzing screenshots and performing mouse/keyboard actions. You operate on an x86_64 Linux machine with internet access.

## Available Actions

Mouse: click, double_click, right_click, drag (with start/end coords)
Keyboard: type (text input), key (shortcuts like "ctrl+c", "enter", "tab")
Navigation: scroll (up/down), wait (pause for loading)
Vision: find_and_click (describe element to locate), find_and_type (find element and type into it)
Control: done (task complete), fail (task impossible)

## Response Format

You MUST respond with ONLY a JSON object (no markdown, no code fences, no explanation outside JSON):
{
  "observation": "Describe EXACTLY what you see on the current screenshot: what page/app is shown, what UI elements are visible, any popups/dialogs/errors, what has changed since the last screenshot",
  "thought": "1) Progress so far: what steps are done, what remains. 2) If previous action failed or screen didn't change, analyze WHY. 3) Consider 2-3 possible next actions. 4) Pick the best one and explain why.",
  "action_type": "click|type|key|scroll|find_and_click|find_and_type|drag|wait|done|fail",
  "target": "description of UI element (for find_and_* actions only)",
  "x": 100,
  "y": 200,
  "text": "text to type (for type/find_and_type actions)",
  "keys": "ctrl+c (for key actions)",
  "direction": "up|down (for scroll)",
  "amount": 3
}

## Critical Rules

1. OBSERVATION FIRST: Always describe what you see BEFORE deciding what to do. Compare the current screenshot with what you expected from your last action.

2. NEVER REPEAT FAILED ACTIONS: If you clicked coordinates and the screen didn't change, that click FAILED. Do NOT click the same spot again. Instead:
   - Try find_and_click with a text description of the element
   - Try keyboard navigation (Tab, Enter, Shift+Tab, arrow keys)
   - Try clicking at significantly different coordinates
   - Try scrolling to reveal hidden elements

3. SINGLE ACTION: Return exactly ONE action per response. Wait for the next screenshot to see the result before acting again.

4. COORDINATE PRECISION: The screenshot resolution is provided. Coordinates (0,0) = top-left. Be precise — look carefully at element positions. When unsure, prefer find_and_click over guessing coordinates.

5. KEYBOARD SHORTCUTS: Prefer keyboard shortcuts when they're more reliable than clicking:
   - Ctrl+L to focus browser address bar
   - / to focus search on many sites (YouTube, GitHub, etc.)
   - Tab to move between form fields
   - Enter to submit forms

6. AVOID GOOGLE LENS: NEVER click the camera/lens icon in Chrome's address bar or search boxes. If Google Lens overlay appears ("Select any text or image to search with Google Lens"), press Escape immediately to dismiss it, then use keyboard (Ctrl+L) to focus the address bar instead.

7. COMPLETION: Return "done" ONLY when you can visually confirm the task is complete. Return "fail" with explanation if the task is impossible (wrong page, login required, etc.)."""


# =============================================================================
# User prompt template — includes step counter + history
# =============================================================================

PLANNER_USER_PROMPT = """## Step {step_num} of {max_steps}
Screen resolution: {screen_width}x{screen_height} pixels.

## Task
{goal}

## Action History
{history}
{stuck_warning}
Analyze the screenshot and determine the NEXT SINGLE ACTION. Respond with ONLY a JSON object."""


class TaskPlanner:
    """Plans and decomposes tasks using LLM reasoning.

    v2: Multi-turn conversation with screenshot history for much better
    context awareness across steps.
    """

    # Resolution to send to LLM (smaller = more accurate coordinates)
    LLM_MAX_WIDTH = 1280
    LLM_MAX_HEIGHT = 720

    # How many recent screenshots to include as actual images in conversation
    MAX_IMAGE_HISTORY = 3
    # How many older steps to include as text-only summaries
    MAX_TEXT_HISTORY = 7

    def __init__(self, config: LLMConfig | None = None):
        self.config = config or LLMConfig()
        self._client = None
        self.history: list[dict] = []
        # Multi-turn conversation state
        self._messages: list[dict] = []
        self._step_num: int = 0
        self._max_steps: int = 50
        # Token usage tracking for cost estimation
        self.total_input_tokens: int = 0
        self.total_output_tokens: int = 0

        # For non-Anthropic providers, strip find_and_* from system prompt
        # (they require Anthropic ScreenAnalyzer for coordinate resolution)
        if self.config.provider != "anthropic":
            self._system_prompt = PLANNER_SYSTEM_PROMPT.replace(
                "Vision: find_and_click (describe element to locate), find_and_type (find element and type into it)\n", ""
            ).replace(
                "find_and_click|find_and_type|", ""
            ).replace(
                '   - Try find_and_click with a text description of the element\n', ""
            ).replace(
                "When unsure, prefer find_and_click over guessing coordinates.",
                "Look carefully at element positions in the screenshot."
            ).replace(
                "- Use find_and_click with a text description\n", ""
            )
        else:
            self._system_prompt = PLANNER_SYSTEM_PROMPT

        # Claude Code subprocess: temp dir for screenshots
        if self.config.provider == "claude_code":
            import tempfile
            self._cc_tmpdir = tempfile.mkdtemp(prefix="screenpilot_cc_")
            self._cc_model = self.config.model or "sonnet"

    def _get_client(self):
        """Lazy-initialize the LLM client."""
        if self.config.provider == "claude_code":
            return None  # No API client needed; uses subprocess

        if self._client is not None:
            return self._client

        if self.config.provider == "anthropic":
            import anthropic

            self._client = anthropic.Anthropic(api_key=self.config.api_key)
        elif self.config.provider == "azure":
            import openai

            self._client = openai.AzureOpenAI(
                azure_endpoint=self.config.azure_endpoint,
                api_key=self.config.api_key,
                api_version=self.config.azure_api_version,
            )
        elif self.config.provider == "gemini":
            from google import genai

            self._client = genai.Client(api_key=self.config.api_key)
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

    def _call_llm_multiturn(
        self,
        screenshot: Screenshot,
        user_text: str,
        temperature: float | None = None,
    ) -> str:
        """Call LLM with full conversation history including screenshot images.

        Key difference from v1: maintains multi-turn conversation so the LLM
        can "remember" previous screenshots and compare them with current state.
        """
        client = self._get_client()
        temp = temperature if temperature is not None else self.config.temperature

        # ── Claude Code subprocess path ──────────────────────────────
        if self.config.provider == "claude_code":
            return self._call_claude_code(screenshot, user_text)

        img_b64 = screenshot.to_base64(format="png")

        # Build current user message with screenshot
        user_content = [
            {
                "type": "image",
                "source": {
                    "type": "base64",
                    "media_type": "image/png",
                    "data": img_b64,
                },
            },
            {"type": "text", "text": user_text},
        ]

        if self.config.provider == "anthropic":
            # Build message list: old messages + current
            messages = list(self._messages) + [
                {"role": "user", "content": user_content}
            ]

            response = client.messages.create(
                model=self.config.model,
                max_tokens=self.config.max_tokens,
                temperature=temp,
                system=self._system_prompt,
                messages=messages,
            )
            response_text = response.content[0].text

            # Track token usage
            if hasattr(response, "usage"):
                self.total_input_tokens += getattr(response.usage, "input_tokens", 0)
                self.total_output_tokens += getattr(response.usage, "output_tokens", 0)

            # Save to conversation history
            self._messages.append({"role": "user", "content": user_content})
            self._messages.append(
                {"role": "assistant", "content": response_text}
            )

            # Sliding window: keep conversation manageable
            self._trim_messages()

            return response_text

        elif self.config.provider in ("openai", "azure"):
            # OpenAI / Azure OpenAI format
            user_content_oai = [
                {
                    "type": "image_url",
                    "image_url": {"url": f"data:image/png;base64,{img_b64}", "detail": "auto"},
                },
                {"type": "text", "text": user_text},
            ]

            messages = (
                [{"role": "system", "content": self._system_prompt}]
                + list(self._messages)
                + [{"role": "user", "content": user_content_oai}]
            )

            # Azure OpenAI: max_completion_tokens instead of max_tokens
            if self.config.provider == "azure":
                model = self.config.azure_deployment or self.config.model
                kwargs = dict(
                    model=model,
                    max_completion_tokens=self.config.max_tokens,
                    messages=messages,
                )
                # GPT-5.2 supports temperature; GPT-5 doesn't
                if temp is not None and self.config.temperature is not None:
                    kwargs["temperature"] = temp
                response = client.chat.completions.create(**kwargs)
            else:
                response = client.chat.completions.create(
                    model=self.config.model,
                    max_tokens=self.config.max_tokens,
                    temperature=temp,
                    messages=messages,
                )
            response_text = response.choices[0].message.content or ""

            # Track tokens
            if hasattr(response, "usage") and response.usage:
                self.total_input_tokens += getattr(response.usage, "prompt_tokens", 0) or 0
                self.total_output_tokens += getattr(response.usage, "completion_tokens", 0) or 0

            self._messages.append({"role": "user", "content": user_content_oai})
            self._messages.append(
                {"role": "assistant", "content": response_text}
            )
            self._trim_messages()

            return response_text

        elif self.config.provider == "gemini":
            # Google Gemini format
            from google.genai import types
            import PIL.Image

            contents = []
            # Add conversation history as text
            for msg in self._messages:
                role = "user" if msg["role"] == "user" else "model"
                text = msg["content"] if isinstance(msg["content"], str) else "(previous step)"
                contents.append(types.Content(role=role, parts=[types.Part.from_text(text=text)]))

            # Add current screenshot + text
            contents.append(types.Content(
                role="user",
                parts=[
                    types.Part.from_image(image=screenshot.image),
                    types.Part.from_text(text=user_text),
                ],
            ))

            response = client.models.generate_content(
                model=self.config.model,
                contents=contents,
                config=types.GenerateContentConfig(
                    system_instruction=self._system_prompt,
                    max_output_tokens=self.config.max_tokens,
                    temperature=temp if temp is not None else 1.0,
                ),
            )
            response_text = response.text or ""

            # Track tokens
            if hasattr(response, "usage_metadata") and response.usage_metadata:
                self.total_input_tokens += getattr(response.usage_metadata, "prompt_token_count", 0) or 0
                self.total_output_tokens += getattr(response.usage_metadata, "candidates_token_count", 0) or 0

            self._messages.append({"role": "user", "content": user_text})
            self._messages.append(
                {"role": "assistant", "content": response_text}
            )
            self._trim_messages()

            return response_text

        else:
            # litellm fallback — same as OpenAI format
            import litellm

            user_content_oai = [
                {
                    "type": "image_url",
                    "image_url": {"url": f"data:image/png;base64,{img_b64}"},
                },
                {"type": "text", "text": user_text},
            ]

            messages = (
                [{"role": "system", "content": self._system_prompt}]
                + list(self._messages)
                + [{"role": "user", "content": user_content_oai}]
            )

            response = litellm.completion(
                model=self.config.model,
                max_tokens=self.config.max_tokens,
                temperature=temp,
                messages=messages,
            )
            response_text = response.choices[0].message.content

            self._messages.append({"role": "user", "content": user_content_oai})
            self._messages.append(
                {"role": "assistant", "content": response_text}
            )
            self._trim_messages()

            return response_text

    def _call_claude_code(self, screenshot: Screenshot, user_text: str) -> str:
        """Call Claude Code CLI (`claude -p`) with session resume.

        Uses the user's Claude Code subscription (no API key needed).
        - First call: --session-id + --system-prompt to establish context
        - Subsequent calls: --resume to continue with full conversation history
        This gives the model memory of previous screenshots and actions.
        """
        import os
        import subprocess

        # Save screenshot to temp file
        img_path = os.path.join(self._cc_tmpdir, f"step_{self._step_num:03d}.png")
        screenshot.image.save(img_path, "PNG")

        # User prompt: read screenshot + step instructions
        prompt = f"Read the screenshot at {img_path} and analyze it carefully.\n\n{user_text}"

        # Build command
        env = os.environ.copy()
        env.pop("CLAUDECODE", None)

        is_first_call = not hasattr(self, "_cc_session_id") or self._cc_session_id is None

        if is_first_call:
            import uuid
            self._cc_session_id = str(uuid.uuid4())
            cmd = [
                "claude", "-p", prompt,
                "--session-id", self._cc_session_id,
                "--system-prompt", self._system_prompt,
                "--allowedTools", "Read",
                "--model", self._cc_model,
                "--output-format", "text",
            ]
        else:
            cmd = [
                "claude", "-p", prompt,
                "--resume", self._cc_session_id,
                "--allowedTools", "Read",
                "--model", self._cc_model,
                "--output-format", "text",
            ]

        try:
            # Use temp files for stdout/stderr to avoid pipe inheritance hang.
            # When `claude` spawns background processes that inherit pipe FDs,
            # subprocess.run with capture_output=True blocks forever.
            import tempfile
            stdout_file = os.path.join(self._cc_tmpdir, f"stdout_{self._step_num:03d}.txt")
            stderr_file = os.path.join(self._cc_tmpdir, f"stderr_{self._step_num:03d}.txt")
            with open(stdout_file, "w") as fout, open(stderr_file, "w") as ferr:
                proc = subprocess.Popen(
                    cmd,
                    stdout=fout,
                    stderr=ferr,
                    env=env,
                    start_new_session=True,
                )
                try:
                    proc.wait(timeout=120)
                except subprocess.TimeoutExpired:
                    import signal
                    os.killpg(os.getpgid(proc.pid), signal.SIGTERM)
                    try:
                        proc.wait(timeout=5)
                    except subprocess.TimeoutExpired:
                        os.killpg(os.getpgid(proc.pid), signal.SIGKILL)
                        proc.wait(timeout=5)
                    raise

            with open(stdout_file, "r") as f:
                response_text = f.read().strip()
            if proc.returncode != 0 and not response_text:
                with open(stderr_file, "r") as f:
                    response_text = f.read().strip()
                logger.error("claude -p error (step %d): %s", self._step_num, response_text)
                # If resume fails, fall back to fresh session
                if not is_first_call and ("session" in response_text.lower() or "error" in response_text.lower()):
                    logger.warning("Session resume failed, falling back to fresh session")
                    self._cc_session_id = None
                    return self._call_claude_code(screenshot, user_text)
        except subprocess.TimeoutExpired:
            logger.error("claude -p timed out after 120s at step %d", self._step_num)
            response_text = '{"action_type": "wait", "observation": "timeout", "thought": "Claude Code subprocess timed out"}'
        except Exception as e:
            logger.error("claude -p exception at step %d: %s", self._step_num, e)
            response_text = '{"action_type": "wait", "observation": "error", "thought": "Claude Code subprocess error: ' + str(e).replace('"', "'") + '"}'

        # Rough token estimation
        self.total_input_tokens += 2000 + len(prompt) // 4
        self.total_output_tokens += len(response_text) // 4

        return response_text

    def _trim_messages(self) -> None:
        """Trim conversation history to manage token budget.

        Strategy (from OSWorld O3 agent):
        - Keep the most recent MAX_IMAGE_HISTORY turns with full images
        - Convert older turns to text-only (remove image data, keep text summary)
        - Drop turns beyond MAX_TEXT_HISTORY + MAX_IMAGE_HISTORY
        """
        if len(self._messages) <= self.MAX_IMAGE_HISTORY * 2:
            return

        max_total = (self.MAX_IMAGE_HISTORY + self.MAX_TEXT_HISTORY) * 2
        if len(self._messages) > max_total:
            self._messages = self._messages[-max_total:]

        # Convert older messages' images to text placeholders
        image_boundary = len(self._messages) - (self.MAX_IMAGE_HISTORY * 2)
        for i in range(0, image_boundary):
            msg = self._messages[i]
            if msg["role"] == "user" and isinstance(msg["content"], list):
                # Replace image blocks with text placeholder
                new_content = []
                for block in msg["content"]:
                    if isinstance(block, dict) and block.get("type") == "image":
                        new_content.append(
                            {"type": "text", "text": "[Previous screenshot — see action history for details]"}
                        )
                    elif isinstance(block, dict) and block.get("type") == "image_url":
                        new_content.append(
                            {"type": "text", "text": "[Previous screenshot — see action history for details]"}
                        )
                    else:
                        new_content.append(block)
                self._messages[i] = {"role": "user", "content": new_content}

    def _parse_action(self, text: str) -> Action:
        """Parse an action from LLM response."""
        # Extract JSON from possible code fences
        cleaned = text.strip()
        if "```json" in cleaned:
            start = cleaned.index("```json") + 7
            end = cleaned.index("```", start)
            cleaned = cleaned[start:end]
        elif "```" in cleaned:
            start = cleaned.index("```") + 3
            end = cleaned.index("```", start)
            cleaned = cleaned[start:end]

        data = json.loads(cleaned.strip())

        # Normalize common action_type aliases
        action_type_raw = data["action_type"].lower().strip()
        action_aliases = {
            "success": "done", "complete": "done", "finished": "done",
            "failure": "fail", "error": "fail",
            "press": "key", "keypress": "key", "keyboard": "key",
            "enter": "key", "hotkey": "key",
            "left_click": "click", "single_click": "click",
            "find_and_click": "click", "find_and_type": "type",
            "none": "wait", "observe": "wait", "noop": "wait",
            "bash_command": "fail", "command": "fail", "execute": "fail",
            "navigate": "click", "open_url": "key",
            "triple_click": "click", "select_all": "key",
        }
        action_type_str = action_aliases.get(action_type_raw, action_type_raw)

        # For key actions, ensure keys field is present
        keys = data.get("keys")
        if action_type_str == "key" and not keys:
            # Try to extract from text or target field
            keys = data.get("text") or data.get("target") or "enter"

        return Action(
            action_type=ActionType(action_type_str),
            target=data.get("target"),
            x=data.get("x"),
            y=data.get("y"),
            text=data.get("text"),
            keys=keys,
            direction=data.get("direction"),
            amount=data.get("amount"),
            duration=data.get("duration"),
            reasoning=data.get("thought", data.get("reasoning", "")),
            observation=data.get("observation", ""),
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
                "\n⚠️ CRITICAL: You clicked ({}, {}) multiple times with NO screen change. "
                "This is NOT working. You MUST choose a COMPLETELY DIFFERENT approach NOW:\n"
                "- Use find_and_click with a text description\n"
                "- Use keyboard: Tab to navigate, Enter to select, Ctrl+L for address bar\n"
                "- Click at very different coordinates\n"
                "- Scroll to find the element\n"
                "- If stuck, return 'fail' with explanation\n"
            ).format(coords[0][0], coords[0][1])

        # Check if same action type repeated 3+ times without progress
        action_types = [h.get("action_type") for h in recent]
        if len(action_types) >= 3 and len(set(action_types)) == 1:
            if action_types[0] in ("click", "find_and_click"):
                return (
                    "\n⚠️ WARNING: You repeated '{}' 3 times. Try a different action type "
                    "(keyboard shortcut, scroll, type, etc.).\n"
                ).format(action_types[0])

        return ""

    def _format_history(self) -> str:
        """Format action history for context."""
        if not self.history:
            return "No actions taken yet."

        recent = self.history[-10:]
        lines = []
        for i, h in enumerate(recent):
            action_type = h.get("action_type", "?")
            parts = [f"Step {i + 1}: {action_type}"]

            x, y = h.get("x"), h.get("y")
            if x is not None and y is not None:
                parts.append(f"at ({x}, {y})")

            target = h.get("target")
            if target:
                parts.append(f'target="{target}"')

            text = h.get("text")
            if text:
                parts.append(f'text="{text[:30]}"')

            keys = h.get("keys")
            if keys:
                parts.append(f'keys="{keys}"')

            # Include observation summary (new in v2)
            obs = h.get("observation", "")
            if obs:
                parts.append(f"[saw: {obs[:60]}]")

            lines.append(" ".join(parts))

        return "\n".join(lines)

    def get_next_action(
        self, goal: str, screenshot: Screenshot, max_steps: int = 50
    ) -> Action:
        """Determine the next action given current screen state.

        v2: Uses multi-turn conversation so LLM can compare current
        screenshot with previous ones.
        """
        self._step_num += 1
        self._max_steps = max_steps

        history_str = self._format_history()
        stuck_warning = self._detect_stuck()

        # Resize screenshot for LLM
        original_width = screenshot.width
        original_height = screenshot.height
        llm_screenshot = screenshot.resize(self.LLM_MAX_WIDTH, self.LLM_MAX_HEIGHT)
        scale_x = original_width / llm_screenshot.width
        scale_y = original_height / llm_screenshot.height

        # Add completion nudge when approaching step limit
        completion_nudge = ""
        if self._step_num >= max_steps - 2:
            completion_nudge = (
                "\n⚠️ APPROACHING STEP LIMIT. If the task goal appears achieved "
                "(even partially), return action_type \"done\" NOW. "
                "Do NOT continue exploring — declare completion or failure.\n"
            )

        user_prompt = PLANNER_USER_PROMPT.format(
            step_num=self._step_num,
            max_steps=max_steps,
            goal=goal,
            history=history_str,
            stuck_warning=stuck_warning + completion_nudge,
            screen_width=llm_screenshot.width,
            screen_height=llm_screenshot.height,
        )

        # Try up to 3 times with increasing temperature (OSWorld pattern)
        last_error = None
        for attempt in range(3):
            if self.config.temperature is None:
                temp = None  # Model doesn't support temperature (e.g. GPT-5)
            else:
                temp = None if attempt == 0 else min(0.5 + attempt * 0.3, 1.0)
            try:
                response = self._call_llm_multiturn(
                    llm_screenshot, user_prompt, temperature=temp
                )
                logger.debug("Planner response (attempt %d): %s", attempt + 1, response)
                action = self._parse_action(response)
                break
            except (json.JSONDecodeError, ValueError, KeyError) as e:
                last_error = e
                logger.warning(
                    "Parse attempt %d failed: %s. Retrying with higher temperature.",
                    attempt + 1, e,
                )
                # Remove the failed assistant message from history
                if self._messages and self._messages[-1]["role"] == "assistant":
                    self._messages.pop()
                if self._messages and self._messages[-1]["role"] == "user":
                    self._messages.pop()
                time.sleep(0.5)
        else:
            logger.error("All parse attempts failed: %s", last_error)
            return Action(
                action_type=ActionType.FAIL,
                reasoning=f"Failed to parse LLM response after 3 attempts: {last_error}",
            )

        # Scale coordinates back to original screen resolution
        if action.x is not None:
            action.x = int(action.x * scale_x)
        if action.y is not None:
            action.y = int(action.y * scale_y)

        # Record in history
        self.history.append(action.to_dict())

        return action

    @property
    def estimated_cost_usd(self) -> float:
        """Estimate API cost in USD based on token usage."""
        # Pricing per provider (per 1M tokens)
        pricing = {
            "anthropic": (3.0, 15.0),    # Claude Sonnet 4.5
            "azure": (2.0, 10.0),         # GPT-5 (estimate)
            "gemini": (1.25, 10.0),       # Gemini 2.5 Pro
            "openai": (2.5, 10.0),        # GPT-4o
            "claude_code": (0.0, 0.0),   # Subscription-based, no per-token cost
        }
        inp_price, out_price = pricing.get(self.config.provider, (3.0, 15.0))
        input_cost = self.total_input_tokens * inp_price / 1_000_000
        output_cost = self.total_output_tokens * out_price / 1_000_000
        return input_cost + output_cost

    def reset(self) -> None:
        """Reset the planner state for a new task."""
        self.history = []
        self._messages = []
        self._step_num = 0
        self.total_input_tokens = 0
        self.total_output_tokens = 0
        # Reset Claude Code session for fresh conversation
        if self.config.provider == "claude_code":
            self._cc_session_id = None

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

        llm_screenshot = screenshot.resize(self.LLM_MAX_WIDTH, self.LLM_MAX_HEIGHT)

        # Use single-shot for planning
        client = self._get_client()
        img_b64 = llm_screenshot.to_base64(format="png")

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
            response_text = response.content[0].text
        else:
            # OpenAI / litellm
            messages = [
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
            ]
            if self.config.provider == "openai":
                resp = client.chat.completions.create(
                    model=self.config.model,
                    max_tokens=self.config.max_tokens,
                    temperature=self.config.temperature,
                    messages=messages,
                )
                response_text = resp.choices[0].message.content
            else:
                import litellm
                resp = litellm.completion(
                    model=self.config.model,
                    max_tokens=self.config.max_tokens,
                    temperature=self.config.temperature,
                    messages=messages,
                )
                response_text = resp.choices[0].message.content

        logger.debug("Plan response: %s", response_text)

        try:
            cleaned = response_text.strip()
            if "```json" in cleaned:
                start = cleaned.index("```json") + 7
                end = cleaned.index("```", start)
                json_str = cleaned[start:end]
            elif "```" in cleaned:
                start = cleaned.index("```") + 3
                end = cleaned.index("```", start)
                json_str = cleaned[start:end]
            else:
                json_str = cleaned

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
