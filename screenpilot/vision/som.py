"""Set-of-Mark (SoM) visual prompting for improved GUI grounding.

Based on the Set-of-Mark paper (arXiv:2310.11441) and OmniParser approach.
Overlays numbered bounding boxes and labels on screenshots to help LLMs
precisely identify and reference UI elements by number rather than raw coordinates.

This dramatically improves grounding accuracy, as shown by OmniParser+GPT-4o
achieving 39.6% on ScreenSpot-Pro (vs <2% without SoM).
"""

from __future__ import annotations

import colorsys
import logging
from dataclasses import dataclass, field

from PIL import Image, ImageDraw, ImageFont

logger = logging.getLogger(__name__)


@dataclass
class MarkedRegion:
    """A region marked on the screenshot with an ID."""

    mark_id: int
    x: int
    y: int
    width: int
    height: int
    label: str = ""

    @property
    def center(self) -> tuple[int, int]:
        return self.x + self.width // 2, self.y + self.height // 2

    @property
    def bbox(self) -> tuple[int, int, int, int]:
        """Return (left, top, right, bottom)."""
        return self.x, self.y, self.x + self.width, self.y + self.height


@dataclass
class SoMResult:
    """Result of Set-of-Mark annotation."""

    annotated_image: Image.Image
    regions: list[MarkedRegion] = field(default_factory=list)
    original_size: tuple[int, int] = (0, 0)

    def get_region(self, mark_id: int) -> MarkedRegion | None:
        """Get a marked region by its ID."""
        for r in self.regions:
            if r.mark_id == mark_id:
                return r
        return None


def _generate_colors(n: int) -> list[tuple[int, int, int]]:
    """Generate n visually distinct colors using HSV spacing."""
    colors = []
    for i in range(n):
        hue = i / max(n, 1)
        r, g, b = colorsys.hsv_to_rgb(hue, 0.9, 0.9)
        colors.append((int(r * 255), int(g * 255), int(b * 255)))
    return colors


def _get_font(size: int = 14) -> ImageFont.FreeTypeFont | ImageFont.ImageFont:
    """Get a font for rendering labels."""
    try:
        return ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf", size)
    except (OSError, IOError):
        try:
            return ImageFont.truetype(
                "/usr/share/fonts/truetype/liberation/LiberationSans-Bold.ttf", size
            )
        except (OSError, IOError):
            return ImageFont.load_default()


