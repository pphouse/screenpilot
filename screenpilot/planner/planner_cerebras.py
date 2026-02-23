"""Cerebras + Chandra OCR planner — text-only LLM with external OCR.

Architecture:
  1. Screenshot → pytesseract (local, fast) for text + coordinates
  2. Screenshot → Chandra/Datalab Marker API for structured content
  3. Combined text description → Cerebras GPT-OSS-120B for reasoning
  4. LLM returns action referencing element numbers or coordinates

Cost comparison vs Claude:
  - Cerebras: $0.25/M input, $0.69/M output (12-22x cheaper than Claude)
  - Chandra OCR: ~1 cent per image
  - pytesseract: free (local)
"""

from __future__ import annotations

import base64
import io
import json
import logging
import os
import re
import time
from dataclasses import dataclass, field
from typing import Any

import requests

from screenpilot.planner.planner import (
    Action,
    ActionType,
    Plan,
    PLANNER_USER_PROMPT,
)
from screenpilot.vision.capture import Screenshot

logger = logging.getLogger(__name__)


# =============================================================================
# System prompt adapted for text-only LLM (no vision)
# =============================================================================

CEREBRAS_SYSTEM_PROMPT = """You are ScreenPilot, an AI agent that controls a computer. Unlike a vision model, you CANNOT see screenshots directly. Instead, you receive:
1. **OCR text**: structured text extracted from the screen
2. **Element list**: numbered UI elements with their coordinates (x, y)

## Available Actions

Mouse: click, double_click, right_click, drag (with start/end coords)
Keyboard: type (text input), key (shortcuts like "ctrl+c", "enter", "tab")
Navigation: scroll (up/down), wait (pause for loading)
Control: done (task complete), fail (task impossible)

## Response Format

You MUST respond with ONLY a JSON object (no markdown, no code fences):
{
  "observation": "Describe what the OCR text tells you about the current screen state",
  "thought": "1) Progress so far. 2) If previous action failed, analyze why. 3) Pick the best next action.",
  "action_type": "click|type|key|scroll|drag|wait|done|fail",
  "element": 5,
  "x": 100,
  "y": 200,
  "text": "text to type",
  "keys": "ctrl+c",
  "direction": "up|down",
  "amount": 3
}

## How to Specify Coordinates

- **Preferred**: Use "element": N to click on element #N from the element list. The system will use that element's coordinates.
- **Alternative**: Specify "x" and "y" directly if you need to click somewhere not covered by an element.
- For keyboard actions (type, key), coordinates are optional.

## Critical Rules

1. READ THE OCR TEXT CAREFULLY: This is your only window into what's on screen. Look for buttons, links, input fields, headers, etc.
2. USE ELEMENT NUMBERS: When possible, reference elements by their number rather than guessing coordinates.
3. NEVER REPEAT FAILED ACTIONS: If an action didn't change the screen, try something different.
4. KEYBOARD SHORTCUTS are very reliable since they don't need coordinates:
   - Ctrl+L: focus browser address bar
   - Tab: move between form fields
   - Enter: submit / activate
   - Ctrl+A: select all text
5. SINGLE ACTION per response. Wait for the next OCR update to see the result.
6. Return "done" when the task is visually confirmed complete. Return "fail" if impossible."""


CEREBRAS_USER_PROMPT = """## Step {step_num} of {max_steps}
Screen resolution: {screen_width}x{screen_height} pixels.

## Task
{goal}

## OCR Content (structured text from screen)
{ocr_text}

## Clickable Elements (element_number: "text" at x,y)
{elements}

## Action History
{history}
{stuck_warning}
Analyze the OCR text and elements, then determine the NEXT SINGLE ACTION. Respond with ONLY a JSON object."""


# =============================================================================
# Chandra/Datalab OCR client
# =============================================================================

@dataclass
class ChandraOCRResult:
    """Result from Chandra OCR."""
    text: str
    raw_json: dict
    cost_cents: float
    runtime_seconds: float


