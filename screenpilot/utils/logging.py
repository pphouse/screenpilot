"""Logging configuration for ScreenPilot."""

from __future__ import annotations

import logging
import sys
from pathlib import Path


def setup_logging(verbose: bool = False, log_dir: str | None = None) -> None:
    """Configure logging for ScreenPilot."""
    level = logging.DEBUG if verbose else logging.INFO

    formatter = logging.Formatter(
        "%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )

    # Console handler
    console = logging.StreamHandler(sys.stderr)
    console.setLevel(level)
    console.setFormatter(formatter)

    # Root logger
    root = logging.getLogger("screenpilot")
    root.setLevel(level)
    root.addHandler(console)

    # File handler
    if log_dir:
        log_path = Path(log_dir).expanduser()
        log_path.mkdir(parents=True, exist_ok=True)
        file_handler = logging.FileHandler(log_path / "screenpilot.log")
        file_handler.setLevel(logging.DEBUG)
        file_handler.setFormatter(formatter)
        root.addHandler(file_handler)
