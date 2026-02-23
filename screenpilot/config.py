"""Configuration management for ScreenPilot."""

from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Literal


@dataclass
class LLMConfig:
    """LLM provider configuration."""

    provider: Literal["anthropic", "openai", "azure", "gemini", "claude_code", "litellm"] = "anthropic"
    model: str = "claude-sonnet-4-5-20250929"
    api_key: str | None = None
    base_url: str | None = None
    max_tokens: int = 4096
    temperature: float | None = 0.0
    # Azure-specific
    azure_endpoint: str | None = None
    azure_api_version: str = "2024-12-01-preview"
    azure_deployment: str | None = None

    def __post_init__(self):
        if self.api_key is None:
            env_map = {
                "anthropic": "ANTHROPIC_API_KEY",
                "openai": "OPENAI_API_KEY",
                "azure": "AZURE_OPENAI_API_KEY",
                "gemini": "GEMINI_API_KEY",
            }
            env_var = env_map.get(self.provider, "LITELLM_API_KEY")
            self.api_key = os.environ.get(env_var, "")


@dataclass
class CaptureConfig:
    """Screen capture configuration."""

    monitor: int = 0  # 0 = primary monitor
    scale_factor: float = 1.0
    max_width: int = 1920
    max_height: int = 1080
    format: Literal["png", "jpeg"] = "png"
    jpeg_quality: int = 85


@dataclass
class ExecutorConfig:
    """Action executor configuration."""

    click_delay: float = 0.1
    type_delay: float = 0.02
    action_timeout: float = 30.0
    screenshot_after_action: bool = True
    safe_mode: bool = True  # Require confirmation for destructive actions


@dataclass
class RecorderConfig:
    """Workflow recorder configuration."""

    capture_interval: float = 0.5
    capture_on_click: bool = True
    capture_on_key: bool = True
    save_dir: str = "~/.screenpilot/recordings"
    max_screenshots: int = 1000


@dataclass
class ScreenPilotConfig:
    """Main configuration."""

    llm: LLMConfig = field(default_factory=LLMConfig)
    capture: CaptureConfig = field(default_factory=CaptureConfig)
    executor: ExecutorConfig = field(default_factory=ExecutorConfig)
    recorder: RecorderConfig = field(default_factory=RecorderConfig)
    log_dir: str = "~/.screenpilot/logs"
    verbose: bool = False

    @classmethod
    def from_file(cls, path: str | Path) -> ScreenPilotConfig:
        """Load configuration from a JSON file."""
        path = Path(path)
        if not path.exists():
            return cls()
        with open(path) as f:
            data = json.load(f)
        return cls(
            llm=LLMConfig(**data.get("llm", {})),
            capture=CaptureConfig(**data.get("capture", {})),
            executor=ExecutorConfig(**data.get("executor", {})),
            recorder=RecorderConfig(**data.get("recorder", {})),
            log_dir=data.get("log_dir", "~/.screenpilot/logs"),
            verbose=data.get("verbose", False),
        )

    def to_file(self, path: str | Path) -> None:
        """Save configuration to a JSON file."""
        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        from dataclasses import asdict

        with open(path, "w") as f:
            json.dump(asdict(self), f, indent=2)
