"""Execution reporting and analytics.

Generates structured reports of automation runs for business stakeholders.
Supports JSON, HTML, and summary formats. Tracks KPIs like success rate,
average execution time, and common failure patterns.
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)


@dataclass
class StepReport:
    """Report of a single execution step."""

    step_number: int
    action_type: str
    target: str | None = None
    success: bool = True
    duration: float = 0.0
    error: str | None = None
    reasoning: str = ""


@dataclass
class ExecutionReport:
    """Complete report of a task execution."""

    task_id: str
    goal: str
    start_time: str
    end_time: str
    success: bool
    total_time: float
    num_steps: int
    steps: list[StepReport] = field(default_factory=list)
    error: str | None = None
    recovery_attempts: int = 0
    template_id: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict:
        return {
            "task_id": self.task_id,
            "goal": self.goal,
            "start_time": self.start_time,
            "end_time": self.end_time,
            "success": self.success,
            "total_time": self.total_time,
            "num_steps": self.num_steps,
            "steps": [
                {
                    "step_number": s.step_number,
                    "action_type": s.action_type,
                    "target": s.target,
                    "success": s.success,
                    "duration": s.duration,
                    "error": s.error,
                    "reasoning": s.reasoning,
                }
                for s in self.steps
            ],
            "error": self.error,
            "recovery_attempts": self.recovery_attempts,
            "template_id": self.template_id,
            "metadata": self.metadata,
        }

    @classmethod
    def from_dict(cls, data: dict) -> ExecutionReport:
        steps = [StepReport(**s) for s in data.get("steps", [])]
        return cls(
            task_id=data["task_id"],
            goal=data["goal"],
            start_time=data["start_time"],
            end_time=data["end_time"],
            success=data["success"],
            total_time=data["total_time"],
            num_steps=data["num_steps"],
            steps=steps,
            error=data.get("error"),
            recovery_attempts=data.get("recovery_attempts", 0),
            template_id=data.get("template_id"),
            metadata=data.get("metadata", {}),
        )

    def to_json(self, path: str | Path) -> None:
        """Save report as JSON file."""
        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        with open(path, "w") as f:
            json.dump(self.to_dict(), f, indent=2)

    def to_html(self) -> str:
        """Generate an HTML report."""
        status_color = "#22c55e" if self.success else "#ef4444"
        status_text = "Success" if self.success else "Failed"

        steps_html = ""
        for step in self.steps:
            s_color = "#22c55e" if step.success else "#ef4444"
            steps_html += f"""
            <tr>
                <td>{step.step_number}</td>
                <td>{step.action_type}</td>
                <td>{step.target or "-"}</td>
                <td style="color: {s_color}">{"OK" if step.success else "FAIL"}</td>
                <td>{step.duration:.2f}s</td>
                <td>{step.error or "-"}</td>
            </tr>"""

        return f"""<!DOCTYPE html>
