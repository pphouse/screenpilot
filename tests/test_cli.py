"""Tests for CLI commands."""

import os
import sys

os.environ.setdefault("DISPLAY", ":99")

from unittest.mock import MagicMock

sys.modules.setdefault("pyautogui", MagicMock())
sys.modules.setdefault("pynput", MagicMock())
sys.modules.setdefault("pynput.mouse", MagicMock())
sys.modules.setdefault("pynput.keyboard", MagicMock())
sys.modules.setdefault("mss", MagicMock())

from click.testing import CliRunner

from screenpilot.cli import cli


def test_cli_help():
    runner = CliRunner()
    result = runner.invoke(cli, ["--help"])
    assert result.exit_code == 0
    assert "ScreenPilot" in result.output


def test_cli_version():
    runner = CliRunner()
    result = runner.invoke(cli, ["--version"])
    assert result.exit_code == 0
    assert "0.1.0" in result.output


def test_templates_command():
    runner = CliRunner()
    result = runner.invoke(cli, ["templates"])
    assert result.exit_code == 0
    assert "web_form_fill" in result.output
    assert "Fill Web Form" in result.output


def test_schedule_list_empty():
    runner = CliRunner()
    result = runner.invoke(cli, ["schedule", "list"])
    assert result.exit_code == 0
    assert "No scheduled tasks" in result.output


def test_schedule_help():
    runner = CliRunner()
    result = runner.invoke(cli, ["schedule", "--help"])
    assert result.exit_code == 0
    assert "Manage scheduled tasks" in result.output
