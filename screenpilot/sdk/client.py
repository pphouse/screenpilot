"""Python SDK client for the ScreenPilot API.

Provides a clean programmatic interface for integrating ScreenPilot
into existing Python applications and CI/CD pipelines.

Usage:
    from screenpilot.sdk import ScreenPilotClient

    client = ScreenPilotClient("http://localhost:8000")
    task = client.run_task("Open Chrome and search for 'hello'")
    task.wait()
    print(task.status, task.success)
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field
from typing import Any

logger = logging.getLogger(__name__)

try:
    import httpx
except ImportError:
    httpx = None  # type: ignore[assignment]

try:
    import websockets
except ImportError:
    websockets = None  # type: ignore[assignment]


@dataclass
class Screenshot:
    """Screenshot data from the API."""

    width: int
    height: int
    timestamp: float
    image_base64: str


@dataclass
class Element:
    """A detected UI element."""

    label: str
    element_type: str
    x: int
    y: int
    width: int = 0
    height: int = 0
    confidence: float = 0.0
    text: str | None = None


@dataclass
class ActionResult:
    """Result of executing an action."""

    success: bool
    error: str | None = None
    duration: float = 0.0


@dataclass
class TaskHandle:
    """Handle to a running or completed task."""

    task_id: str
    goal: str
    status: str
    current_step: int = 0
    total_time: float = 0.0
    error: str | None = None
    _client: Any = field(default=None, repr=False)

    @property
    def is_running(self) -> bool:
        return self.status == "running"

    @property
    def success(self) -> bool:
        return self.status == "completed"

    def refresh(self) -> TaskHandle:
        """Refresh task status from the server."""
        if self._client:
            updated = self._client.get_task(self.task_id)
            self.status = updated.status
            self.current_step = updated.current_step
            self.total_time = updated.total_time
            self.error = updated.error
        return self

    def wait(self, timeout: float = 300, poll_interval: float = 1.0) -> TaskHandle:
        """Wait for the task to complete."""
        start = time.time()
        while self.is_running and (time.time() - start) < timeout:
            time.sleep(poll_interval)
            self.refresh()
        return self

    def stop(self) -> None:
        """Stop the running task."""
        if self._client:
            self._client.stop_task(self.task_id)
        self.status = "stopped"


@dataclass
class Template:
    """A workflow template."""

    id: str
    name: str
    description: str
    category: str
    goal_template: str
    params: list[dict] = field(default_factory=list)
    tags: list[str] = field(default_factory=list)
    estimated_steps: int = 10


class ScreenPilotClient:
    """SDK client for ScreenPilot API.

    Provides methods for all API operations with a clean Python interface.
    Requires `httpx` package: pip install httpx
    """

    def __init__(self, base_url: str = "http://localhost:8000", timeout: float = 30.0):
        if httpx is None:
            raise ImportError("httpx is required for ScreenPilotClient: pip install httpx")
        self.base_url = base_url.rstrip("/")
        self._client = httpx.Client(base_url=self.base_url, timeout=timeout)

    def close(self) -> None:
        """Close the HTTP client."""
        self._client.close()

    def __enter__(self) -> ScreenPilotClient:
        return self

    def __exit__(self, *args: Any) -> None:
        self.close()

    # Health / Info

    def health(self) -> dict:
        """Check server health."""
        resp = self._client.get("/health")
        resp.raise_for_status()
        return resp.json()

    def info(self) -> dict:
        """Get API info."""
        resp = self._client.get("/api")
        resp.raise_for_status()
        return resp.json()

    # Vision

    def screenshot(self) -> Screenshot:
        """Take a screenshot."""
        resp = self._client.post("/screenshot")
        resp.raise_for_status()
        data = resp.json()
        return Screenshot(
            width=data["width"],
            height=data["height"],
            timestamp=data["timestamp"],
            image_base64=data["image"],
        )

    def analyze(self) -> dict:
        """Analyze the current screen state."""
        resp = self._client.post("/analyze")
        resp.raise_for_status()
        return resp.json()

    def find_element(self, target: str) -> Element | None:
        """Find a UI element by description."""
        resp = self._client.post("/find", json={"target": target})
        if resp.status_code == 404:
            return None
        resp.raise_for_status()
        data = resp.json()
        return Element(
            label=data["label"],
            element_type=data["element_type"],
            x=data["x"],
            y=data["y"],
            width=data.get("width", 0),
            height=data.get("height", 0),
            confidence=data.get("confidence", 0.0),
        )

    # Actions

    def execute_action(
        self,
        action_type: str,
        target: str | None = None,
        x: int | None = None,
        y: int | None = None,
        text: str | None = None,
        keys: str | None = None,
        direction: str | None = None,
        amount: int | None = None,
    ) -> ActionResult:
        """Execute a single action."""
        payload: dict[str, Any] = {"action_type": action_type}
        if target is not None:
            payload["target"] = target
        if x is not None:
            payload["x"] = x
        if y is not None:
            payload["y"] = y
        if text is not None:
            payload["text"] = text
        if keys is not None:
            payload["keys"] = keys
        if direction is not None:
            payload["direction"] = direction
        if amount is not None:
            payload["amount"] = amount

        resp = self._client.post("/action", json=payload)
        resp.raise_for_status()
        data = resp.json()
        return ActionResult(
            success=data["success"],
            error=data.get("error"),
            duration=data.get("duration", 0.0),
        )

    def click(self, x: int, y: int) -> ActionResult:
        """Click at coordinates."""
        return self.execute_action("click", x=x, y=y)

    def double_click(self, x: int, y: int) -> ActionResult:
        """Double-click at coordinates."""
        return self.execute_action("double_click", x=x, y=y)

    def right_click(self, x: int, y: int) -> ActionResult:
        """Right-click at coordinates."""
        return self.execute_action("right_click", x=x, y=y)

    def type_text(self, text: str) -> ActionResult:
        """Type text at current cursor position."""
        return self.execute_action("type", text=text)

    def press_key(self, keys: str) -> ActionResult:
        """Press a keyboard shortcut (e.g., 'ctrl+c')."""
        return self.execute_action("key", keys=keys)

    def scroll(self, direction: str = "down", amount: int = 3) -> ActionResult:
        """Scroll the screen."""
        return self.execute_action("scroll", direction=direction, amount=amount)

    def find_and_click(self, target: str) -> ActionResult:
        """Find a UI element and click it."""
        return self.execute_action("find_and_click", target=target)

    def find_and_type(self, target: str, text: str) -> ActionResult:
        """Find a UI element, click it, and type text."""
        return self.execute_action("find_and_type", target=target, text=text)

    # Tasks

    def run_task(self, goal: str, max_steps: int = 50) -> TaskHandle:
        """Start an automation task."""
        resp = self._client.post("/task", json={"goal": goal, "max_steps": max_steps})
        resp.raise_for_status()
        data = resp.json()
        return TaskHandle(
            task_id=data["task_id"],
            goal=data["goal"],
            status=data["status"],
            current_step=data.get("current_step", 0),
            total_time=data.get("total_time", 0.0),
            _client=self,
        )

    def get_task(self, task_id: str) -> TaskHandle:
        """Get task status."""
        resp = self._client.get(f"/task/{task_id}")
        resp.raise_for_status()
        data = resp.json()
        return TaskHandle(
            task_id=data["task_id"],
            goal=data["goal"],
            status=data["status"],
            current_step=data.get("current_step", 0),
            total_time=data.get("total_time", 0.0),
            error=data.get("error"),
            _client=self,
        )

    def stop_task(self, task_id: str) -> dict:
        """Stop a running task."""
        resp = self._client.post(f"/task/{task_id}/stop")
        resp.raise_for_status()
        return resp.json()

    def list_tasks(self) -> list[TaskHandle]:
        """List all tasks."""
        resp = self._client.get("/tasks")
        resp.raise_for_status()
        return [
            TaskHandle(
                task_id=t["task_id"],
                goal=t["goal"],
                status=t["status"],
                current_step=t.get("current_step", 0),
                total_time=t.get("total_time", 0.0),
                _client=self,
            )
            for t in resp.json()
        ]

    # Templates

    def list_templates(self) -> list[Template]:
        """List available workflow templates."""
        resp = self._client.get("/templates")
        resp.raise_for_status()
        return [
            Template(
                id=t["id"],
                name=t["name"],
                description=t["description"],
                category=t["category"],
                goal_template=t["goal_template"],
                params=t.get("params", []),
                tags=t.get("tags", []),
                estimated_steps=t.get("estimated_steps", 10),
            )
            for t in resp.json()
        ]

    def run_template(self, template_id: str, params: dict[str, Any]) -> TaskHandle:
        """Run a workflow template with given parameters."""
        resp = self._client.post(f"/templates/{template_id}/run", json=params)
        resp.raise_for_status()
        data = resp.json()
        return TaskHandle(
            task_id=data["task_id"],
            goal=data["goal"],
            status=data["status"],
            current_step=data.get("current_step", 0),
            total_time=data.get("total_time", 0.0),
            _client=self,
        )

    # Scheduling

    def list_schedules(self) -> list[dict]:
        """List all scheduled tasks."""
        resp = self._client.get("/schedules")
        resp.raise_for_status()
        return resp.json()

    def add_schedule(self, schedule: dict) -> dict:
        """Add a new scheduled task."""
        resp = self._client.post("/schedules", json=schedule)
        resp.raise_for_status()
        return resp.json()

    def remove_schedule(self, schedule_id: str) -> dict:
        """Remove a scheduled task."""
        resp = self._client.delete(f"/schedules/{schedule_id}")
        resp.raise_for_status()
        return resp.json()
