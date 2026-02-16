"""Workflow recording: captures user actions and screenshots for later replay."""

from __future__ import annotations

import json
import logging
import threading
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path

from pynput import keyboard, mouse

from screenpilot.config import RecorderConfig
from screenpilot.vision.capture import ScreenCapture

logger = logging.getLogger(__name__)


@dataclass
class RecordedEvent:
    """A single recorded user interaction event."""

    timestamp: float
    event_type: str  # click, double_click, right_click, type, key, scroll
    x: int | None = None
    y: int | None = None
    button: str | None = None
    text: str | None = None
    key: str | None = None
    scroll_dx: int | None = None
    scroll_dy: int | None = None
    screenshot_path: str | None = None


@dataclass
class Workflow:
    """A recorded workflow consisting of events and screenshots."""

    name: str
    events: list[RecordedEvent] = field(default_factory=list)
    start_time: float = 0.0
    end_time: float = 0.0
    description: str = ""

    def save(self, path: str | Path) -> None:
        """Save workflow to JSON file."""
        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        data = {
            "name": self.name,
            "description": self.description,
            "start_time": self.start_time,
            "end_time": self.end_time,
            "events": [asdict(e) for e in self.events],
        }
        with open(path, "w") as f:
            json.dump(data, f, indent=2)
        logger.info("Workflow saved to %s (%d events)", path, len(self.events))

    @classmethod
    def load(cls, path: str | Path) -> Workflow:
        """Load workflow from JSON file."""
        with open(path) as f:
            data = json.load(f)
        events = [RecordedEvent(**e) for e in data.get("events", [])]
        return cls(
            name=data["name"],
            events=events,
            start_time=data.get("start_time", 0),
            end_time=data.get("end_time", 0),
            description=data.get("description", ""),
        )

    @property
    def duration(self) -> float:
        """Total duration in seconds."""
        if self.events:
            return self.events[-1].timestamp - self.events[0].timestamp
        return 0.0


class WorkflowRecorder:
    """Records user interactions (mouse clicks, keyboard) with screenshots."""

    def __init__(self, config: RecorderConfig | None = None):
        self.config = config or RecorderConfig()
        self._capture = ScreenCapture()
        self._recording = False
        self._workflow: Workflow | None = None
        self._save_dir = Path(self.config.save_dir).expanduser()
        self._save_dir.mkdir(parents=True, exist_ok=True)
        self._mouse_listener: mouse.Listener | None = None
        self._keyboard_listener: keyboard.Listener | None = None
        self._current_text_buffer: list[str] = []
        self._screenshot_count = 0
        self._lock = threading.Lock()

    def start(self, name: str, description: str = "") -> None:
        """Start recording a new workflow."""
        if self._recording:
            raise RuntimeError("Already recording. Stop the current recording first.")

        self._workflow = Workflow(
            name=name,
            start_time=time.time(),
            description=description,
        )
        self._recording = True
        self._screenshot_count = 0
        self._current_text_buffer = []

        workflow_dir = self._save_dir / name
        workflow_dir.mkdir(parents=True, exist_ok=True)

        # Start listeners
        self._mouse_listener = mouse.Listener(
            on_click=self._on_click,
            on_scroll=self._on_scroll,
        )
        self._keyboard_listener = keyboard.Listener(
            on_press=self._on_key_press,
            on_release=self._on_key_release,
        )
        self._mouse_listener.start()
        self._keyboard_listener.start()

        logger.info("Recording started: %s", name)

    def stop(self) -> Workflow | None:
        """Stop recording and return the workflow."""
        if not self._recording:
            return None

        self._recording = False

        # Flush text buffer
        self._flush_text_buffer()

        # Stop listeners
        if self._mouse_listener:
            self._mouse_listener.stop()
        if self._keyboard_listener:
            self._keyboard_listener.stop()

        if self._workflow:
            self._workflow.end_time = time.time()
            # Auto-save
            workflow_path = self._save_dir / self._workflow.name / "workflow.json"
            self._workflow.save(workflow_path)

        logger.info(
            "Recording stopped: %d events captured",
            len(self._workflow.events) if self._workflow else 0,
        )
        return self._workflow

    def _take_screenshot(self) -> str | None:
        """Take a screenshot and save it, return the path."""
        if self._screenshot_count >= self.config.max_screenshots:
            return None
        try:
            screenshot = self._capture.capture()
            self._screenshot_count += 1
            path = (
                self._save_dir
                / self._workflow.name
                / f"screenshot_{self._screenshot_count:04d}.png"
            )
            screenshot.save(str(path))
            return str(path)
        except Exception as e:
            logger.warning("Failed to capture screenshot: %s", e)
            return None

    def _on_click(self, x: int, y: int, button: mouse.Button, pressed: bool) -> None:
        """Handle mouse click events."""
        if not self._recording or not pressed:
            return

        with self._lock:
            self._flush_text_buffer()

            screenshot_path = None
            if self.config.capture_on_click:
                screenshot_path = self._take_screenshot()

            event_type = "click"
            if button == mouse.Button.right:
                event_type = "right_click"

            event = RecordedEvent(
                timestamp=time.time(),
                event_type=event_type,
                x=int(x),
                y=int(y),
                button=button.name,
                screenshot_path=screenshot_path,
            )
            self._workflow.events.append(event)

    def _on_scroll(self, x: int, y: int, dx: int, dy: int) -> None:
        """Handle scroll events."""
        if not self._recording:
            return

        with self._lock:
            event = RecordedEvent(
                timestamp=time.time(),
                event_type="scroll",
                x=int(x),
                y=int(y),
                scroll_dx=dx,
                scroll_dy=dy,
            )
            self._workflow.events.append(event)

    def _on_key_press(self, key: keyboard.Key | keyboard.KeyCode) -> None:
        """Handle key press events."""
        if not self._recording:
            return

        with self._lock:
            try:
                # Regular character key
                if hasattr(key, "char") and key.char:
                    self._current_text_buffer.append(key.char)
                else:
                    # Special key - flush text buffer first
                    self._flush_text_buffer()
                    key_name = key.name if hasattr(key, "name") else str(key)
                    event = RecordedEvent(
                        timestamp=time.time(),
                        event_type="key",
                        key=key_name,
                    )
                    self._workflow.events.append(event)
            except AttributeError:
                pass

    def _on_key_release(self, key: keyboard.Key | keyboard.KeyCode) -> None:
        """Handle key release (for detecting special key combos)."""
        pass

    def _flush_text_buffer(self) -> None:
        """Flush accumulated text characters as a single type event."""
        if self._current_text_buffer:
            text = "".join(self._current_text_buffer)
            event = RecordedEvent(
                timestamp=time.time(),
                event_type="type",
                text=text,
            )
            self._workflow.events.append(event)
            self._current_text_buffer = []

    @property
    def is_recording(self) -> bool:
        return self._recording
