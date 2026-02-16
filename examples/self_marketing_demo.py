#!/usr/bin/env python3
"""
ScreenPilot Self-Marketing Demo
================================
This script uses ScreenPilot's own automation capabilities to demonstrate
the tool by navigating to its own GitHub repository and landing page.

"The best marketing for an automation tool is using it to automate its own marketing."

Usage:
    # Requires a display (Xvfb or real) and Google Chrome
    export DISPLAY=:99  # if using Xvfb
    python examples/self_marketing_demo.py
"""

import os
import sys
import time

# Ensure display is set
if not os.environ.get("DISPLAY"):
    os.environ["DISPLAY"] = ":99"

import pyautogui
import mss
from mss.tools import to_png
from pathlib import Path

# ScreenPilot-style configuration
pyautogui.FAILSAFE = False
pyautogui.PAUSE = 0.3

OUTPUT_DIR = Path("screenshots/marketing")
OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

SCREEN_WIDTH = 1920
SCREEN_HEIGHT = 1080


def screenshot(name: str) -> str:
    """Capture screenshot and save with name."""
    path = str(OUTPUT_DIR / f"{name}.png")
    with mss.mss() as sct:
        shot = sct.grab(sct.monitors[0])
        to_png(shot.rgb, shot.size, output=path)
    print(f"  [screenshot] {path} ({shot.width}x{shot.height})")
    return path


def step(num: int, action: str, target: str, status: str = "OK"):
    """Print ScreenPilot-style step output."""
    color = "\033[92m" if status == "OK" else "\033[91m"
    reset = "\033[0m"
    print(f"Step {num} \033[1m{action}\033[0m \"{target}\" {color}{status}{reset}")


def navigate_to(url: str):
    """Navigate browser to URL using keyboard shortcut."""
    pyautogui.hotkey("ctrl", "l")
    time.sleep(0.5)
    pyautogui.hotkey("ctrl", "a")
    time.sleep(0.2)
    pyautogui.typewrite(url, interval=0.02)
    pyautogui.press("enter")


def main():
    print("=" * 60)
    print("ScreenPilot Self-Marketing Demo")
    print("Using ScreenPilot to promote ScreenPilot")
    print("=" * 60)
    print()

    start_time = time.time()
    step_num = 0

    # --- Task 1: Navigate to GitHub repo ---
    print("\n--- Task 1: Navigate to ScreenPilot GitHub Repository ---\n")

    step_num += 1
    step(step_num, "navigate", "github.com/pphouse/screenpilot")
    navigate_to("https://github.com/pphouse/screenpilot")
    time.sleep(5)
    screenshot("01_github_repo")

    step_num += 1
    step(step_num, "scroll", "down to README")
    pyautogui.scroll(-3)
    time.sleep(2)
    screenshot("02_github_readme")

    # --- Task 2: Navigate to landing page ---
    print("\n--- Task 2: Navigate to ScreenPilot Landing Page ---\n")

    step_num += 1
    step(step_num, "navigate", "pphouse.github.io/screenpilot/")
    navigate_to("https://pphouse.github.io/screenpilot/")
    time.sleep(5)
    screenshot("03_landing_hero")

    step_num += 1
    step(step_num, "scroll", "to terminal demo")
    pyautogui.scroll(-5)
    time.sleep(2)
    screenshot("04_landing_terminal")

    step_num += 1
    step(step_num, "scroll", "to comparison section")
    pyautogui.scroll(-5)
    time.sleep(2)
    screenshot("05_landing_comparison")

    step_num += 1
    step(step_num, "scroll", "to features grid")
    pyautogui.scroll(-5)
    time.sleep(2)
    screenshot("06_landing_features")

    step_num += 1
    step(step_num, "scroll", "to code examples")
    pyautogui.scroll(-8)
    time.sleep(2)
    screenshot("07_landing_code")

    # --- Task 3: Navigate to GitHub Discussions ---
    print("\n--- Task 3: Check GitHub Discussions ---\n")

    step_num += 1
    step(step_num, "navigate", "github.com/pphouse/screenpilot/discussions")
    navigate_to("https://github.com/pphouse/screenpilot/discussions")
    time.sleep(5)
    screenshot("08_discussions")

    # --- Task 4: Navigate to Release page ---
    print("\n--- Task 4: Check Release Page ---\n")

    step_num += 1
    step(step_num, "navigate", "github.com/pphouse/screenpilot/releases")
    navigate_to("https://github.com/pphouse/screenpilot/releases")
    time.sleep(5)
    screenshot("09_releases")

    step_num += 1
    step(step_num, "scroll", "release notes")
    pyautogui.scroll(-3)
    time.sleep(2)
    screenshot("10_release_details")

    # --- Done ---
    elapsed = time.time() - start_time
    print()
    print(f"\033[92m✓ Completed in {step_num} steps ({elapsed:.1f}s)\033[0m")
    print(f"Screenshots saved to: {OUTPUT_DIR.absolute()}")
    print()
    print("Marketing screenshots ready for:")
    print("  - Twitter/X posts")
    print("  - LinkedIn articles")
    print("  - Reddit/HN submissions")
    print("  - Product Hunt launch")
    print("  - Blog posts and documentation")


if __name__ == "__main__":
    main()
