"""Tests for plugin system."""

import tempfile
from pathlib import Path

from screenpilot.plugins.base import Plugin, PluginInfo, PluginManager


class SamplePlugin(Plugin):
    """A test plugin for unit tests."""

    def __init__(self):
        self.loaded = False
        self.unloaded = False
        self.tasks_started = []
        self.tasks_completed = []
        self.steps_before = []
        self.steps_after = []
        self.errors = []

    def info(self) -> PluginInfo:
        return PluginInfo(
            name="test-plugin",
            version="1.0.0",
            description="A test plugin",
            author="Test",
        )

    def on_load(self):
        self.loaded = True

    def on_unload(self):
        self.unloaded = True

    def on_task_start(self, goal, config):
        self.tasks_started.append(goal)

    def on_task_complete(self, goal, success, result):
        self.tasks_completed.append((goal, success))

    def on_step_before(self, step_number, action):
        self.steps_before.append(step_number)
        return None

    def on_step_after(self, step_number, action, result):
        self.steps_after.append(step_number)

    def on_error(self, error, context):
        self.errors.append(error)


class ModifyingPlugin(Plugin):
    """Plugin that modifies actions."""

    def info(self) -> PluginInfo:
        return PluginInfo(name="modifier", version="1.0.0", description="Modifies actions")

    def on_step_before(self, step_number, action):
        modified = dict(action)
        modified["modified"] = True
        return modified


def test_register_plugin():
    manager = PluginManager()
    plugin = SamplePlugin()
    manager.register(plugin)
    assert plugin.loaded
    assert len(manager.list_plugins()) == 1
    assert manager.list_plugins()[0].name == "test-plugin"


def test_unregister_plugin():
    manager = PluginManager()
    plugin = SamplePlugin()
    manager.register(plugin)
    assert manager.unregister("test-plugin")
    assert plugin.unloaded
    assert len(manager.list_plugins()) == 0


def test_unregister_nonexistent():
    manager = PluginManager()
    assert not manager.unregister("nonexistent")


def test_get_plugin():
    manager = PluginManager()
    plugin = SamplePlugin()
    manager.register(plugin)
    assert manager.get("test-plugin") is plugin
    assert manager.get("nonexistent") is None


def test_dispatch_task_start():
    manager = PluginManager()
    plugin = SamplePlugin()
    manager.register(plugin)
    manager.dispatch_task_start("open chrome", {})
    assert "open chrome" in plugin.tasks_started


def test_dispatch_task_complete():
    manager = PluginManager()
    plugin = SamplePlugin()
    manager.register(plugin)
    manager.dispatch_task_complete("open chrome", True, {"steps": 5})
    assert ("open chrome", True) in plugin.tasks_completed


def test_dispatch_step_hooks():
    manager = PluginManager()
    plugin = SamplePlugin()
    manager.register(plugin)
    manager.dispatch_step_before(1, {"action_type": "click"})
    manager.dispatch_step_after(1, {"action_type": "click"}, {"success": True})
    assert 1 in plugin.steps_before
    assert 1 in plugin.steps_after


def test_dispatch_error():
    manager = PluginManager()
    plugin = SamplePlugin()
    manager.register(plugin)
    manager.dispatch_error("timeout", {"action": "click"})
    assert "timeout" in plugin.errors


def test_step_before_modification():
    manager = PluginManager()
    manager.register(ModifyingPlugin())
    result = manager.dispatch_step_before(1, {"action_type": "click"})
    assert result.get("modified") is True


def test_multiple_plugins():
    manager = PluginManager()
    p1 = SamplePlugin()
    p2 = ModifyingPlugin()
    manager.register(p1)
    manager.register(p2)
    assert len(manager.list_plugins()) == 2


def test_plugin_error_handling():
    """Plugins that raise errors should not crash the manager."""

    class BadPlugin(Plugin):
        def info(self):
            return PluginInfo(name="bad", version="0", description="Bad plugin")

        def on_task_start(self, goal, config):
            raise RuntimeError("Plugin crash!")

    manager = PluginManager()
    manager.register(BadPlugin())
    # Should not raise
    manager.dispatch_task_start("test", {})


def test_load_from_directory():
    with tempfile.TemporaryDirectory() as tmpdir:
        # Create a valid plugin file
        plugin_file = Path(tmpdir) / "my_plugin.py"
        plugin_file.write_text("""
from screenpilot.plugins.base import Plugin, PluginInfo

class MyPlugin(Plugin):
    def info(self):
        return PluginInfo(name="my-dynamic", version="1.0", description="Dynamic")

def create_plugin():
    return MyPlugin()
""")
        manager = PluginManager()
        loaded = manager.load_from_directory(tmpdir)
        assert loaded == 1
        assert manager.get("my-dynamic") is not None


def test_load_from_nonexistent_directory():
    manager = PluginManager()
    loaded = manager.load_from_directory("/nonexistent/path")
    assert loaded == 0
