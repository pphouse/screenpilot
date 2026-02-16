"""Task scheduler for running automations on a schedule.

Supports cron-like scheduling, one-shot delayed execution, and
recurring intervals. Critical for enterprise RPA replacement where
tasks run unattended (e.g., daily report generation, periodic data sync).
"""

from __future__ import annotations

import json
import logging
import threading
import time
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from enum import Enum
from pathlib import Path
from typing import Any, Callable

logger = logging.getLogger(__name__)


class ScheduleType(str, Enum):
    """Types of schedules."""

    ONCE = "once"
    INTERVAL = "interval"
    DAILY = "daily"
    WEEKLY = "weekly"
    CRON = "cron"


@dataclass
class ScheduledTask:
    """A task scheduled for future execution."""

    id: str
    name: str
    goal: str
    schedule_type: ScheduleType
    max_steps: int = 50
    enabled: bool = True

    # Schedule parameters
    run_at: str | None = None  # ISO datetime for ONCE
    interval_seconds: int = 3600  # For INTERVAL
    time_of_day: str | None = None  # HH:MM for DAILY
    day_of_week: int | None = None  # 0=Mon for WEEKLY
    cron_expr: str | None = None  # Cron expression

    # State
    last_run: str | None = None
    next_run: str | None = None
    run_count: int = 0
    last_success: bool | None = None
    last_error: str | None = None

    # Template support
    template_id: str | None = None
    template_params: dict[str, Any] = field(default_factory=dict)

    def calculate_next_run(self, from_time: datetime | None = None) -> datetime | None:
        """Calculate the next run time based on schedule type."""
        now = from_time or datetime.now()

        if self.schedule_type == ScheduleType.ONCE:
            if self.run_at:
                run_time = datetime.fromisoformat(self.run_at)
                return run_time if run_time > now else None
            return None

        if self.schedule_type == ScheduleType.INTERVAL:
            if self.last_run:
                last = datetime.fromisoformat(self.last_run)
                return last + timedelta(seconds=self.interval_seconds)
            return now

        if self.schedule_type == ScheduleType.DAILY:
            if self.time_of_day:
                hour, minute = map(int, self.time_of_day.split(":"))
                target = now.replace(hour=hour, minute=minute, second=0, microsecond=0)
                if target <= now:
                    target += timedelta(days=1)
                return target
            return None

        if self.schedule_type == ScheduleType.WEEKLY:
            if self.day_of_week is not None and self.time_of_day:
                hour, minute = map(int, self.time_of_day.split(":"))
                target = now.replace(hour=hour, minute=minute, second=0, microsecond=0)
                days_ahead = self.day_of_week - now.weekday()
                if days_ahead < 0 or (days_ahead == 0 and target <= now):
                    days_ahead += 7
                target += timedelta(days=days_ahead)
                return target
            return None

        if self.schedule_type == ScheduleType.CRON:
            return self._next_cron_run(now)

        return None

    def _next_cron_run(self, now: datetime) -> datetime | None:
        """Simple cron-like next run calculation.

        Supports: minute hour day_of_month month day_of_week
        With * for any, and specific values.
        """
        if not self.cron_expr:
            return None

        parts = self.cron_expr.strip().split()
        if len(parts) != 5:
            return None

        minute_spec, hour_spec, dom_spec, month_spec, dow_spec = parts

        def parse_field(spec: str, min_val: int, max_val: int) -> list[int]:
            if spec == "*":
                return list(range(min_val, max_val + 1))
            if "," in spec:
                return [int(v) for v in spec.split(",")]
            if "/" in spec:
                base, step = spec.split("/")
                start = min_val if base == "*" else int(base)
                return list(range(start, max_val + 1, int(step)))
            return [int(spec)]

        minutes = parse_field(minute_spec, 0, 59)
        hours = parse_field(hour_spec, 0, 23)
        doms = parse_field(dom_spec, 1, 31)
        months = parse_field(month_spec, 1, 12)
        dows = parse_field(dow_spec, 0, 6)

        # Brute-force search for next match within 366 days
        candidate = now.replace(second=0, microsecond=0) + timedelta(minutes=1)
        for _ in range(366 * 24 * 60):
            if (
                candidate.minute in minutes
                and candidate.hour in hours
                and candidate.day in doms
                and candidate.month in months
                and candidate.weekday() in dows
            ):
                return candidate
            candidate += timedelta(minutes=1)

        return None

    def should_run(self, now: datetime | None = None) -> bool:
        """Check if this task should run now."""
        if not self.enabled:
            return False

        now = now or datetime.now()

        if self.next_run:
            next_time = datetime.fromisoformat(self.next_run)
            return now >= next_time

        # No next_run set, calculate it
        next_time = self.calculate_next_run(now)
        if next_time:
            self.next_run = next_time.isoformat()
            return now >= next_time

        return False

    def mark_run(self, success: bool, error: str | None = None) -> None:
        """Mark a task as having run, update state."""
        now = datetime.now()
        self.last_run = now.isoformat()
        self.run_count += 1
        self.last_success = success
        self.last_error = error

        # Calculate next run
        if self.schedule_type == ScheduleType.ONCE:
            self.enabled = False
            self.next_run = None
        else:
            next_time = self.calculate_next_run(now)
            self.next_run = next_time.isoformat() if next_time else None

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "name": self.name,
            "goal": self.goal,
            "schedule_type": self.schedule_type.value,
            "max_steps": self.max_steps,
            "enabled": self.enabled,
            "run_at": self.run_at,
            "interval_seconds": self.interval_seconds,
            "time_of_day": self.time_of_day,
            "day_of_week": self.day_of_week,
            "cron_expr": self.cron_expr,
            "last_run": self.last_run,
            "next_run": self.next_run,
            "run_count": self.run_count,
            "last_success": self.last_success,
            "last_error": self.last_error,
            "template_id": self.template_id,
            "template_params": self.template_params,
        }

    @classmethod
    def from_dict(cls, data: dict) -> ScheduledTask:
        return cls(
            id=data["id"],
            name=data["name"],
            goal=data["goal"],
            schedule_type=ScheduleType(data["schedule_type"]),
            max_steps=data.get("max_steps", 50),
            enabled=data.get("enabled", True),
            run_at=data.get("run_at"),
            interval_seconds=data.get("interval_seconds", 3600),
            time_of_day=data.get("time_of_day"),
            day_of_week=data.get("day_of_week"),
            cron_expr=data.get("cron_expr"),
            last_run=data.get("last_run"),
            next_run=data.get("next_run"),
            run_count=data.get("run_count", 0),
            last_success=data.get("last_success"),
            last_error=data.get("last_error"),
            template_id=data.get("template_id"),
            template_params=data.get("template_params", {}),
        )


