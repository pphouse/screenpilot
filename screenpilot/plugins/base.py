"""Plugin system for extending ScreenPilot.

Allows users to add custom action types, pre/post action hooks,
custom LLM providers, and notification integrations without
modifying the core codebase.
"""

from __future__ import annotations

import importlib
import logging
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from pathlib import Path

logger = logging.getLogger(__name__)


@dataclass
class PluginInfo:
    """Metadata about a plugin."""

    name: str
    version: str
    description: str
    author: str = ""
    hooks: list[str] = field(default_factory=list)


class Plugin(ABC):
    """Base class for ScreenPilot plugins.

    Plugins can hook into several lifecycle events:
    - on_task_start: Called when a task begins
    - on_task_complete: Called when a task finishes
    - on_step_before: Called before each action step
    - on_step_after: Called after each action step
    - on_error: Called when an error occurs
    - on_screenshot: Called when a screenshot is taken
    """

    @abstractmethod
    def info(self) -> PluginInfo:
        """Return plugin metadata."""

    def on_load(self) -> None:
        """Called when the plugin is loaded."""

    def on_unload(self) -> None:
        """Called when the plugin is unloaded."""

    def on_task_start(self, goal: str, config: dict) -> None:
        """Called when a task starts."""

    def on_task_complete(self, goal: str, success: bool, result: dict) -> None:
        """Called when a task completes."""

    def on_step_before(self, step_number: int, action: dict) -> dict | None:
        """Called before each step. Return modified action or None."""
        return None

    def on_step_after(self, step_number: int, action: dict, result: dict) -> None:
        """Called after each step."""

    def on_error(self, error: str, context: dict) -> None:
        """Called when an error occurs."""

    def on_screenshot(self, screenshot_data: dict) -> None:
        """Called when a screenshot is taken."""


class PluginManager:
    """Manages plugin lifecycle and hook dispatch."""

    def __init__(self):
        self._plugins: dict[str, Plugin] = {}

    def register(self, plugin: Plugin) -> None:
        """Register a plugin."""
        info = plugin.info()
        self._plugins[info.name] = plugin
        plugin.on_load()
        logger.info("Plugin loaded: %s v%s", info.name, info.version)

    def unregister(self, name: str) -> bool:
        """Unregister a plugin."""
        plugin = self._plugins.pop(name, None)
        if plugin:
            plugin.on_unload()
            logger.info("Plugin unloaded: %s", name)
            return True
        return False

    def get(self, name: str) -> Plugin | None:
        """Get a plugin by name."""
        return self._plugins.get(name)

    def list_plugins(self) -> list[PluginInfo]:
        """List all registered plugins."""
        return [p.info() for p in self._plugins.values()]

    def load_from_directory(self, directory: str | Path) -> int:
        """Load plugins from a directory of Python files.

        Each file should contain a `create_plugin()` function
        that returns a Plugin instance.
        """
        directory = Path(directory)
        if not directory.exists():
            return 0

        loaded = 0
        for py_file in sorted(directory.glob("*.py")):
            if py_file.name.startswith("_"):
                continue
            try:
                spec = importlib.util.spec_from_file_location(py_file.stem, py_file)
                if spec and spec.loader:
                    module = importlib.util.module_from_spec(spec)
                    spec.loader.exec_module(module)
                    if hasattr(module, "create_plugin"):
                        plugin = module.create_plugin()
                        self.register(plugin)
                        loaded += 1
            except Exception as e:
                logger.error("Failed to load plugin from %s: %s", py_file, e)

        return loaded

    # Hook dispatchers

    def dispatch_task_start(self, goal: str, config: dict) -> None:
        """Dispatch on_task_start to all plugins."""
        for plugin in self._plugins.values():
            try:
                plugin.on_task_start(goal, config)
            except Exception as e:
                logger.error("Plugin error in on_task_start: %s", e)

    def dispatch_task_complete(self, goal: str, success: bool, result: dict) -> None:
        """Dispatch on_task_complete to all plugins."""
        for plugin in self._plugins.values():
            try:
                plugin.on_task_complete(goal, success, result)
            except Exception as e:
                logger.error("Plugin error in on_task_complete: %s", e)

    def dispatch_step_before(self, step_number: int, action: dict) -> dict:
        """Dispatch on_step_before. Returns potentially modified action."""
        current = action
        for plugin in self._plugins.values():
            try:
                modified = plugin.on_step_before(step_number, current)
                if modified is not None:
                    current = modified
            except Exception as e:
                logger.error("Plugin error in on_step_before: %s", e)
        return current

    def dispatch_step_after(self, step_number: int, action: dict, result: dict) -> None:
        """Dispatch on_step_after to all plugins."""
        for plugin in self._plugins.values():
            try:
                plugin.on_step_after(step_number, action, result)
            except Exception as e:
                logger.error("Plugin error in on_step_after: %s", e)

    def dispatch_error(self, error: str, context: dict) -> None:
        """Dispatch on_error to all plugins."""
        for plugin in self._plugins.values():
            try:
                plugin.on_error(error, context)
            except Exception as e:
                logger.error("Plugin error in on_error: %s", e)

    def dispatch_screenshot(self, screenshot_data: dict) -> None:
        """Dispatch on_screenshot to all plugins."""
        for plugin in self._plugins.values():
            try:
                plugin.on_screenshot(screenshot_data)
            except Exception as e:
                logger.error("Plugin error in on_screenshot: %s", e)
