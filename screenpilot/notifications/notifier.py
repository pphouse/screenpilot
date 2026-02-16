"""Notification system for task events.

Supports multiple channels: webhook (Slack/Teams/generic), email (SMTP),
and console. Enterprise users need to know immediately when unattended
automations succeed or fail.
"""

from __future__ import annotations

import json
import logging
import smtplib
import urllib.request
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from email.mime.text import MIMEText
from typing import Any

logger = logging.getLogger(__name__)


@dataclass
class Notification:
    """A notification message."""

    title: str
    message: str
    level: str = "info"  # info, success, warning, error
    task_id: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)


class Notifier(ABC):
    """Base class for notification channels."""

    @abstractmethod
    def send(self, notification: Notification) -> bool:
        """Send a notification. Returns True if successful."""

    @abstractmethod
    def name(self) -> str:
        """Channel name."""


class WebhookNotifier(Notifier):
    """Send notifications via HTTP webhook (Slack, Teams, generic).

    Formats messages according to the target platform.
    """

    def __init__(self, url: str, platform: str = "generic", headers: dict | None = None):
        self.url = url
        self.platform = platform
        self.headers = headers or {"Content-Type": "application/json"}

    def name(self) -> str:
        return f"webhook:{self.platform}"

    def send(self, notification: Notification) -> bool:
        payload = self._format_payload(notification)
        data = json.dumps(payload).encode("utf-8")

        req = urllib.request.Request(self.url, data=data, headers=self.headers, method="POST")
        try:
            with urllib.request.urlopen(req, timeout=10) as resp:
                return resp.status < 400
        except Exception as e:
            logger.error("Webhook notification failed: %s", e)
            return False

    def _format_payload(self, notification: Notification) -> dict:
        if self.platform == "slack":
            icon = {
                "info": ":information_source:",
                "success": ":white_check_mark:",
                "warning": ":warning:",
                "error": ":x:",
            }.get(notification.level, "")
            return {
                "text": f"{icon} *{notification.title}*\n{notification.message}",
                "username": "ScreenPilot",
            }
        if self.platform == "teams":
            color = {
                "info": "0078D7",
                "success": "00CC6A",
                "warning": "FFB900",
                "error": "E81123",
            }.get(notification.level, "0078D7")
            return {
                "@type": "MessageCard",
                "themeColor": color,
                "title": notification.title,
                "text": notification.message,
            }
        return {
            "title": notification.title,
            "message": notification.message,
            "level": notification.level,
            "task_id": notification.task_id,
            "metadata": notification.metadata,
        }


class EmailNotifier(Notifier):
    """Send notifications via SMTP email."""

    def __init__(
        self,
        smtp_host: str,
        smtp_port: int = 587,
        username: str = "",
        password: str = "",
        from_addr: str = "",
        to_addrs: list[str] | None = None,
        use_tls: bool = True,
    ):
        self.smtp_host = smtp_host
        self.smtp_port = smtp_port
        self.username = username
        self.password = password
        self.from_addr = from_addr
        self.to_addrs = to_addrs or []
        self.use_tls = use_tls

    def name(self) -> str:
        return "email"

    def send(self, notification: Notification) -> bool:
        if not self.to_addrs:
            return False

        msg = MIMEText(notification.message)
        msg["Subject"] = f"[ScreenPilot] {notification.title}"
        msg["From"] = self.from_addr
        msg["To"] = ", ".join(self.to_addrs)

        try:
            with smtplib.SMTP(self.smtp_host, self.smtp_port) as server:
                if self.use_tls:
                    server.starttls()
                if self.username:
                    server.login(self.username, self.password)
                server.sendmail(self.from_addr, self.to_addrs, msg.as_string())
            return True
        except Exception as e:
            logger.error("Email notification failed: %s", e)
            return False


class ConsoleNotifier(Notifier):
    """Log notifications to the console/logger."""

    def name(self) -> str:
        return "console"

    def send(self, notification: Notification) -> bool:
        level_map = {
            "info": logging.INFO,
            "success": logging.INFO,
            "warning": logging.WARNING,
            "error": logging.ERROR,
        }
        log_level = level_map.get(notification.level, logging.INFO)
        logger.log(
            log_level,
            "[%s] %s: %s",
            notification.level.upper(),
            notification.title,
            notification.message,
        )
        return True


class NotificationManager:
    """Manages multiple notification channels."""

    def __init__(self):
        self._channels: list[Notifier] = []
        self._history: list[tuple[Notification, dict[str, bool]]] = []

    def add_channel(self, notifier: Notifier) -> None:
        """Add a notification channel."""
        self._channels.append(notifier)

    def remove_channel(self, channel_name: str) -> bool:
        """Remove a notification channel by name."""
        for i, ch in enumerate(self._channels):
            if ch.name() == channel_name:
                self._channels.pop(i)
                return True
        return False

    @property
    def channels(self) -> list[str]:
        """List channel names."""
        return [ch.name() for ch in self._channels]

    def notify(self, notification: Notification) -> dict[str, bool]:
        """Send a notification to all channels."""
        results = {}
        for channel in self._channels:
            results[channel.name()] = channel.send(notification)
        self._history.append((notification, results))
        return results

    def notify_task_complete(
        self, task_id: str, goal: str, success: bool, time_taken: float
    ) -> dict[str, bool]:
        """Convenience method for task completion notifications."""
        status = "completed successfully" if success else "failed"
        level = "success" if success else "error"
        return self.notify(
            Notification(
                title=f"Task {status}",
                message=f"Task '{goal}' {status} in {time_taken:.1f}s",
                level=level,
                task_id=task_id,
                metadata={"success": success, "time": time_taken},
            )
        )

    def notify_error(self, task_id: str, error: str) -> dict[str, bool]:
        """Convenience method for error notifications."""
        return self.notify(
            Notification(
                title="Automation Error",
                message=error,
                level="error",
                task_id=task_id,
            )
        )

    @property
    def history(self) -> list[tuple[Notification, dict[str, bool]]]:
        return list(self._history)