class TaskScheduler:
    """Scheduler that manages and executes scheduled tasks.

    Runs a background thread that checks for tasks due to execute.
    Tasks are persisted to a JSON file for durability across restarts.
    """

    def __init__(self, persist_path: str | Path | None = None):
        self._tasks: dict[str, ScheduledTask] = {}
        self._running = False
        self._thread: threading.Thread | None = None
        self._on_task: Callable[[ScheduledTask], None] | None = None
        self._lock = threading.Lock()
        self._persist_path = Path(persist_path) if persist_path else None

        if (
            self._persist_path
            and self._persist_path.exists()
            and self._persist_path.stat().st_size > 0
        ):
            self._load()

    def add(self, task: ScheduledTask) -> None:
        """Add a scheduled task."""
        with self._lock:
            # Calculate initial next_run
            if not task.next_run:
                next_time = task.calculate_next_run()
                if next_time:
                    task.next_run = next_time.isoformat()
            self._tasks[task.id] = task
            self._save()
        logger.info("Scheduled task: %s (%s)", task.name, task.schedule_type.value)

    def remove(self, task_id: str) -> bool:
        """Remove a scheduled task."""
        with self._lock:
            if task_id in self._tasks:
                del self._tasks[task_id]
                self._save()
                return True
        return False

    def get(self, task_id: str) -> ScheduledTask | None:
        return self._tasks.get(task_id)

    def list_all(self) -> list[ScheduledTask]:
        return list(self._tasks.values())

    def list_pending(self) -> list[ScheduledTask]:
        """List tasks that are due to run."""
        now = datetime.now()
        return [t for t in self._tasks.values() if t.should_run(now)]

    def on_task(self, callback: Callable[[ScheduledTask], None]) -> None:
        """Register a callback for when a task should execute."""
        self._on_task = callback

    def start(self, check_interval: float = 30.0) -> None:
        """Start the scheduler background thread."""
        if self._running:
            return
        self._running = True
        self._thread = threading.Thread(
            target=self._run_loop,
            args=(check_interval,),
            daemon=True,
        )
        self._thread.start()
        logger.info("Scheduler started (check every %.0fs)", check_interval)

    def stop(self) -> None:
        """Stop the scheduler."""
        self._running = False
        if self._thread:
            self._thread.join(timeout=5)
            self._thread = None
        logger.info("Scheduler stopped")

    def _run_loop(self, check_interval: float) -> None:
        """Main scheduler loop."""
        while self._running:
            try:
                self._check_and_run()
            except Exception as e:
                logger.error("Scheduler error: %s", e)
            time.sleep(check_interval)

    def _check_and_run(self) -> None:
        """Check for due tasks and trigger them."""
        now = datetime.now()
        with self._lock:
            due_tasks = [t for t in self._tasks.values() if t.should_run(now)]

        for task in due_tasks:
            logger.info("Running scheduled task: %s", task.name)
            if self._on_task:
                try:
                    self._on_task(task)
                except Exception as e:
                    logger.error("Task execution error for %s: %s", task.name, e)
                    task.mark_run(success=False, error=str(e))
            with self._lock:
                self._save()

    def _save(self) -> None:
        """Persist tasks to file."""
        if not self._persist_path:
            return
        self._persist_path.parent.mkdir(parents=True, exist_ok=True)
        data = {"tasks": [t.to_dict() for t in self._tasks.values()]}
        with open(self._persist_path, "w") as f:
            json.dump(data, f, indent=2)

    def _load(self) -> None:
        """Load tasks from file."""
        if not self._persist_path or not self._persist_path.exists():
            return
        with open(self._persist_path) as f:
            data = json.load(f)
        for t_data in data.get("tasks", []):
            task = ScheduledTask.from_dict(t_data)
            self._tasks[task.id] = task
        logger.info("Loaded %d scheduled tasks", len(self._tasks))

    @property
    def is_running(self) -> bool:
        return self._running
