"""Tests for configuration module."""

import tempfile
from pathlib import Path

from screenpilot.config import (
    CaptureConfig,
    ExecutorConfig,
    LLMConfig,
    RecorderConfig,
    ScreenPilotConfig,
)


def test_default_config():
    config = ScreenPilotConfig()
    assert config.llm.provider == "anthropic"
    assert config.llm.model == "claude-sonnet-4-5-20250929"
    assert config.capture.max_width == 1920
    assert config.executor.safe_mode is True
    assert config.verbose is False


def test_llm_config_defaults():
    config = LLMConfig()
    assert config.provider == "anthropic"
    assert config.max_tokens == 4096
    assert config.temperature == 0.0


def test_config_save_load():
    config = ScreenPilotConfig(
        llm=LLMConfig(provider="openai", model="gpt-4o"),
        capture=CaptureConfig(max_width=1280),
        verbose=True,
    )

    with tempfile.NamedTemporaryFile(suffix=".json", delete=False) as f:
        path = f.name

    config.to_file(path)
    loaded = ScreenPilotConfig.from_file(path)

    assert loaded.llm.provider == "openai"
    assert loaded.llm.model == "gpt-4o"
    assert loaded.capture.max_width == 1280
    assert loaded.verbose is True

    Path(path).unlink()


def test_config_from_missing_file():
    config = ScreenPilotConfig.from_file("/nonexistent/path.json")
    assert config.llm.provider == "anthropic"


def test_executor_config():
    config = ExecutorConfig(click_delay=0.5, safe_mode=False)
    assert config.click_delay == 0.5
    assert config.safe_mode is False


def test_recorder_config():
    config = RecorderConfig(capture_interval=1.0, max_screenshots=500)
    assert config.capture_interval == 1.0
    assert config.max_screenshots == 500
