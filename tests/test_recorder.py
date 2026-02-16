"""Tests for workflow recorder (unit tests)."""

import tempfile
from pathlib import Path

from screenpilot.recorder.recorder import RecordedEvent, Workflow


def test_workflow_save_load():
    workflow = Workflow(
        name="test-workflow",
        description="A test workflow",
        start_time=1000.0,
        end_time=1010.0,
        events=[
            RecordedEvent(timestamp=1000.0, event_type="click", x=100, y=200),
            RecordedEvent(timestamp=1002.0, event_type="type", text="hello"),
            RecordedEvent(timestamp=1005.0, event_type="key", key="enter"),
        ],
    )

    with tempfile.TemporaryDirectory() as tmpdir:
        path = Path(tmpdir) / "workflow.json"
        workflow.save(path)

        loaded = Workflow.load(path)
        assert loaded.name == "test-workflow"
        assert loaded.description == "A test workflow"
        assert len(loaded.events) == 3
        assert loaded.events[0].event_type == "click"
        assert loaded.events[0].x == 100
        assert loaded.events[1].text == "hello"
        assert loaded.events[2].key == "enter"


def test_workflow_duration():
    workflow = Workflow(
        name="test",
        events=[
            RecordedEvent(timestamp=100.0, event_type="click", x=0, y=0),
            RecordedEvent(timestamp=105.0, event_type="click", x=0, y=0),
        ],
    )
    assert workflow.duration == 5.0


def test_workflow_empty_duration():
    workflow = Workflow(name="empty")
    assert workflow.duration == 0.0


def test_recorded_event():
    event = RecordedEvent(
        timestamp=1000.0,
        event_type="click",
        x=100,
        y=200,
        button="left",
        screenshot_path="/tmp/screenshot.png",
    )
    assert event.x == 100
    assert event.y == 200
    assert event.button == "left"
