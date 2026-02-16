"""Command-line interface for ScreenPilot."""

from __future__ import annotations

import sys

import click
from rich.console import Console
from rich.panel import Panel
from rich.table import Table

from screenpilot import __version__
from screenpilot.agent import ScreenPilotAgent, StepResult
from screenpilot.config import ScreenPilotConfig
from screenpilot.utils.logging import setup_logging

console = Console()


@click.group()
@click.version_option(__version__)
@click.option("--config", "-c", default=None, help="Path to config file")
@click.option("--verbose", "-v", is_flag=True, help="Enable verbose logging")
@click.pass_context
def cli(ctx: click.Context, config: str | None, verbose: bool) -> None:
    """ScreenPilot - AI-powered desktop automation."""
    ctx.ensure_object(dict)
    if config:
        ctx.obj["config"] = ScreenPilotConfig.from_file(config)
    else:
        ctx.obj["config"] = ScreenPilotConfig()
    ctx.obj["config"].verbose = verbose
    setup_logging(verbose=verbose, log_dir=ctx.obj["config"].log_dir)


@cli.command()
@click.argument("goal")
@click.option("--max-steps", "-n", default=50, help="Maximum number of steps")
@click.option("--provider", "-p", default=None, help="LLM provider (anthropic/openai/litellm)")
@click.option("--model", "-m", default=None, help="Model name")
@click.pass_context
def run(
    ctx: click.Context, goal: str, max_steps: int, provider: str | None, model: str | None
) -> None:
    """Run an automation task.

    Example: screenpilot run "Open Chrome and search for Python tutorials"
    """
    cfg: ScreenPilotConfig = ctx.obj["config"]
    if provider:
        cfg.llm.provider = provider
    if model:
        cfg.llm.model = model

    agent = ScreenPilotAgent(cfg)

    console.print(Panel(f"[bold blue]Goal:[/] {goal}", title="ScreenPilot"))
    console.print(f"[dim]Provider: {cfg.llm.provider} | Model: {cfg.llm.model}[/]")
    console.print()

    step_table = Table(title="Execution Log")
    step_table.add_column("#", style="dim", width=4)
    step_table.add_column("Action", style="cyan")
    step_table.add_column("Target", style="green")
    step_table.add_column("Status", style="bold")
    step_table.add_column("Reasoning", max_width=50)

    def on_step(step: StepResult) -> None:
        status = "[green]OK[/]" if step.action_result.success else "[red]FAIL[/]"
        target = step.action.target or ""
        if step.action.x is not None:
            target += f" ({step.action.x}, {step.action.y})"
        reasoning = (
            step.action.reasoning[:50] + "..."
            if len(step.action.reasoning) > 50
            else step.action.reasoning
        )
        step_table.add_row(
            str(step.step_number),
            step.action.action_type.value,
            target,
            status,
            reasoning,
        )
        console.print(step_table)

    agent.on_step(on_step)

    try:
        result = agent.run(goal, max_steps=max_steps)
    except KeyboardInterrupt:
        agent.stop()
        console.print("\n[yellow]Stopped by user.[/]")
        return

    # Print result
    if result.success:
        console.print(
            Panel(
                f"[green bold]Task completed successfully![/]\n"
                f"Steps: {result.num_steps} | Time: {result.total_time:.1f}s",
                title="Result",
            )
        )
    else:
        console.print(
            Panel(
                f"[red bold]Task failed.[/]\n"
                f"Error: {result.error}\n"
                f"Steps: {result.num_steps} | Time: {result.total_time:.1f}s",
                title="Result",
            )
        )
        sys.exit(1)


@cli.command()
@click.pass_context
def screenshot(ctx: click.Context) -> None:
    """Take a screenshot and analyze it."""
    from screenpilot.vision import ScreenAnalyzer, ScreenCapture

    cfg: ScreenPilotConfig = ctx.obj["config"]

    console.print("[dim]Capturing screenshot...[/]")
    capture = ScreenCapture(cfg.capture)
    ss = capture.capture()
    ss.save("screenshot.png")
    console.print(f"[green]Screenshot saved:[/] screenshot.png ({ss.width}x{ss.height})")

    console.print("[dim]Analyzing with LLM...[/]")
    analyzer = ScreenAnalyzer(cfg.llm)
    state = analyzer.analyze(ss)

    console.print(f"\n[bold]Description:[/] {state.description}")
    if state.active_window:
        console.print(f"[bold]Active Window:[/] {state.active_window}")

    if state.elements:
        table = Table(title="UI Elements")
        table.add_column("Label", style="cyan")
        table.add_column("Type", style="green")
        table.add_column("Position")
        table.add_column("Text")

        for el in state.elements[:20]:
            table.add_row(
                el.label,
                el.element_type,
                f"({el.x}, {el.y})",
                el.text or "",
            )
        console.print(table)


