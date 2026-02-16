"""Tests for the Python SDK client (offline/mock tests)."""

from screenpilot.sdk.client import (
    ActionResult,
    Element,
    Screenshot,
    TaskHandle,
    Template,
)


def test_screenshot_dataclass():
    ss = Screenshot(width=1920, height=1080, timestamp=1234567.0, image_base64="abc123")
    assert ss.width == 1920
    assert ss.height == 1080


def test_element_dataclass():
    el = Element(label="Submit", element_type="button", x=100, y=200, confidence=0.95)
    assert el.label == "Submit"
    assert el.confidence == 0.95


def test_action_result():
    result = ActionResult(success=True, duration=0.5)
    assert result.success
    assert result.error is None


def test_action_result_failure():
    result = ActionResult(success=False, error="Click failed", duration=0.3)
    assert not result.success
    assert "Click failed" in result.error


def test_task_handle_running():
    handle = TaskHandle(task_id="abc", goal="Test", status="running")
    assert handle.is_running
    assert not handle.success


def test_task_handle_completed():
    handle = TaskHandle(task_id="abc", goal="Test", status="completed")
    assert not handle.is_running
    assert handle.success


def test_task_handle_failed():
    handle = TaskHandle(task_id="abc", goal="Test", status="failed", error="Timeout")
    assert not handle.is_running
    assert not handle.success
    assert handle.error == "Timeout"


def test_template_dataclass():
    t = Template(
        id="test",
        name="Test Template",
        description="A test",
        category="testing",
        goal_template="Do {thing}",
        tags=["test"],
    )
    assert t.id == "test"
    assert t.estimated_steps == 10


def test_task_handle_stop_without_client():
    handle = TaskHandle(task_id="abc", goal="Test", status="running")
    handle.stop()
    assert handle.status == "stopped"
