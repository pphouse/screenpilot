"""Workflow recording and replay."""


def __getattr__(name):
    if name == "WorkflowRecorder":
        from screenpilot.recorder.recorder import WorkflowRecorder

        return WorkflowRecorder
    if name == "WorkflowReplayer":
        from screenpilot.recorder.replay import WorkflowReplayer

        return WorkflowReplayer
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")


__all__ = ["WorkflowRecorder", "WorkflowReplayer"]