@cli.command()
@click.argument("target")
@click.pass_context
def find(ctx: click.Context, target: str) -> None:
    """Find a UI element on screen by description.

    Example: screenpilot find "the search bar"
    """
    from screenpilot.vision import ScreenAnalyzer, ScreenCapture

    cfg: ScreenPilotConfig = ctx.obj["config"]

    capture = ScreenCapture(cfg.capture)
    analyzer = ScreenAnalyzer(cfg.llm)

    console.print(f"[dim]Looking for: {target}[/]")
    ss = capture.capture()
    element = analyzer.find_element(ss, target)

    if element:
        console.print(
            Panel(
                f"[green bold]Found![/]\n"
                f"Label: {element.label}\n"
                f"Type: {element.element_type}\n"
                f"Position: ({element.x}, {element.y})\n"
                f"Confidence: {element.confidence:.0%}",
                title="Element",
            )
        )
    else:
        console.print("[red]Element not found.[/]")


@cli.command()
@click.argument("name")
@click.option("--description", "-d", default="", help="Workflow description")
@click.pass_context
def record(ctx: click.Context, name: str, description: str) -> None:
    """Record a workflow.

    Example: screenpilot record "login-flow" -d "Login to the app"
    """
    from screenpilot.recorder import WorkflowRecorder

    cfg: ScreenPilotConfig = ctx.obj["config"]
    recorder = WorkflowRecorder(cfg.recorder)

    console.print(
        Panel(
            f"Recording workflow: [bold]{name}[/]\nPress [bold red]Ctrl+C[/] to stop recording.",
            title="Recorder",
        )
    )

    recorder.start(name, description)

    try:
        while True:
            import time

            time.sleep(0.5)
    except KeyboardInterrupt:
        workflow = recorder.stop()
        if workflow:
            console.print(
                f"\n[green]Recorded {len(workflow.events)} events ({workflow.duration:.1f}s)[/]"
            )


@cli.command()
@click.argument("workflow_path")
@click.option("--speed", "-s", default=1.0, help="Replay speed multiplier")
@click.option("--adaptive/--exact", default=True, help="Use vision-based adaptive replay")
@click.pass_context
def replay(ctx: click.Context, workflow_path: str, speed: float, adaptive: bool) -> None:
    """Replay a recorded workflow.

    Example: screenpilot replay ~/.screenpilot/recordings/login-flow/workflow.json
    """
    from screenpilot.recorder.recorder import Workflow
    from screenpilot.recorder.replay import WorkflowReplayer

    cfg: ScreenPilotConfig = ctx.obj["config"]

    workflow = Workflow.load(workflow_path)
    console.print(f"[dim]Loaded workflow: {workflow.name} ({len(workflow.events)} events)[/]")

    replayer = WorkflowReplayer(
        llm_config=cfg.llm if adaptive else None,
        executor_config=cfg.executor,
        adaptive=adaptive,
    )

    try:
        results = replayer.replay(workflow, speed=speed)
        success = sum(1 for r in results if r.success)
        console.print(f"\n[green]Replay complete: {success}/{len(results)} actions succeeded[/]")
    except KeyboardInterrupt:
        replayer.stop()
        console.print("\n[yellow]Replay stopped.[/]")


@cli.command()
@click.option("--host", default="0.0.0.0", help="Server host")
@click.option("--port", default=8420, help="Server port")
@click.pass_context
def serve(ctx: click.Context, host: str, port: int) -> None:
    """Start the ScreenPilot API server.

    Example: screenpilot serve --port 8420
    """
    import uvicorn

    from screenpilot.api.server import create_app

    cfg: ScreenPilotConfig = ctx.obj["config"]
    app = create_app(cfg)

    console.print(
        Panel(
            f"[bold green]ScreenPilot API Server[/]\n"
            f"URL: http://{host}:{port}\n"
            f"Docs: http://{host}:{port}/docs",
            title="Server",
        )
    )

    uvicorn.run(app, host=host, port=port)


def main():
    """Entry point."""
    cli()


if __name__ == "__main__":
    main()