<html>
<head>
<title>ScreenPilot Report - {self.task_id}</title>
<style>
body {{ font-family: -apple-system, sans-serif; max-width: 900px; margin: 2rem auto; padding: 0 1rem; background: #0f172a; color: #e2e8f0; }}
h1 {{ font-size: 1.5rem; }}
.summary {{ display: grid; grid-template-columns: repeat(auto-fit, minmax(150px, 1fr)); gap: 1rem; margin: 1.5rem 0; }}
.stat {{ background: #1e293b; padding: 1rem; border-radius: 8px; text-align: center; }}
.stat .value {{ font-size: 1.5rem; font-weight: 700; }}
.stat .label {{ font-size: 0.75rem; color: #94a3b8; text-transform: uppercase; }}
table {{ width: 100%; border-collapse: collapse; margin-top: 1.5rem; }}
th, td {{ padding: 8px 12px; text-align: left; border-bottom: 1px solid #334155; font-size: 0.85rem; }}
th {{ color: #94a3b8; font-weight: 600; text-transform: uppercase; font-size: 0.75rem; }}
.goal {{ background: #1e293b; padding: 1rem; border-radius: 8px; margin: 1rem 0; }}
</style>
</head>
<body>
<h1>ScreenPilot Execution Report</h1>
<div class="goal"><strong>Goal:</strong> {self.goal}</div>
<div class="summary">
    <div class="stat"><div class="value" style="color: {status_color}">{status_text}</div><div class="label">Status</div></div>
    <div class="stat"><div class="value">{self.num_steps}</div><div class="label">Steps</div></div>
    <div class="stat"><div class="value">{self.total_time:.1f}s</div><div class="label">Duration</div></div>
    <div class="stat"><div class="value">{self.recovery_attempts}</div><div class="label">Recoveries</div></div>
</div>
<p><strong>Task ID:</strong> {self.task_id} | <strong>Start:</strong> {self.start_time} | <strong>End:</strong> {self.end_time}</p>
{f'<p style="color: #ef4444"><strong>Error:</strong> {self.error}</p>' if self.error else ""}
<table>
<thead><tr><th>#</th><th>Action</th><th>Target</th><th>Status</th><th>Duration</th><th>Error</th></tr></thead>
<tbody>{steps_html}</tbody>
</table>
<p style="margin-top: 2rem; color: #64748b; font-size: 0.75rem;">Generated by ScreenPilot</p>
</body>
</html>"""

    def summary(self) -> str:
        """Generate a text summary."""
        status = "SUCCESS" if self.success else "FAILED"
        failed_steps = [s for s in self.steps if not s.success]
        lines = [
            f"Task: {self.goal}",
            f"Status: {status}",
            f"Steps: {self.num_steps} ({len(failed_steps)} failed)",
            f"Duration: {self.total_time:.1f}s",
            f"Recoveries: {self.recovery_attempts}",
        ]
        if self.error:
            lines.append(f"Error: {self.error}")
        return "\n".join(lines)


class ReportGenerator:
    """Generates and stores execution reports."""

    def __init__(self, output_dir: str | Path = "~/.screenpilot/reports"):
        self.output_dir = Path(output_dir).expanduser()
        self._reports: list[ExecutionReport] = []

    def add_report(self, report: ExecutionReport) -> None:
        """Add a report."""
        self._reports.append(report)

    def save_report(self, report: ExecutionReport, format: str = "json") -> Path:
        """Save a report to file."""
        self.output_dir.mkdir(parents=True, exist_ok=True)
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        filename = f"report_{report.task_id}_{timestamp}"

        if format == "html":
            path = self.output_dir / f"{filename}.html"
            path.write_text(report.to_html())
        else:
            path = self.output_dir / f"{filename}.json"
            report.to_json(path)

        logger.info("Report saved: %s", path)
        return path

    @property
    def reports(self) -> list[ExecutionReport]:
        return list(self._reports)

    def aggregate_stats(self) -> dict:
        """Aggregate statistics across all reports."""
        if not self._reports:
            return {"total": 0, "success_rate": 0.0}

        total = len(self._reports)
        successes = sum(1 for r in self._reports if r.success)
        total_time = sum(r.total_time for r in self._reports)
        total_steps = sum(r.num_steps for r in self._reports)
        total_recoveries = sum(r.recovery_attempts for r in self._reports)

        # Common failures
        failure_counts: dict[str, int] = {}
        for r in self._reports:
            for s in r.steps:
                if not s.success and s.error:
                    key = s.error[:50]
                    failure_counts[key] = failure_counts.get(key, 0) + 1

        return {
            "total": total,
            "successes": successes,
            "failures": total - successes,
            "success_rate": successes / total,
            "average_time": total_time / total,
            "average_steps": total_steps / total,
            "total_recoveries": total_recoveries,
            "common_failures": dict(sorted(failure_counts.items(), key=lambda x: -x[1])[:5]),
        }
