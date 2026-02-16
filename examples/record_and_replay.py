"""Example: Record a workflow and replay it."""

import time

from screenpilot.config import LLMConfig, RecorderConfig, ScreenPilotConfig
from screenpilot.recorder.recorder import Workflow, WorkflowRecorder
from screenpilot.recorder.replay import WorkflowReplayer


def record_example():
    """Record a workflow interactively."""
    config = RecorderConfig(save_dir="~/.screenpilot/recordings")
    recorder = WorkflowRecorder(config)

    print("Recording started. Perform your actions...")
    print("Press Ctrl+C to stop recording.\n")

    recorder.start("example-workflow", "Example automated workflow")

    try:
        while True:
            time.sleep(0.5)
            if recorder.is_recording:
                print(f"\r  Events captured: {len(recorder._workflow.events)}", end="", flush=True)
    except KeyboardInterrupt:
        workflow = recorder.stop()
        print(f"\n\nRecorded {len(workflow.events)} events")
        print(f"Saved to: ~/.screenpilot/recordings/example-workflow/workflow.json")
        return workflow


def replay_example(workflow_path: str):
    """Replay a recorded workflow with adaptive vision."""
    workflow = Workflow.load(workflow_path)
    print(f"Loaded workflow: {workflow.name} ({len(workflow.events)} events)")

    config = ScreenPilotConfig(
        llm=LLMConfig(provider="anthropic", model="claude-sonnet-4-5-20250929")
    )

    replayer = WorkflowReplayer(
        llm_config=config.llm,
        adaptive=True,  # Use vision to adapt to UI changes
    )

    results = replayer.replay(workflow, speed=1.0)

    success = sum(1 for r in results if r.success)
    print(f"\nReplay complete: {success}/{len(results)} actions succeeded")


if __name__ == "__main__":
    import sys

    if len(sys.argv) > 1 and sys.argv[1] == "replay":
        path = sys.argv[2] if len(sys.argv) > 2 else "~/.screenpilot/recordings/example-workflow/workflow.json"
        replay_example(path)
    else:
        record_example()
