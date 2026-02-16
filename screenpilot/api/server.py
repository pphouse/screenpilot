"""FastAPI server for remote control and monitoring."""

from __future__ import annotations

import asyncio
import logging
import time
import uuid
from pathlib import Path
from typing import Any

from fastapi import FastAPI, HTTPException, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from screenpilot import __version__
from screenpilot.agent import ScreenPilotAgent, StepResult
from screenpilot.config import ScreenPilotConfig
from screenpilot.planner.planner import Action, ActionType
from screenpilot.reporting.report import ReportGenerator
from screenpilot.scheduler.scheduler import ScheduledTask, ScheduleType, TaskScheduler
from screenpilot.templates.registry import TemplateRegistry
from screenpilot.vision.capture import ScreenCapture

logger = logging.getLogger(__name__)


class TaskRequest(BaseModel):
    """Request to run an automation task."""

    goal: str
    max_steps: int = 50


class ActionRequest(BaseModel):
    """Request to execute a single action."""

    action_type: str
    target: str | None = None
    x: int | None = None
    y: int | None = None
    text: str | None = None
    keys: str | None = None
    direction: str | None = None
    amount: int | None = None


class FindElementRequest(BaseModel):
    """Request to find a UI element."""

    target: str


class ScheduleRequest(BaseModel):
    """Request to create a scheduled task."""

    id: str
    name: str
    goal: str
    schedule_type: str
    max_steps: int = 50
    run_at: str | None = None
    interval_seconds: int = 3600
    time_of_day: str | None = None
    day_of_week: int | None = None
    cron_expr: str | None = None
    template_id: str | None = None
    template_params: dict = {}


class TaskStatus(BaseModel):
    """Status of a running task."""

    task_id: str
    goal: str
    status: str  # running, completed, failed, stopped
    current_step: int
    total_time: float
    error: str | None = None


