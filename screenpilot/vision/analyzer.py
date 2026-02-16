"""Screen analysis using LLM vision APIs."""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field

from screenpilot.config import LLMConfig
from screenpilot.vision.capture import Screenshot

logger = logging.getLogger(__name__)


@dataclass
class UIElement:
    """Represents a detected UI element on screen."""

    label: str
    element_type: str  # button, text_field, link, icon, menu, etc.
    x: int
    y: int
    width: int | None = None
    height: int | None = None
    text: str | None = None
    confidence: float = 1.0

    @property
    def center(self) -> tuple[int, int]:
        """Get center coordinates."""
        cx = self.x + (self.width // 2 if self.width else 0)
        cy = self.y + (self.height // 2 if self.height else 0)
        return cx, cy


@dataclass
class ScreenState:
    """Represents the analyzed state of a screen."""

    elements: list[UIElement] = field(default_factory=list)
    description: str = ""
    active_window: str | None = None
    raw_response: str = ""

    def find_element(self, label: str) -> UIElement | None:
        """Find a UI element by label (fuzzy match)."""
        label_lower = label.lower()
        for el in self.elements:
            if label_lower in el.label.lower() or (el.text and label_lower in el.text.lower()):
                return el
        return None

    def find_elements_by_type(self, element_type: str) -> list[UIElement]:
        """Find all UI elements of a given type."""
        return [el for el in self.elements if el.element_type == element_type]


ANALYZE_SCREEN_PROMPT = """Analyze this screenshot and identify all interactive UI elements.

For each element, provide:
- label: a descriptive label
- element_type: one of [button, text_field, link, icon, menu, menu_item, checkbox, radio, dropdown, tab, scroll_bar, image, text, dialog, toolbar, status_bar, other]
- x: left pixel coordinate
- y: top pixel coordinate
- width: element width in pixels (estimate)
- height: element height in pixels (estimate)
- text: any visible text on the element

Also provide:
- description: a brief description of what's currently shown on screen
- active_window: the title of the active/focused window if visible

Return your response as JSON in this exact format:
{
  "description": "...",
  "active_window": "...",
  "elements": [
    {"label": "...", "element_type": "...", "x": 0, "y": 0, "width": 0, "height": 0, "text": "..."}
  ]
}

Be precise with coordinates. Focus on interactive elements that a user might click, type into, or interact with."""


FIND_ELEMENT_PROMPT = """Look at this screenshot and find the UI element that best matches this description: "{target}"

Return the exact pixel coordinates where I should click to interact with this element.

Return your response as JSON:
{{
  "found": true/false,
  "label": "description of the element",
  "element_type": "button/text_field/link/etc",
  "x": <center_x_coordinate>,
  "y": <center_y_coordinate>,
  "width": <estimated_width>,
  "height": <estimated_height>,
  "confidence": <0.0-1.0>,
  "reasoning": "why this element matches"
}}

Be very precise with the coordinates. The click should land exactly on the element."""


class ScreenAnalyzer:
    """Analyzes screenshots using LLM vision APIs."""

    def __init__(self, config: LLMConfig | None = None):
        self.config = config or LLMConfig()
        self._client = None

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
            # Use litellm for other providers
            import litellm

            self._client = litellm
        return self._client

    def _call_vision(self, screenshot: Screenshot, prompt: str) -> str:
        """Call the vision LLM with a screenshot and prompt."""
        client = self._get_client()
        img_b64 = screenshot.to_base64(format="png")

        if self.config.provider == "anthropic":
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
            )
            return response.content[0].text

        elif self.config.provider == "openai":
            response = client.chat.completions.create(
                model=self.config.model,
                max_tokens=self.config.max_tokens,
                temperature=self.config.temperature,
                messages=[
                    {
                        "role": "user",
                        "content": [
                            {
                                "type": "image_url",
                                "image_url": {
                                    "url": f"data:image/png;base64,{img_b64}",
                                },
                            },
                            {"type": "text", "text": prompt},
                        ],
                    }
                ],
            )
            return response.choices[0].message.content

        else:
            # litellm
            import litellm

            response = litellm.completion(
                model=self.config.model,
                max_tokens=self.config.max_tokens,
                temperature=self.config.temperature,
                messages=[
                    {
                        "role": "user",
                        "content": [
                            {
                                "type": "image_url",
                                "image_url": {
                                    "url": f"data:image/png;base64,{img_b64}",
                                },
                            },
                            {"type": "text", "text": prompt},
                        ],
                    }
                ],
            )
            return response.choices[0].message.content

    def _parse_json(self, text: str) -> dict:
        """Extract and parse JSON from LLM response."""
        # Try to find JSON block in the response
        if "```json" in text:
            start = text.index("```json") + 7
            end = text.index("```", start)
            text = text[start:end]
        elif "```" in text:
            start = text.index("```") + 3
            end = text.index("```", start)
            text = text[start:end]

        text = text.strip()
        return json.loads(text)

    def analyze(self, screenshot: Screenshot) -> ScreenState:
        """Analyze a screenshot and return the screen state."""
        response = self._call_vision(screenshot, ANALYZE_SCREEN_PROMPT)
        logger.debug("Screen analysis response: %s", response)

        try:
            data = self._parse_json(response)
        except (json.JSONDecodeError, ValueError):
            logger.warning("Failed to parse screen analysis JSON, returning raw response")
            return ScreenState(description=response, raw_response=response)

        elements = []
        for el_data in data.get("elements", []):
            elements.append(
                UIElement(
                    label=el_data.get("label", ""),
                    element_type=el_data.get("element_type", "other"),
                    x=el_data.get("x", 0),
                    y=el_data.get("y", 0),
                    width=el_data.get("width"),
                    height=el_data.get("height"),
                    text=el_data.get("text"),
                )
            )

        return ScreenState(
            elements=elements,
            description=data.get("description", ""),
            active_window=data.get("active_window"),
            raw_response=response,
        )

    def find_element(self, screenshot: Screenshot, target: str) -> UIElement | None:
        """Find a specific UI element on screen by description."""
        prompt = FIND_ELEMENT_PROMPT.format(target=target)
        response = self._call_vision(screenshot, prompt)
        logger.debug("Find element response: %s", response)

        try:
            data = self._parse_json(response)
        except (json.JSONDecodeError, ValueError):
            logger.warning("Failed to parse find element JSON")
            return None

        if not data.get("found", False):
            return None

        return UIElement(
            label=data.get("label", target),
            element_type=data.get("element_type", "other"),
            x=data.get("x", 0),
            y=data.get("y", 0),
            width=data.get("width"),
            height=data.get("height"),
            confidence=data.get("confidence", 0.5),
        )

    def describe_screen(self, screenshot: Screenshot) -> str:
        """Get a natural language description of the current screen."""
        prompt = (
            "Describe what is shown on this screen in detail. "
            "Include the active application, visible UI elements, "
            "and any important text or content visible."
        )
        return self._call_vision(screenshot, prompt)
