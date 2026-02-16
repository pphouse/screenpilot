"""Cross-platform screen capture module."""

from __future__ import annotations

import base64
import io
import time
from dataclasses import dataclass

import mss
from PIL import Image

from screenpilot.config import CaptureConfig


@dataclass
class Screenshot:
    """Represents a captured screenshot with metadata."""

    image: Image.Image
    timestamp: float
    monitor_index: int
    width: int
    height: int

    def to_base64(self, format: str = "png", quality: int = 85) -> str:
        """Convert screenshot to base64 string for LLM APIs."""
        buffer = io.BytesIO()
        save_kwargs = {"format": format.upper()}
        if format.lower() == "jpeg":
            save_kwargs["quality"] = quality
        self.image.save(buffer, **save_kwargs)
        return base64.b64encode(buffer.getvalue()).decode("utf-8")

    def to_bytes(self, format: str = "png") -> bytes:
        """Convert screenshot to bytes."""
        buffer = io.BytesIO()
        self.image.save(buffer, format=format.upper())
        return buffer.getvalue()

    def save(self, path: str, format: str | None = None) -> None:
        """Save screenshot to file."""
        self.image.save(path, format=format)

    def resize(self, max_width: int, max_height: int) -> Screenshot:
        """Resize screenshot while maintaining aspect ratio."""
        w, h = self.image.size
        scale = min(max_width / w, max_height / h, 1.0)
        if scale < 1.0:
            new_w, new_h = int(w * scale), int(h * scale)
            resized = self.image.resize((new_w, new_h), Image.LANCZOS)
            return Screenshot(
                image=resized,
                timestamp=self.timestamp,
                monitor_index=self.monitor_index,
                width=new_w,
                height=new_h,
            )
        return self


class ScreenCapture:
    """Cross-platform screen capture using mss."""

    def __init__(self, config: CaptureConfig | None = None):
        self.config = config or CaptureConfig()
        self._sct = mss.mss()

    def capture(
        self, monitor: int | None = None, region: tuple[int, int, int, int] | None = None
    ) -> Screenshot:
        """Capture a screenshot.

        Args:
            monitor: Monitor index (0=all, 1=primary, 2=secondary, etc.)
            region: Optional (left, top, width, height) region to capture
        """
        if region:
            monitor_area = {
                "left": region[0],
                "top": region[1],
                "width": region[2],
                "height": region[3],
            }
        else:
            mon_idx = monitor if monitor is not None else self.config.monitor
            monitors = self._sct.monitors
            if mon_idx >= len(monitors):
                mon_idx = 0
            monitor_area = monitors[mon_idx]

        raw = self._sct.grab(monitor_area)
        img = Image.frombytes("RGB", (raw.width, raw.height), raw.rgb)

        screenshot = Screenshot(
            image=img,
            timestamp=time.time(),
            monitor_index=monitor if monitor is not None else self.config.monitor,
            width=raw.width,
            height=raw.height,
        )

        # Auto-resize if needed
        if self.config.max_width or self.config.max_height:
            screenshot = screenshot.resize(self.config.max_width, self.config.max_height)

        return screenshot

    def capture_window(self, title: str) -> Screenshot | None:
        """Capture a specific window by title (platform-dependent)."""
        # For now, fall back to full screen capture
        # Platform-specific window capture can be added later
        return self.capture()

    def get_monitors(self) -> list[dict]:
        """Get list of available monitors."""
        return [
            {
                "index": i,
                "left": m["left"],
                "top": m["top"],
                "width": m["width"],
                "height": m["height"],
            }
            for i, m in enumerate(self._sct.monitors)
        ]
