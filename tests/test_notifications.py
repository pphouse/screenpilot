"""Tests for notification system."""

from screenpilot.notifications.notifier import (
    ConsoleNotifier,
    Notification,
    NotificationManager,
    WebhookNotifier,
)


def test_notification_dataclass():
    n = Notification(title="Test", message="Hello", level="info")
    assert n.title == "Test"
    assert n.level == "info"
    assert n.task_id is None


def test_console_notifier():
    notifier = ConsoleNotifier()
    assert notifier.name() == "console"
    result = notifier.send(Notification(title="Test", message="Hello"))
    assert result is True


def test_console_notifier_levels():
    notifier = ConsoleNotifier()
    for level in ["info", "success", "warning", "error"]:
        result = notifier.send(Notification(title="Test", message="msg", level=level))
        assert result is True


def test_webhook_notifier_slack_format():
    notifier = WebhookNotifier(url="http://example.com", platform="slack")
    assert notifier.name() == "webhook:slack"
    payload = notifier._format_payload(
        Notification(title="Task Done", message="Success", level="success")
    )
    assert "text" in payload
    assert "Task Done" in payload["text"]
    assert "username" in payload


def test_webhook_notifier_teams_format():
    notifier = WebhookNotifier(url="http://example.com", platform="teams")
    assert notifier.name() == "webhook:teams"
    payload = notifier._format_payload(Notification(title="Error", message="Failed", level="error"))
    assert payload["@type"] == "MessageCard"
    assert payload["themeColor"] == "E81123"


def test_webhook_notifier_generic_format():
    notifier = WebhookNotifier(url="http://example.com", platform="generic")
    payload = notifier._format_payload(Notification(title="Info", message="Test", task_id="abc"))
    assert payload["title"] == "Info"
    assert payload["task_id"] == "abc"


def test_notification_manager_add_channel():
    manager = NotificationManager()
    manager.add_channel(ConsoleNotifier())
    assert "console" in manager.channels


def test_notification_manager_remove_channel():
    manager = NotificationManager()
    manager.add_channel(ConsoleNotifier())
    assert manager.remove_channel("console")
    assert "console" not in manager.channels


def test_notification_manager_remove_nonexistent():
    manager = NotificationManager()
    assert not manager.remove_channel("nonexistent")


def test_notification_manager_notify():
    manager = NotificationManager()
    manager.add_channel(ConsoleNotifier())
    results = manager.notify(Notification(title="Test", message="Hello"))
    assert results["console"] is True
    assert len(manager.history) == 1


def test_notification_manager_multi_channel():
    manager = NotificationManager()
    manager.add_channel(ConsoleNotifier())

    # Add a second console notifier under different name
    class NamedConsole(ConsoleNotifier):
        def name(self):
            return "console2"

    manager.add_channel(NamedConsole())
    results = manager.notify(Notification(title="Test", message="Hello"))
    assert len(results) == 2
    assert all(v is True for v in results.values())


def test_notify_task_complete_success():
    manager = NotificationManager()
    manager.add_channel(ConsoleNotifier())
    results = manager.notify_task_complete("t1", "Open Chrome", True, 5.3)
    assert results["console"] is True
    assert len(manager.history) == 1
    notification, _ = manager.history[0]
    assert notification.level == "success"
    assert "completed successfully" in notification.title


def test_notify_task_complete_failure():
    manager = NotificationManager()
    manager.add_channel(ConsoleNotifier())
    results = manager.notify_task_complete("t2", "Open Chrome", False, 10.5)
    assert results["console"] is True
    notification, _ = manager.history[0]
    assert notification.level == "error"
    assert "failed" in notification.title


def test_notify_error():
    manager = NotificationManager()
    manager.add_channel(ConsoleNotifier())
    results = manager.notify_error("t3", "Element not found on screen")
    assert results["console"] is True
    notification, _ = manager.history[0]
    assert notification.level == "error"
    assert notification.task_id == "t3"
