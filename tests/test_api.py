"""Tests for the FastAPI server endpoints."""

import os
import sys

os.environ.setdefault("DISPLAY", ":99")

# Mock display-dependent modules before imports
from unittest.mock import MagicMock

sys.modules.setdefault("pyautogui", MagicMock())
sys.modules.setdefault("pynput", MagicMock())
sys.modules.setdefault("pynput.mouse", MagicMock())
sys.modules.setdefault("pynput.keyboard", MagicMock())
sys.modules.setdefault("mss", MagicMock())

from fastapi.testclient import TestClient

from screenpilot.api.server import create_app
from screenpilot.config import ScreenPilotConfig


def _client() -> TestClient:
    app = create_app(ScreenPilotConfig())
    return TestClient(app)


def test_health():
    client = _client()
    response = client.get("/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_api_info():
    client = _client()
    response = client.get("/api")
    assert response.status_code == 200
    data = response.json()
    assert data["name"] == "ScreenPilot API"
    assert data["status"] == "running"
    assert "version" in data


def test_root_serves_dashboard():
    client = _client()
    response = client.get("/")
    assert response.status_code == 200
    # Should serve HTML dashboard
    assert "ScreenPilot" in response.text


def test_list_templates():
    client = _client()
    response = client.get("/templates")
    assert response.status_code == 200
    templates = response.json()
    assert len(templates) >= 5
    assert any(t["id"] == "web_form_fill" for t in templates)


def test_get_template():
    client = _client()
    response = client.get("/templates/web_form_fill")
    assert response.status_code == 200
    data = response.json()
    assert data["name"] == "Fill Web Form"
    assert data["category"] == "data_entry"


def test_get_template_not_found():
    client = _client()
    response = client.get("/templates/nonexistent")
    assert response.status_code == 404


def test_list_tasks_empty():
    client = _client()
    response = client.get("/tasks")
    assert response.status_code == 200
    assert response.json() == []


def test_get_task_not_found():
    client = _client()
    response = client.get("/task/nonexistent")
    assert response.status_code == 404


def test_stop_task_not_found():
    client = _client()
    response = client.post("/task/nonexistent/stop")
    assert response.status_code == 404


def test_list_schedules_empty():
    client = _client()
    response = client.get("/schedules")
    assert response.status_code == 200
    assert response.json() == []


def test_add_schedule():
    client = _client()
    response = client.post(
        "/schedules",
        json={
            "id": "test_sched",
            "name": "Test Schedule",
            "goal": "Do something",
            "schedule_type": "daily",
            "time_of_day": "09:00",
        },
    )
    assert response.status_code == 200
    data = response.json()
    assert data["id"] == "test_sched"
    assert data["schedule_type"] == "daily"


def test_add_and_list_schedule():
    client = _client()
    client.post(
        "/schedules",
        json={
            "id": "s1",
            "name": "S1",
            "goal": "Goal",
            "schedule_type": "interval",
            "interval_seconds": 3600,
        },
    )
    response = client.get("/schedules")
    assert response.status_code == 200
    schedules = response.json()
    assert len(schedules) == 1


def test_delete_schedule():
    client = _client()
    client.post(
        "/schedules",
        json={
            "id": "s_del",
            "name": "Delete me",
            "goal": "Goal",
            "schedule_type": "once",
        },
    )
    response = client.delete("/schedules/s_del")
    assert response.status_code == 200
    assert response.json()["status"] == "removed"


def test_delete_schedule_not_found():
    client = _client()
    response = client.delete("/schedules/nope")
    assert response.status_code == 404


def test_list_reports_empty():
    client = _client()
    response = client.get("/reports")
    assert response.status_code == 200
    assert response.json() == []


def test_report_stats_empty():
    client = _client()
    response = client.get("/reports/stats")
    assert response.status_code == 200
    data = response.json()
    assert data["total"] == 0