def create_app(config: ScreenPilotConfig | None = None) -> FastAPI:
    """Create the FastAPI application."""
    cfg = config or ScreenPilotConfig()

    app = FastAPI(
        title="ScreenPilot API",
        description="AI-powered desktop automation API",
        version=__version__,
    )

    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    # Serve static dashboard
    static_dir = Path(__file__).parent / "static"
    if static_dir.exists():
        app.mount("/static", StaticFiles(directory=str(static_dir)), name="static")

    # State
    agent = ScreenPilotAgent(cfg)
    capture = ScreenCapture(cfg.capture)
    template_registry = TemplateRegistry()
    scheduler = TaskScheduler()
    report_generator = ReportGenerator()
    running_tasks: dict[str, dict[str, Any]] = {}
    ws_clients: list[WebSocket] = []

    async def broadcast_ws(message: dict) -> None:
        """Broadcast a message to all WebSocket clients."""
        disconnected = []
        for ws in ws_clients:
            try:
                await ws.send_json(message)
            except Exception:
                disconnected.append(ws)
        for ws in disconnected:
            ws_clients.remove(ws)

    @app.get("/")
    async def root():
        """Serve the web dashboard."""
        index_path = static_dir / "index.html"
        if index_path.exists():
            return HTMLResponse(index_path.read_text())
        return {
            "name": "ScreenPilot API",
            "version": __version__,
            "status": "running",
        }

    @app.get("/api")
    async def api_info():
        return {
            "name": "ScreenPilot API",
            "version": __version__,
            "status": "running",
        }

    @app.get("/health")
    async def health():
        return {"status": "ok"}

    @app.post("/screenshot")
    async def take_screenshot():
        """Take a screenshot and return as base64."""
        ss = capture.capture()
        return {
            "width": ss.width,
            "height": ss.height,
            "timestamp": ss.timestamp,
            "image": ss.to_base64(),
        }

    @app.post("/analyze")
    async def analyze_screen():
        """Analyze the current screen state."""
        from screenpilot.vision.analyzer import ScreenAnalyzer

        ss = capture.capture()
        analyzer = ScreenAnalyzer(cfg.llm)
        state = analyzer.analyze(ss)
        return {
            "description": state.description,
            "active_window": state.active_window,
            "elements": [
                {
                    "label": el.label,
                    "element_type": el.element_type,
                    "x": el.x,
                    "y": el.y,
                    "width": el.width,
                    "height": el.height,
                    "text": el.text,
                }
                for el in state.elements
            ],
        }

    @app.post("/find")
    async def find_element(req: FindElementRequest):
        """Find a UI element by description."""
        from screenpilot.vision.analyzer import ScreenAnalyzer

        ss = capture.capture()
        analyzer = ScreenAnalyzer(cfg.llm)
        element = analyzer.find_element(ss, req.target)

        if element is None:
            raise HTTPException(status_code=404, detail="Element not found")

        return {
            "label": element.label,
            "element_type": element.element_type,
            "x": element.x,
            "y": element.y,
            "width": element.width,
            "height": element.height,
            "confidence": element.confidence,
        }

    @app.post("/action")
    async def execute_action(req: ActionRequest):
        """Execute a single action."""
        action = Action(
            action_type=ActionType(req.action_type),
            target=req.target,
            x=req.x,
            y=req.y,
            text=req.text,
            keys=req.keys,
            direction=req.direction,
            amount=req.amount,
        )
        result = agent.run_action(action)
        return {
            "success": result.success,
            "error": result.error,
            "duration": result.duration,
        }

    @app.post("/task", response_model=TaskStatus)
    async def start_task(req: TaskRequest):
        """Start an automation task (runs in background)."""
        task_id = str(uuid.uuid4())[:8]
        task_info = {
            "id": task_id,
            "goal": req.goal,
            "status": "running",
            "current_step": 0,
            "start_time": time.time(),
            "result": None,
        }
        running_tasks[task_id] = task_info

        async def run_task():
            def on_step(step: StepResult):
                task_info["current_step"] = step.step_number
                asyncio.get_event_loop().call_soon_threadsafe(
                    asyncio.ensure_future,
                    broadcast_ws(
                        {
                            "type": "step",
                            "task_id": task_id,
                            "step": step.step_number,
                            "action": step.action.action_type.value,
                            "success": step.action_result.success,
                            "reasoning": step.action.reasoning,
                        }
                    ),
                )

            agent.on_step(on_step)
            loop = asyncio.get_event_loop()
            result = await loop.run_in_executor(None, agent.run, req.goal, req.max_steps)
            task_info["status"] = "completed" if result.success else "failed"
            task_info["result"] = result
            await broadcast_ws(
                {
                    "type": "task_complete",
                    "task_id": task_id,
                    "success": result.success,
                    "steps": result.num_steps,
                    "time": result.total_time,
                }
            )

        asyncio.create_task(run_task())

        return TaskStatus(
            task_id=task_id,
            goal=req.goal,
            status="running",
            current_step=0,
            total_time=0,
        )

    @app.get("/task/{task_id}", response_model=TaskStatus)
    async def get_task(task_id: str):
        """Get the status of a running task."""
        if task_id not in running_tasks:
            raise HTTPException(status_code=404, detail="Task not found")

        info = running_tasks[task_id]
        return TaskStatus(
            task_id=info["id"],
            goal=info["goal"],
            status=info["status"],
            current_step=info["current_step"],
            total_time=time.time() - info["start_time"],
            error=info["result"].error if info.get("result") else None,
        )

    @app.post("/task/{task_id}/stop")
    async def stop_task(task_id: str):
        """Stop a running task."""
        if task_id not in running_tasks:
            raise HTTPException(status_code=404, detail="Task not found")
        agent.stop()
        running_tasks[task_id]["status"] = "stopped"
        return {"status": "stopped"}

    @app.get("/tasks")
    async def list_tasks():
        """List all tasks."""
        return [
            TaskStatus(
                task_id=info["id"],
                goal=info["goal"],
                status=info["status"],
                current_step=info["current_step"],
                total_time=time.time() - info["start_time"],
            )
            for info in running_tasks.values()
        ]

    @app.get("/templates")
    async def list_templates():
        """List all available workflow templates."""
        return [t.to_dict() for t in template_registry.list_all()]

    @app.get("/templates/{template_id}")
    async def get_template(template_id: str):
        """Get a specific template."""
        template = template_registry.get(template_id)
        if template is None:
            raise HTTPException(status_code=404, detail="Template not found")
        return template.to_dict()

    @app.post("/templates/{template_id}/run")
    async def run_template(template_id: str, params: dict):
        """Run a workflow template with given parameters."""
        template = template_registry.get(template_id)
        if template is None:
            raise HTTPException(status_code=404, detail="Template not found")

        errors = template.validate_params(params)
        if errors:
            raise HTTPException(status_code=400, detail={"errors": errors})

        goal = template.render_goal(params)

        # Create and run task
        task_id = str(uuid.uuid4())[:8]
        task_info = {
            "id": task_id,
            "goal": goal,
            "status": "running",
            "current_step": 0,
            "start_time": time.time(),
            "result": None,
            "template_id": template_id,
        }
        running_tasks[task_id] = task_info

        async def run_templated_task():
            loop = asyncio.get_event_loop()
            result = await loop.run_in_executor(None, agent.run, goal, template.estimated_steps * 2)
            task_info["status"] = "completed" if result.success else "failed"
            task_info["result"] = result
            await broadcast_ws(
                {
                    "type": "task_complete",
                    "task_id": task_id,
                    "success": result.success,
                    "steps": result.num_steps,
                    "time": result.total_time,
                }
            )

        asyncio.create_task(run_templated_task())

        return TaskStatus(
            task_id=task_id,
            goal=goal,
            status="running",
            current_step=0,
            total_time=0,
        )

    # --- Scheduling endpoints ---

    @app.get("/schedules")
    async def list_schedules():
        """List all scheduled tasks."""
        return [t.to_dict() for t in scheduler.list_all()]

    @app.post("/schedules")
    async def add_schedule(req: ScheduleRequest):
        """Add a new scheduled task."""
        task = ScheduledTask(
            id=req.id,
            name=req.name,
            goal=req.goal,
            schedule_type=ScheduleType(req.schedule_type),
            max_steps=req.max_steps,
            run_at=req.run_at,
            interval_seconds=req.interval_seconds,
            time_of_day=req.time_of_day,
            day_of_week=req.day_of_week,
            cron_expr=req.cron_expr,
            template_id=req.template_id,
            template_params=req.template_params,
        )
        scheduler.add(task)
        return task.to_dict()

    @app.delete("/schedules/{schedule_id}")
    async def remove_schedule(schedule_id: str):
        """Remove a scheduled task."""
        if not scheduler.remove(schedule_id):
            raise HTTPException(status_code=404, detail="Schedule not found")
        return {"status": "removed"}

    # --- Reporting endpoints ---

    @app.get("/reports")
    async def list_reports():
        """List execution reports."""
        return [r.to_dict() for r in report_generator.reports]

    @app.get("/reports/stats")
    async def report_stats():
        """Get aggregate execution statistics."""
        return report_generator.aggregate_stats()

    @app.websocket("/ws")
    async def websocket_endpoint(ws: WebSocket):
        """WebSocket for real-time task updates."""
        await ws.accept()
        ws_clients.append(ws)
        try:
            while True:
                data = await ws.receive_text()
                # Handle ping/pong
                if data == "ping":
                    await ws.send_text("pong")
        except WebSocketDisconnect:
            if ws in ws_clients:
                ws_clients.remove(ws)

    return app
