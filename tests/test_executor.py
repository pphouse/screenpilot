"""Tests for the executor module (mocked pyautogui)."""

import os
import sys
from unittest.mock import MagicMock, patch

# Ensure DISPLAY is set for pyautogui import on headless systems
if "DISPLAY" not in os.environ:
    os.environ["DISPLAY"] = ":99"

# Mock pyautogui at module level to prevent X11 errors on headless
mock_pyautogui = MagicMock()
mock_pyautogui.FAILSAFE = True
mock_pyautogui.PAUSE = 0.05
sys.modules.setdefault("pyautogui", mock_pyautogui)

from screenpilot.executor.executor import ActionExecutor
from screenpilot.planner.planner import Action, ActionType


@patch("screenpilot.executor.executor.pyautogui")
def test_click(mock_pag):
    executor = ActionExecutor()
    action = Action(action_type=ActionType.CLICK, x=100, y=200)
    result = executor.execute(action)
    assert result.success
    mock_pag.click.assert_called_once_with(100, 200)


@patch("screenpilot.executor.executor.pyautogui")
def test_click_missing_coords(mock_pag):
    executor = ActionExecutor()
    action = Action(action_type=ActionType.CLICK)
    result = executor.execute(action)
    assert not result.success
    assert "coordinates" in result.error


@patch("screenpilot.executor.executor.pyautogui")
def test_type(mock_pag):
    executor = ActionExecutor()
    action = Action(action_type=ActionType.TYPE, text="hello world")
    result = executor.execute(action)
    assert result.success
    mock_pag.write.assert_called_once()


@patch("screenpilot.executor.executor.pyautogui")
def test_key(mock_pag):
    executor = ActionExecutor()
    action = Action(action_type=ActionType.KEY, keys="ctrl+c")
    result = executor.execute(action)
    assert result.success
    mock_pag.hotkey.assert_called_once_with("ctrl", "c")


@patch("screenpilot.executor.executor.pyautogui")
def test_single_key(mock_pag):
    executor = ActionExecutor()
    action = Action(action_type=ActionType.KEY, keys="enter")
    result = executor.execute(action)
    assert result.success
    mock_pag.press.assert_called_once_with("enter")


@patch("screenpilot.executor.executor.pyautogui")
def test_scroll_down(mock_pag):
    executor = ActionExecutor()
    action = Action(action_type=ActionType.SCROLL, direction="down", amount=5)
    result = executor.execute(action)
    assert result.success
    mock_pag.scroll.assert_called_once_with(-5)


@patch("screenpilot.executor.executor.pyautogui")
def test_scroll_up(mock_pag):
    executor = ActionExecutor()
    action = Action(action_type=ActionType.SCROLL, direction="up", amount=3)
    result = executor.execute(action)
    assert result.success
    mock_pag.scroll.assert_called_once_with(3)


@patch("screenpilot.executor.executor.pyautogui")
def test_done_action(mock_pag):
    executor = ActionExecutor()
    action = Action(action_type=ActionType.DONE)
    result = executor.execute(action)
    assert result.success


@patch("screenpilot.executor.executor.pyautogui")
def test_fail_action(mock_pag):
    executor = ActionExecutor()
    action = Action(action_type=ActionType.FAIL, reasoning="Cannot find element")
    result = executor.execute(action)
    assert not result.success


@patch("screenpilot.executor.executor.pyautogui")
def test_action_log(mock_pag):
    executor = ActionExecutor()
    executor.execute(Action(action_type=ActionType.CLICK, x=10, y=20))
    executor.execute(Action(action_type=ActionType.TYPE, text="test"))
    assert len(executor.action_log) == 2
    executor.clear_log()
    assert len(executor.action_log) == 0


@patch("screenpilot.executor.executor.pyautogui")
def test_double_click(mock_pag):
    executor = ActionExecutor()
    action = Action(action_type=ActionType.DOUBLE_CLICK, x=150, y=250)
    result = executor.execute(action)
    assert result.success
    mock_pag.doubleClick.assert_called_once_with(150, 250)


@patch("screenpilot.executor.executor.pyautogui")
def test_wait(mock_pag):
    executor = ActionExecutor()
    action = Action(action_type=ActionType.WAIT, duration=0.01)
    result = executor.execute(action)
    assert result.success
