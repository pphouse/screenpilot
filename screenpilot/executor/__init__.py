"""Action execution engine for desktop automation."""


def __getattr__(name):
    if name == "ActionExecutor":
        from screenpilot.executor.executor import ActionExecutor

        return ActionExecutor
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")


__all__ = ["ActionExecutor"]
