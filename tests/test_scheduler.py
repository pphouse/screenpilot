"""Tests for task scheduler."""

import tempfile
from datetime import datetime, timedelta
from pathlib import Path

from screenpilot.scheduler.scheduler import ScheduledTask, ScheduleType, TaskScheduler


def test_once_schedule():
    future = (datetime.now() + timedelta(hours=1)).isoformat()
    task = ScheduledTask(
        id="t1",
        name="One-time task",
        goal="Do something",
        schedule_type=ScheduleType.ONCE,
        run_at=future,
    )
    next_run = task.calculate_next_run()
    assert next_run is not None
    assert next_run > datetime.now()


def test_once_schedule_past():
    past = (datetime.now() - timedelta(hours=1)).isoformat()
    task = ScheduledTask(
        id="t1",
        name="Past task",
        goal="Do something",
        schedule_type=ScheduleType.ONCE,
        run_at=past,
    )
    assert task.calculate_next_run() is None


def test_interval_schedule():
    task = ScheduledTask(
        id="t2",
        name="Interval task",
        goal="Check status",
        schedule_type=ScheduleType.INTERVAL,
        interval_seconds=3600,
    )
    # No last_run → should run now
    next_run = task.calculate_next_run()
    assert next_run is not None
    assert (next_run - datetime.now()).total_seconds() < 2


def test_interval_after_run():
    last = (datetime.now() - timedelta(minutes=30)).isoformat()
    task = ScheduledTask(
        id="t2",
        name="Interval task",
        goal="Check status",
        schedule_type=ScheduleType.INTERVAL,
        interval_seconds=3600,
        last_run=last,
    )
    next_run = task.calculate_next_run()
    assert next_run is not None
    # Should be ~30 min from now
    diff = (next_run - datetime.now()).total_seconds()
    assert 1700 < diff < 1900


def test_daily_schedule():
    task = ScheduledTask(
        id="t3",
        name="Daily report",
        goal="Generate daily report",
        schedule_type=ScheduleType.DAILY,
        time_of_day="03:00",
    )
    next_run = task.calculate_next_run()
    assert next_run is not None
    assert next_run.hour == 3
    assert next_run.minute == 0


def test_weekly_schedule():
    task = ScheduledTask(
        id="t4",
        name="Weekly sync",
        goal="Sync data weekly",
        schedule_type=ScheduleType.WEEKLY,
        day_of_week=0,  # Monday
        time_of_day="09:00",
    )
    next_run = task.calculate_next_run()
    assert next_run is not None
    assert next_run.weekday() == 0
    assert next_run.hour == 9


def test_cron_schedule():
    task = ScheduledTask(
        id="t5",
        name="Cron task",
        goal="Run every hour",
        schedule_type=ScheduleType.CRON,
        cron_expr="0 * * * *",
    )
    next_run = task.calculate_next_run()
    assert next_run is not None
    assert next_run.minute == 0


def test_should_run():
    past = (datetime.now() - timedelta(minutes=5)).isoformat()
    task = ScheduledTask(
        id="t6",
        name="Due task",
        goal="Run now",
        schedule_type=ScheduleType.ONCE,
        run_at=past,
        next_run=past,
    )
    assert task.should_run()


def test_should_not_run_disabled():
    past = (datetime.now() - timedelta(minutes=5)).isoformat()
    task = ScheduledTask(
        id="t7",
        name="Disabled task",
        goal="Skip",
        schedule_type=ScheduleType.ONCE,
        run_at=past,
        next_run=past,
        enabled=False,
    )
    assert not task.should_run()


def test_mark_run_once():
    task = ScheduledTask(
        id="t8",
        name="One-shot",
        goal="Run once",
        schedule_type=ScheduleType.ONCE,
    )
    task.mark_run(success=True)
    assert task.run_count == 1
    assert task.last_success is True
    assert not task.enabled  # Disabled after one-shot


def test_mark_run_interval():
    task = ScheduledTask(
        id="t9",
        name="Repeating",
        goal="Run again",
        schedule_type=ScheduleType.INTERVAL,
        interval_seconds=3600,
    )
    task.mark_run(success=True)
    assert task.run_count == 1
    assert task.enabled  # Still enabled
    assert task.next_run is not None


def test_serialize_deserialize():
    task = ScheduledTask(
        id="ser1",
        name="Serialized",
        goal="Test serialization",
        schedule_type=ScheduleType.DAILY,
        time_of_day="08:30",
        template_id="web_form_fill",
        template_params={"url": "https://example.com"},
    )
    data = task.to_dict()
    restored = ScheduledTask.from_dict(data)
    assert restored.id == task.id
    assert restored.schedule_type == ScheduleType.DAILY
    assert restored.time_of_day == "08:30"
    assert restored.template_id == "web_form_fill"


def test_scheduler_add_remove():
    scheduler = TaskScheduler()
    task = ScheduledTask(
        id="s1",
        name="Test",
        goal="Test task",
        schedule_type=ScheduleType.ONCE,
        run_at=(datetime.now() + timedelta(hours=1)).isoformat(),
    )
    scheduler.add(task)
    assert len(scheduler.list_all()) == 1
    assert scheduler.get("s1") is not None

    scheduler.remove("s1")
    assert len(scheduler.list_all()) == 0


def test_scheduler_list_pending():
    scheduler = TaskScheduler()
    past = (datetime.now() - timedelta(minutes=5)).isoformat()
    future = (datetime.now() + timedelta(hours=1)).isoformat()

    scheduler.add(
        ScheduledTask(
            id="due",
            name="Due",
            goal="Run",
            schedule_type=ScheduleType.ONCE,
            run_at=past,
            next_run=past,
        )
    )
    scheduler.add(
        ScheduledTask(
            id="future",
            name="Future",
            goal="Wait",
            schedule_type=ScheduleType.ONCE,
            run_at=future,
            next_run=future,
        )
    )

    pending = scheduler.list_pending()
    assert len(pending) == 1
    assert pending[0].id == "due"


def test_scheduler_persist():
    with tempfile.NamedTemporaryFile(suffix=".json", delete=False) as f:
        path = f.name

    scheduler = TaskScheduler(persist_path=path)
    scheduler.add(
        ScheduledTask(
            id="p1",
            name="Persist",
            goal="Save me",
            schedule_type=ScheduleType.DAILY,
            time_of_day="10:00",
        )
    )

    # Load from file
    scheduler2 = TaskScheduler(persist_path=path)
    assert len(scheduler2.list_all()) == 1
    assert scheduler2.get("p1").name == "Persist"

    Path(path).unlink()


def test_scheduler_start_stop():
    scheduler = TaskScheduler()
    assert not scheduler.is_running
    scheduler.start(check_interval=60)
    assert scheduler.is_running
    scheduler.stop()
    assert not scheduler.is_running