def create_grid_marks(
    image: Image.Image,
    grid_size: tuple[int, int] = (8, 6),
    min_region_size: int = 30,
) -> SoMResult:
    """Create a uniform grid of marks over the image.

    This is a simple but effective approach when we don't have
    a dedicated UI element detector. The grid ensures all areas
    of the screen are referenced by a mark ID.

    Args:
        image: The screenshot to annotate
        grid_size: (columns, rows) for the grid
        min_region_size: Minimum region size in pixels
    """
    w, h = image.size
    cols, rows = grid_size
    cell_w = w // cols
    cell_h = h // rows

    if cell_w < min_region_size or cell_h < min_region_size:
        cols = max(1, w // min_region_size)
        rows = max(1, h // min_region_size)
        cell_w = w // cols
        cell_h = h // rows

    annotated = image.copy()
    draw = ImageDraw.Draw(annotated)
    font = _get_font(12)
    colors = _generate_colors(cols * rows)
    regions = []

    mark_id = 1
    for row in range(rows):
        for col in range(cols):
            x = col * cell_w
            y = row * cell_h
            region = MarkedRegion(
                mark_id=mark_id,
                x=x,
                y=y,
                width=cell_w,
                height=cell_h,
            )
            regions.append(region)

            color = colors[mark_id - 1]
            # Draw border
            draw.rectangle(
                [x, y, x + cell_w - 1, y + cell_h - 1],
                outline=color,
                width=2,
            )
            # Draw mark ID label with background
            label = str(mark_id)
            bbox = font.getbbox(label)
            text_w = bbox[2] - bbox[0]
            text_h = bbox[3] - bbox[1]
            label_x = x + 3
            label_y = y + 3
            draw.rectangle(
                [label_x - 1, label_y - 1, label_x + text_w + 3, label_y + text_h + 3],
                fill=color,
            )
            draw.text((label_x + 1, label_y), label, fill="white", font=font)

            mark_id += 1

    return SoMResult(
        annotated_image=annotated,
        regions=regions,
        original_size=image.size,
    )


def annotate_with_marks(
    image: Image.Image,
    regions: list[tuple[int, int, int, int]],
    labels: list[str] | None = None,
) -> SoMResult:
    """Annotate an image with numbered marks at specified regions.

    Args:
        image: The screenshot to annotate
        regions: List of (x, y, width, height) bounding boxes
        labels: Optional text labels for each region
    """
    annotated = image.copy()
    draw = ImageDraw.Draw(annotated)
    font = _get_font(14)
    colors = _generate_colors(len(regions))
    marked_regions = []

    for i, (x, y, w, h) in enumerate(regions):
        mark_id = i + 1
        color = colors[i]
        label = labels[i] if labels and i < len(labels) else ""

        marked_regions.append(
            MarkedRegion(
                mark_id=mark_id,
                x=x,
                y=y,
                width=w,
                height=h,
                label=label,
            )
        )

        # Draw bounding box
        draw.rectangle([x, y, x + w, y + h], outline=color, width=2)

        # Draw mark ID
        id_text = str(mark_id)
        text_bbox = font.getbbox(id_text)
        text_w = text_bbox[2] - text_bbox[0]
        text_h = text_bbox[3] - text_bbox[1]

        # Position label at top-left of region
        label_x = x
        label_y = max(0, y - text_h - 4)

        draw.rectangle(
            [label_x, label_y, label_x + text_w + 6, label_y + text_h + 4],
            fill=color,
        )
        draw.text((label_x + 3, label_y + 2), id_text, fill="white", font=font)

        # Draw optional text label
        if label:
            draw.text((x + text_w + 10, label_y + 2), label, fill=color, font=font)

    return SoMResult(
        annotated_image=annotated,
        regions=marked_regions,
        original_size=image.size,
    )


SOM_ANALYSIS_PROMPT = """Analyze this screenshot that has been annotated with numbered marks (colored bounding boxes with numbers).

Each numbered region represents a potential interactive area on the screen.

For each numbered mark that contains an interactive UI element, provide:
- mark_id: the number shown on the mark
- element_type: button, text_field, link, icon, menu, checkbox, dropdown, tab, etc.
- text: any visible text within this region
- description: what this element does or represents

Also identify:
- active_window: the title of the active window
- screen_description: what is currently shown on screen

Return JSON:
{
  "screen_description": "...",
  "active_window": "...",
  "elements": [
    {"mark_id": 1, "element_type": "button", "text": "Save", "description": "Save button"},
    ...
  ]
}

Only include marks that contain meaningful interactive elements. Skip empty or decorative regions."""


SOM_FIND_PROMPT = """Look at this annotated screenshot with numbered marks.

Find the mark that best matches this description: "{target}"

Return JSON:
{{
  "found": true/false,
  "mark_id": <number of the matching mark>,
  "confidence": <0.0-1.0>,
  "reasoning": "why this mark matches the description"
}}"""


SOM_ACTION_PROMPT = """Look at this annotated screenshot with numbered marks.

Current task: {goal}
Previous actions: {history}

Determine the next action to take. Reference UI elements by their mark number.

Return JSON:
{{
  "reasoning": "step-by-step reasoning about what you see and what to do",
  "action_type": "click|type|key|scroll|done|fail",
  "mark_id": <number of the target mark, if clicking>,
  "text": "text to type, if typing",
  "keys": "keyboard shortcut, if pressing keys",
  "direction": "up|down, if scrolling"
}}"""