class ChandraOCR:
    """Chandra/Datalab Marker API client for screenshot OCR."""

    API_URL = "https://www.datalab.to/api/v1/marker"

    def __init__(self, api_key: str):
        self.api_key = api_key
        self.total_cost_cents: float = 0.0
        self.total_calls: int = 0

    def ocr(self, image_bytes: bytes, timeout: int = 30) -> ChandraOCRResult:
        """Send image to Chandra API and get text back."""
        headers = {"X-API-Key": self.api_key}

        # Submit
        t0 = time.time()
        resp = requests.post(
            self.API_URL,
            files={"file": ("screenshot.png", image_bytes, "image/png")},
            data={"output_format": "markdown", "mode": "fast"},
            headers=headers,
            timeout=30,
        )
        resp.raise_for_status()
        result = resp.json()

        if not result.get("success", True):
            raise RuntimeError(f"Chandra API error: {result.get('error', 'unknown')}")

        # Poll if async
        if "request_check_url" in result:
            check_url = result["request_check_url"]
            deadline = t0 + timeout
            while time.time() < deadline:
                time.sleep(1.5)
                check_resp = requests.get(check_url, headers=headers, timeout=15)
                check_data = check_resp.json()
                status = check_data.get("status", "unknown")
                if status == "complete":
                    result = check_data
                    break
                elif status == "error":
                    raise RuntimeError(f"Chandra OCR error: {check_data}")
            else:
                raise TimeoutError("Chandra OCR timed out")

        runtime = time.time() - t0
        cost = result.get("total_cost", 0)
        self.total_cost_cents += cost
        self.total_calls += 1

        # Extract text
        text = result.get("markdown") or result.get("html") or ""
        if not text and result.get("json"):
            # Extract text from JSON structure
            text = self._extract_text_from_json(result["json"])

        return ChandraOCRResult(
            text=text,
            raw_json=result,
            cost_cents=cost,
            runtime_seconds=runtime,
        )

    def _extract_text_from_json(self, json_data) -> str:
        """Extract readable text from Marker JSON output."""
        if isinstance(json_data, str):
            try:
                json_data = json.loads(json_data)
            except json.JSONDecodeError:
                return json_data

        texts = []
        if isinstance(json_data, dict):
            for key in ("text", "html", "markdown"):
                if key in json_data and json_data[key]:
                    texts.append(str(json_data[key]))
            for child in json_data.get("children", []):
                texts.append(self._extract_text_from_json(child))
        elif isinstance(json_data, list):
            for item in json_data:
                texts.append(self._extract_text_from_json(item))

        return "\n".join(t for t in texts if t)


# =============================================================================
# Local pytesseract OCR for element coordinates
# =============================================================================

@dataclass
class ScreenElement:
    """A text element on screen with its coordinates."""
    index: int
    text: str
    x: int  # center x
    y: int  # center y
    width: int
    height: int
    confidence: int


def pytesseract_elements(image) -> list[ScreenElement]:
    """Extract text elements with coordinates using pytesseract."""
    try:
        import pytesseract
    except ImportError:
        logger.warning("pytesseract not available, returning empty elements")
        return []

    data = pytesseract.image_to_data(image, output_type=pytesseract.Output.DICT)
    elements = []
    idx = 1

    # Group words into lines for more meaningful elements
    current_line = []
    current_line_y = -1

    for i in range(len(data["text"])):
        text = data["text"][i].strip()
        conf = int(data["conf"][i])
        if not text or conf < 25:
            # Flush current line
            if current_line:
                elements.append(_merge_words(current_line, idx))
                idx += 1
                current_line = []
                current_line_y = -1
            continue

        word_y = data["top"][i]
        # Same line if y-coordinate is close
        if current_line and abs(word_y - current_line_y) < 10:
            current_line.append({
                "text": text,
                "left": data["left"][i],
                "top": data["top"][i],
                "width": data["width"][i],
                "height": data["height"][i],
                "conf": conf,
            })
        else:
            if current_line:
                elements.append(_merge_words(current_line, idx))
                idx += 1
            current_line = [{
                "text": text,
                "left": data["left"][i],
                "top": data["top"][i],
                "width": data["width"][i],
                "height": data["height"][i],
                "conf": conf,
            }]
            current_line_y = word_y

    if current_line:
        elements.append(_merge_words(current_line, idx))

    return elements


