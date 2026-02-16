"""Tests for execution reporting system."""

import tempfile
from pathlib import Path

from screenpilot.reporting.report import ExecutionReport, ReportGenerator, StepReport


def _make_report(task_id: str = "abc123", success: bool = True, steps: int = 5) -> ExecutionReport:
    step_reports = [
        StepReport(
            step_number=i + 1,
            action_type="click",
            target=f"button_{i}",
            success=True if i < steps - 1 or success else False,
            duration=0.5,
            error=None if success or i < steps - 1 else "Click failed",
        )
        for i in range(steps)
    ]
    return ExecutionReport(
        task_id=task_id,
        goal="Test automation task",
        start_time="2026-01-15T10:00:00",
        end_time="2026-01-15T10:00:05",
        success=success,
        total_time=steps * 0.5,
        num_steps=steps,
        steps=step_reports,
        error=None if success else "Task failed",
    )


def test_report_to_dict():
    report = _make_report()
    data = report.to_dict()
    assert data["task_id"] == "abc123"
    assert data["success"] is True
    assert len(data["steps"]) == 5


def test_report_from_dict():
    report = _make_report()
    data = report.to_dict()
    restored = ExecutionReport.from_dict(data)
    assert restored.task_id == report.task_id
    assert restored.success == report.success
    assert len(restored.steps) == len(report.steps)


def test_report_summary_success():
    report = _make_report(success=True)
    summary = report.summary()
    assert "SUCCESS" in summary
    assert "Test automation task" in summary


def test_report_summary_failure():
    report = _make_report(success=False)
    summary = report.summary()
    assert "FAILED" in summary
    assert "Task failed" in summary


def test_report_to_html():
    report = _make_report()
    html = report.to_html()
    assert "<!DOCTYPE html>" in html
    assert "abc123" in html
    assert "Success" in html
    assert "ScreenPilot" in html


def test_report_to_html_failure():
    report = _make_report(success=False)
    html = report.to_html()
    assert "Failed" in html
    assert "Task failed" in html


def test_report_save_json():
    report = _make_report()
    with tempfile.TemporaryDirectory() as tmpdir:
        path = Path(tmpdir) / "report.json"
        report.to_json(path)
        assert path.exists()
        import json

        data = json.loads(path.read_text())
        assert data["task_id"] == "abc123"


def test_report_generator_add():
    gen = ReportGenerator()
    gen.add_report(_make_report("r1"))
    gen.add_report(_make_report("r2"))
    assert len(gen.reports) == 2


def test_report_generator_save():
    gen = ReportGenerator()
    report = _make_report()
    with tempfile.TemporaryDirectory() as tmpdir:
        gen.output_dir = Path(tmpdir)
        path = gen.save_report(report, format="json")
        assert path.exists()

        path_html = gen.save_report(report, format="html")
        assert path_html.exists()
        assert path_html.suffix == ".html"


def test_aggregate_stats_empty():
    gen = ReportGenerator()
    stats = gen.aggregate_stats()
    assert stats["total"] == 0


def test_aggregate_stats():
    gen = ReportGenerator()
    gen.add_report(_make_report("r1", success=True, steps=5))
    gen.add_report(_make_report("r2", success=True, steps=3))
    gen.add_report(_make_report("r3", success=False, steps=7))

    stats = gen.aggregate_stats()
    assert stats["total"] == 3
    assert stats["successes"] == 2
    assert stats["failures"] == 1
    assert abs(stats["success_rate"] - 2 / 3) < 0.01
    assert stats["average_steps"] == 5.0


def test_step_report():
    step = StepReport(
        step_number=1,
        action_type="click",
        target="button",
        success=True,
        duration=0.3,
    )
    assert step.step_number == 1
    assert step.success
    assert step.error is None
