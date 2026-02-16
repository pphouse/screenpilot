"""Pytest configuration for headless testing."""

import os
import sys
from unittest.mock import MagicMock

# Set DISPLAY for headless environments
if "DISPLAY" not in os.environ:
    os.environ["DISPLAY"] = ":99"

# Pre-mock modules that require X11/display
for mod_name in ["pyautogui", "pynput", "pynput.keyboard", "pynput.mouse"]:
    if mod_name not in sys.modules:
        sys.modules[mod_name] = MagicMock()