def _merge_words(words: list[dict], idx: int) -> ScreenElement:
    """Merge multiple words into a single line element."""
    text = " ".join(w["text"] for w in words)
    left = min(w["left"] for w in words)
    top = min(w["top"] for w in words)
    right = max(w["left"] + w["width"] for w in words)
    bottom = max(w["top"] + w["height"] for w in words)
    avg_conf = sum(w["conf"] for w in words) // len(words)
    return ScreenElement(
        index=idx,
        text=text[:80],  # truncate long lines
        x=(left + right) // 2,
        y=(top + bottom) // 2,
        width=right - left,
        height=bottom - top,
        confidence=avg_conf,
    )


def format_elements(elements: list[ScreenElement], max_elements: int = 60) -> str:
    """Format elements as numbered list for the LLM."""
    if not elements:
        return "(No text elements detected)"

    lines = []
    for e in elements[:max_elements]:
        lines.append(f"[{e.index}] \"{e.text}\" at ({e.x}, {e.y})")

    if len(elements) > max_elements:
        lines.append(f"... and {len(elements) - max_elements} more elements")

    return "\n".join(lines)


# =============================================================================
# Cerebras Planner
# =============================================================================

class CerebrasPlanner:
    """Task planner using Cerebras GPT-OSS-120B + Chandra OCR.

    Drop-in replacement for TaskPlanner with same interface.
    """

    LLM_MAX_WIDTH = 1920  # No resize needed since we use OCR not vision
    LLM_MAX_HEIGHT = 1080

    MAX_TEXT_HISTORY = 10

    def __init__(
        self,
        cerebras_api_key: str | None = None,
        cerebras_api_keys: list[str] | None = None,
        chandra_api_key: str | None = None,
        model: str = "gpt-oss-120b",
        # Azure OpenAI support
        backend: str = "cerebras",  # "cerebras" or "azure"
        azure_endpoint: str | None = None,
        azure_api_key: str | None = None,
        azure_deployment: str | None = None,
        azure_api_version: str = "2024-12-01-preview",
    ):
        self.backend = backend
        self.model = model
        self._key_index = 0

        if backend == "azure":
            self.azure_endpoint = azure_endpoint or os.environ.get("AZURE_OPENAI_ENDPOINT", "")
            self.azure_api_key = azure_api_key or os.environ.get("AZURE_OPENAI_API_KEY", "")
            self.azure_deployment = azure_deployment or os.environ.get("AZURE_OPENAI_DEPLOYMENT", "")
            self.azure_api_version = azure_api_version
            self.cerebras_api_keys = []
        else:
            # Cerebras: support multiple API keys for rate limit rotation
            if cerebras_api_keys:
                self.cerebras_api_keys = cerebras_api_keys
            else:
                key = cerebras_api_key or os.environ.get("CEREBRAS_API_KEY", "")
                extra = os.environ.get("CEREBRAS_API_KEY_2", "")
                self.cerebras_api_keys = [k for k in [key, extra] if k]

        self.chandra_api_key = chandra_api_key or os.environ.get("CHANDRA_API_KEY", "")

        # Initialize clients
        self._llm_clients: list = []
        self.chandra = ChandraOCR(self.chandra_api_key) if self.chandra_api_key else None

        # State
        self.history: list[dict] = []
        self._messages: list[dict] = []
        self._step_num: int = 0
        self._max_steps: int = 50
        self._elements: list[ScreenElement] = []

        # Cost tracking
        self.total_input_tokens: int = 0
        self.total_output_tokens: int = 0
        self.total_ocr_cost_cents: float = 0.0
        self.total_ocr_time: float = 0.0
        self.total_llm_time: float = 0.0
        self._last_llm_call: float = 0.0
        self._min_call_interval: float = 5.0 if backend == "cerebras" else 0.5

    def _get_llm_client(self):
        """Get LLM client (Cerebras or Azure OpenAI)."""
        import openai
        if not self._llm_clients:
            if self.backend == "azure":
                self._llm_clients.append(openai.AzureOpenAI(
                    azure_endpoint=self.azure_endpoint,
                    api_key=self.azure_api_key,
                    api_version=self.azure_api_version,
                ))
            else:
                for key in self.cerebras_api_keys:
                    self._llm_clients.append(openai.OpenAI(
                        base_url="https://api.cerebras.ai/v1",
                        api_key=key,
                    ))
        if not self._llm_clients:
            raise RuntimeError("No API keys configured")
        client = self._llm_clients[self._key_index % len(self._llm_clients)]
        return client

    def _rotate_key(self):
        """Switch to next API key after rate limit."""
        if len(self._llm_clients) > 1:
            self._key_index = (self._key_index + 1) % len(self._llm_clients)
            logger.info("Rotated to key #%d", self._key_index + 1)

    def _ocr_screenshot(self, screenshot: Screenshot) -> tuple[str, list[ScreenElement]]:
        """Run OCR on screenshot using both Chandra and pytesseract."""
        image = screenshot.image

        # 1. pytesseract for elements with coordinates (fast, free)
        t0 = time.time()
        elements = pytesseract_elements(image)
        tess_time = time.time() - t0

        # 2. Chandra for structured content (better text quality)
        chandra_text = ""
        if self.chandra:
            try:
                buf = io.BytesIO()
                image.save(buf, format="PNG")
                result = self.chandra.ocr(buf.getvalue())
                chandra_text = result.text
                self.total_ocr_cost_cents += result.cost_cents
                self.total_ocr_time += result.runtime_seconds
                logger.debug(
                    "Chandra OCR: %.1fs, %d cents, %d chars",
                    result.runtime_seconds, result.cost_cents, len(chandra_text),
                )
            except Exception as e:
                logger.warning("Chandra OCR failed, using pytesseract only: %s", e)
                chandra_text = "\n".join(e.text for e in elements)
        else:
            # Fallback: concatenate pytesseract text
            chandra_text = "\n".join(e.text for e in elements)

        logger.debug(
            "OCR: pytesseract %.2fs (%d elements), chandra text %d chars",
            tess_time, len(elements), len(chandra_text),
        )

        return chandra_text, elements

    def _call_llm(self, user_text: str, temperature: float = 0.0) -> str:
        """Call LLM (Cerebras or Azure OpenAI) with text-only input.

        Retries with key rotation on 429 rate limit errors.
        """
        messages = (
            [{"role": "system", "content": CEREBRAS_SYSTEM_PROMPT}]
            + list(self._messages)
            + [{"role": "user", "content": user_text}]
        )

        # Rate limit: ensure minimum interval between calls
        elapsed = time.time() - self._last_llm_call
        if elapsed < self._min_call_interval:
            time.sleep(self._min_call_interval - elapsed)

        last_error = None
        for retry in range(8):
            client = self._get_llm_client()
            try:
                t0 = time.time()
                # Azure GPT-5: max_completion_tokens, no temperature
                # GPT-5 uses reasoning tokens internally, so need higher limit
                if self.backend == "azure":
                    response = client.chat.completions.create(
                        model=self.azure_deployment or self.model,
                        max_completion_tokens=4096,
                        messages=messages,
                    )
                else:
                    response = client.chat.completions.create(
                        model=self.model,
                        max_tokens=1024,
                        temperature=temperature,
                        messages=messages,
                    )
                self.total_llm_time += time.time() - t0
                self._last_llm_call = time.time()

                text = response.choices[0].message.content or ""

                # Track tokens
                if response.usage:
                    self.total_input_tokens += response.usage.prompt_tokens or 0
                    self.total_output_tokens += response.usage.completion_tokens or 0

                # Empty response (e.g. GPT-5 used all tokens for reasoning)
                if not text.strip():
                    logger.warning("Empty LLM response (retry %d), retrying...", retry + 1)
                    print(f"    Empty response, retrying...")
                    time.sleep(1)
                    continue

                # Save to conversation history
                self._messages.append({"role": "user", "content": user_text})
                self._messages.append({"role": "assistant", "content": text})
                self._trim_messages()

                return text

            except Exception as e:
                last_error = e
                err_str = str(e)
                if "429" in err_str or "rate" in err_str.lower() or "too_many" in err_str.lower():
                    key_num = self._key_index + 1
                    delay = min(5 + retry * 5 + retry * retry, 60)
                    logger.warning(
                        "Rate limited (key #%d), retry %d/8, waiting %ds...",
                        key_num, retry + 1, delay,
                    )
                    print(f"    Rate limited (key #{key_num}), waiting {delay}s...")
                    self._rotate_key()
                    time.sleep(delay)
                    continue
                raise

        raise last_error

    def _trim_messages(self) -> None:
        """Keep conversation manageable (text-only, so less concern about size)."""
        max_total = self.MAX_TEXT_HISTORY * 2
        if len(self._messages) > max_total:
            self._messages = self._messages[-max_total:]

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

            obs = h.get("observation", "")
            if obs:
                parts.append(f"[saw: {obs[:60]}]")

            lines.append(" ".join(parts))

        return "\n".join(lines)

    def _detect_stuck(self) -> str:
        """Detect if the agent is stuck repeating the same action."""
        if len(self.history) < 2:
            return ""

        recent = self.history[-3:]
        coords = []
        for h in recent:
            x, y = h.get("x"), h.get("y")
            if x is not None and y is not None:
                coords.append((x, y))

        if len(coords) >= 2 and len(set(coords)) == 1:
            return (
                "\n⚠️ CRITICAL: You used the same coordinates multiple times with NO change. "
                "MUST choose a COMPLETELY DIFFERENT approach:\n"
                "- Use a different element number\n"
                "- Use keyboard: Tab, Enter, Ctrl+L for address bar\n"
                "- Scroll to reveal hidden elements\n"
                "- Return 'fail' if stuck\n"
            )

        action_types = [h.get("action_type") for h in recent]
        if len(action_types) >= 3 and len(set(action_types)) == 1:
            if action_types[0] in ("click",):
                return "\n⚠️ WARNING: Repeated same action 3 times. Try keyboard shortcuts or scroll.\n"

        return ""

    def _parse_action(self, text: str) -> Action:
        """Parse action from LLM response, resolving element references."""
        cleaned = text.strip()

        # Extract JSON from code fences
        if "```json" in cleaned:
            start = cleaned.index("```json") + 7
            end = cleaned.index("```", start)
            cleaned = cleaned[start:end]
        elif "```" in cleaned:
            start = cleaned.index("```") + 3
            end = cleaned.index("```", start)
            cleaned = cleaned[start:end]

        # Sometimes the model outputs extra text before/after JSON
        # Try to find the JSON object
        match = re.search(r'\{[^{}]*(?:\{[^{}]*\}[^{}]*)*\}', cleaned)
        if match:
            cleaned = match.group()

        data = json.loads(cleaned)

        # Resolve element reference to coordinates
        elem_idx = data.get("element")
        if elem_idx is not None and data.get("x") is None:
            for e in self._elements:
                if e.index == elem_idx:
                    data["x"] = e.x
                    data["y"] = e.y
                    data["target"] = e.text
                    break

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
            reasoning=data.get("thought", data.get("reasoning", "")),
            observation=data.get("observation", ""),
        )

    def get_next_action(
        self, goal: str, screenshot: Screenshot, max_steps: int = 50
    ) -> Action:
        """Determine the next action given current screen state.

        Same interface as TaskPlanner.get_next_action().
        """
        self._step_num += 1
        self._max_steps = max_steps

        # OCR the screenshot
        ocr_text, self._elements = self._ocr_screenshot(screenshot)
        elements_str = format_elements(self._elements)

        history_str = self._format_history()
        stuck_warning = self._detect_stuck()

        user_prompt = CEREBRAS_USER_PROMPT.format(
            step_num=self._step_num,
            max_steps=max_steps,
            goal=goal,
            ocr_text=ocr_text[:3000],  # Limit OCR text length
            elements=elements_str,
            history=history_str,
            stuck_warning=stuck_warning,
            screen_width=screenshot.width,
            screen_height=screenshot.height,
        )

        # Try up to 3 times with increasing temperature
        last_error = None
        for attempt in range(3):
            temp = 0.0 if attempt == 0 else min(0.5 + attempt * 0.3, 1.0)
            try:
                response = self._call_llm(user_prompt, temperature=temp)
                logger.debug("Cerebras response (attempt %d): %s", attempt + 1, response)
                action = self._parse_action(response)
                break
            except (json.JSONDecodeError, ValueError, KeyError) as e:
                last_error = e
                logger.warning(
                    "Parse attempt %d failed: %s. Retrying.",
                    attempt + 1, e,
                )
                # Remove failed messages
                if self._messages and self._messages[-1]["role"] == "assistant":
                    self._messages.pop()
                if self._messages and self._messages[-1]["role"] == "user":
                    self._messages.pop()
                time.sleep(0.3)
        else:
            logger.error("All parse attempts failed: %s", last_error)
            return Action(
                action_type=ActionType.FAIL,
                reasoning=f"Failed to parse LLM response after 3 attempts: {last_error}",
            )

        # Record in history
        self.history.append(action.to_dict())

        return action

    @property
    def engine_name(self) -> str:
        """Human-readable engine name."""
        if self.backend == "azure":
            return f"azure-openai-{self.azure_deployment}"
        return f"cerebras-{self.model}"

    def _llm_pricing(self) -> tuple[float, float]:
        """Return (input_price_per_M, output_price_per_M) for current backend."""
        if self.backend == "azure":
            # GPT-5 pricing (estimate): $2/M in, $10/M out
            return 2.0, 10.0
        # Cerebras GPT-OSS-120B
        return 0.25, 0.69

    @property
    def estimated_cost_usd(self) -> float:
        """Estimate total cost (LLM + OCR) in USD."""
        inp_price, out_price = self._llm_pricing()
        llm_input_cost = self.total_input_tokens * inp_price / 1_000_000
        llm_output_cost = self.total_output_tokens * out_price / 1_000_000
        ocr_cost = self.total_ocr_cost_cents / 100.0
        return llm_input_cost + llm_output_cost + ocr_cost

    @property
    def cost_breakdown(self) -> dict:
        """Detailed cost breakdown."""
        inp_price, out_price = self._llm_pricing()
        return {
            "llm_input_cost": self.total_input_tokens * inp_price / 1_000_000,
            "llm_output_cost": self.total_output_tokens * out_price / 1_000_000,
            "ocr_cost": self.total_ocr_cost_cents / 100.0,
            "total": self.estimated_cost_usd,
            "llm_time": round(self.total_llm_time, 2),
            "ocr_time": round(self.total_ocr_time, 2),
        }

    def reset(self) -> None:
        """Reset planner state for a new task."""
        self.history = []
        self._messages = []
        self._step_num = 0
        self._elements = []
        self.total_input_tokens = 0
        self.total_output_tokens = 0
        self.total_ocr_cost_cents = 0.0
        self.total_ocr_time = 0.0
        self.total_llm_time = 0.0
