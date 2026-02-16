#!/usr/bin/env python3
"""
ScreenPilot Challenge Runner
==============================
Runs ScreenPilot agent on real tasks while recording the Xvfb screen with ffmpeg.
This captures the ACTUAL AI agent behavior (screenshot → LLM → action loop).

Usage:
    python examples/challenge_runner.py
    python examples/challenge_runner.py --challenge 3
"""

import argparse
import os
import signal
import subprocess
import sys
import time
from dataclasses import dataclass
from pathlib import Path

# Ensure DISPLAY is set
os.environ.setdefault("DISPLAY", ":99")

from screenpilot.agent import ScreenPilotAgent, StepResult, TaskResult
from screenpilot.config import ScreenPilotConfig


RECORDINGS_DIR = Path("recordings/challenges")
RECORDINGS_DIR.mkdir(parents=True, exist_ok=True)


@dataclass
class Challenge:
    id: int
    name: str
    difficulty: str  # easy / medium / hard / expert
    goal: str
    setup_url: str  # URL to open in Chrome before running
    max_steps: int
    description: str


CHALLENGES = [
    Challenge(
        id=1,
        name="click_issues_tab",
        difficulty="easy",
        goal="Click on the Issues tab in the GitHub repository page",
        setup_url="https://github.com/pphouse/screenpilot",
        max_steps=10,
        description="Navigate from repo main page to Issues tab by clicking",
    ),
    Challenge(
        id=2,
        name="navigate_to_discussions",
        difficulty="easy",
        goal="Click on the Discussions tab in the GitHub repository page",
        setup_url="https://github.com/pphouse/screenpilot",
        max_steps=10,
        description="Navigate from repo main page to Discussions tab",
    ),
    Challenge(
        id=3,
        name="star_count_check",
        difficulty="medium",
        goal='Find and click on the "Code" tab, then scroll down to read the README',
        setup_url="https://github.com/pphouse/screenpilot/issues",
        max_steps=15,
        description="Start from Issues page, navigate to Code tab and scroll to README",
    ),
    Challenge(
        id=4,
        name="search_github",
        difficulty="medium",
        goal='Use the GitHub search bar to search for "screenpilot" and press Enter',
        setup_url="https://github.com",
        max_steps=15,
        description="Navigate GitHub search from the homepage",
    ),
    Challenge(
        id=5,
        name="open_file_in_repo",
        difficulty="hard",
        goal='Navigate to the "screenpilot" folder, then click on "agent.py" to view the file',
        setup_url="https://github.com/pphouse/screenpilot",
        max_steps=20,
        description="Browse the repo file tree and open a specific Python file",
    ),
    Challenge(
        id=6,
        name="wikipedia_search",
        difficulty="hard",
        goal='Go to the Wikipedia search box, type "artificial intelligence", and press Enter to search',
        setup_url="https://en.wikipedia.org",
        max_steps=15,
        description="Search Wikipedia for a topic using the search box",
    ),
    Challenge(
        id=7,
        name="multi_step_navigation",
        difficulty="expert",
        goal="Navigate to the Issues page, click on issue #2, then go back to the main Code page",
        setup_url="https://github.com/pphouse/screenpilot",
        max_steps=25,
        description="Multi-step navigation: repo → issues → issue detail → back to code",
    ),
    # --- Round 2: Diverse real-world tasks ---
    Challenge(
        id=8,
        name="yahoo_finance_stock",
        difficulty="medium",
        goal='Type "AAPL" in the search/quote box and press Enter to look up Apple stock price',
        setup_url="https://finance.yahoo.com",
        max_steps=15,
        description="Look up Apple stock price on Yahoo Finance",
    ),
    Challenge(
        id=9,
        name="hackernews_browse",
        difficulty="easy",
        goal="Click on the 2nd story link on the Hacker News front page to read the article",
        setup_url="https://news.ycombinator.com",
        max_steps=10,
        description="Browse and click a story on Hacker News",
    ),
    Challenge(
        id=10,
        name="youtube_search",
        difficulty="hard",
        goal='Click the search box at the top, type "screenpilot demo", and press Enter to search',
        setup_url="https://www.youtube.com",
        max_steps=15,
        description="Search for a video on YouTube",
    ),
    Challenge(
        id=11,
        name="reddit_browse",
        difficulty="medium",
        goal="Scroll down to see more posts, then click on any post title to open it",
        setup_url="https://old.reddit.com/r/programming",
        max_steps=15,
        description="Browse r/programming on old Reddit and open a post",
    ),
    Challenge(
        id=12,
        name="google_search",
        difficulty="medium",
        goal='Type "ScreenPilot AI desktop automation" in the Google search box and press Enter',
        setup_url="https://www.google.com",
        max_steps=12,
        description="Perform a Google search query",
    ),
    Challenge(
        id=13,
        name="weather_check",
        difficulty="hard",
        goal='Type "Tokyo" in the search box and search to see the weather forecast for Tokyo',
        setup_url="https://wttr.in",
        max_steps=12,
        description="Check weather forecast for Tokyo",
    ),
    Challenge(
        id=14,
        name="wikipedia_jp_navigate",
        difficulty="expert",
        goal='Search for "人工知能" (artificial intelligence in Japanese), then click the first link in the article body to navigate deeper',
        setup_url="https://ja.wikipedia.org",
        max_steps=20,
        description="Search Japanese Wikipedia and follow a link in the article",
    ),
]


def start_recording(output_path: Path, display: str = ":99", fps: int = 10) -> subprocess.Popen:
    """Start ffmpeg screen recording of Xvfb display."""
    cmd = [
        "ffmpeg", "-y",
        "-f", "x11grab",
        "-framerate", str(fps),
        "-video_size", "1920x1080",
        "-i", display,
        "-c:v", "libx264",
        "-preset", "ultrafast",
        "-crf", "28",
        "-pix_fmt", "yuv420p",
        str(output_path),
    ]
    proc = subprocess.Popen(
        cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
    )
    time.sleep(0.5)  # Let ffmpeg initialize
    return proc


def stop_recording(proc: subprocess.Popen) -> None:
    """Stop ffmpeg recording gracefully."""
    proc.send_signal(signal.SIGINT)
    try:
        proc.wait(timeout=10)
    except subprocess.TimeoutExpired:
        proc.kill()


def navigate_chrome(url: str) -> None:
    """Navigate Chrome to a URL using xdotool."""
    # Focus Chrome window
    subprocess.run(
        ["xdotool", "search", "--onlyvisible", "--name", "Chrome", "windowactivate"],
        capture_output=True, timeout=5,
    )
    time.sleep(0.3)

    # Open URL with Ctrl+L → type URL → Enter
    subprocess.run(["xdotool", "key", "ctrl+l"], capture_output=True, timeout=5)
    time.sleep(0.3)
    subprocess.run(["xdotool", "type", "--clearmodifiers", url], capture_output=True, timeout=10)
    time.sleep(0.2)
    subprocess.run(["xdotool", "key", "Return"], capture_output=True, timeout=5)
    time.sleep(3)  # Wait for page load


def save_step_screenshots(challenge: Challenge, result: TaskResult, output_dir: Path) -> None:
    """Save before/after screenshots for each step."""
    for step in result.steps:
        if step.screenshot_before:
            step.screenshot_before.save(
                str(output_dir / f"step{step.step_number:02d}_before.png")
            )
        if step.screenshot_after:
            step.screenshot_after.save(
                str(output_dir / f"step{step.step_number:02d}_after.png")
            )


def run_challenge(challenge: Challenge) -> dict:
    """Run a single challenge with recording."""
    print(f"\n{'=' * 60}")
    print(f"Challenge #{challenge.id}: {challenge.name}")
    print(f"Difficulty: {challenge.difficulty.upper()}")
    print(f"Goal: {challenge.goal}")
    print(f"{'=' * 60}\n")

    # Create output directory
    output_dir = RECORDINGS_DIR / f"{challenge.id:02d}_{challenge.name}"
    output_dir.mkdir(parents=True, exist_ok=True)
    video_path = output_dir / "recording.mp4"

    # Step 1: Navigate Chrome to setup URL
    print(f"[Setup] Navigating to {challenge.setup_url}...")
    navigate_chrome(challenge.setup_url)
    time.sleep(2)

    # Step 2: Start recording
    print(f"[Recording] Starting screen capture → {video_path}")
    recorder = start_recording(video_path)

    # Brief pause so recording captures the starting state
    time.sleep(1.5)

    # Step 3: Run ScreenPilot agent
    print(f"[Agent] Starting ScreenPilot (max_steps={challenge.max_steps})...")
    config = ScreenPilotConfig()
    config.executor.screenshot_after_action = True
    agent = ScreenPilotAgent(config)

    step_count = 0

    def on_step(step: StepResult) -> None:
        nonlocal step_count
        step_count += 1
        status = "OK" if step.action_result.success else "FAIL"
        coords = ""
        if step.action.x is not None:
            coords = f" at ({step.action.x}, {step.action.y})"
        reasoning = step.action.reasoning[:60] if step.action.reasoning else ""
        print(f"  Step {step.step_number}: {step.action.action_type.value}{coords} [{status}]")
        if reasoning:
            print(f"    → {reasoning}")

    agent.on_step(on_step)

    start_time = time.time()
    try:
        result = agent.run(challenge.goal, max_steps=challenge.max_steps)
    except Exception as e:
        print(f"  [ERROR] Agent crashed: {e}")
        result = TaskResult(
            goal=challenge.goal, success=False, error=str(e), total_time=time.time() - start_time
        )

    # Brief pause so recording captures the final state
    time.sleep(2)

    # Step 4: Stop recording
    stop_recording(recorder)
    print(f"\n[Recording] Saved → {video_path}")

    # Step 5: Save step screenshots
    save_step_screenshots(challenge, result, output_dir)

    # Step 6: Summary
    video_size = video_path.stat().st_size / 1024 if video_path.exists() else 0
    summary = {
        "challenge_id": challenge.id,
        "name": challenge.name,
        "difficulty": challenge.difficulty,
        "success": result.success,
        "steps": result.num_steps,
        "time": result.total_time,
        "error": result.error,
        "video_path": str(video_path),
        "video_size_kb": video_size,
    }

    status_emoji = "PASS" if result.success else "FAIL"
    print(f"\n[Result] {status_emoji} | {result.num_steps} steps | {result.total_time:.1f}s | Video: {video_size:.0f} KB")

    # Save summary
    import json
    with open(output_dir / "summary.json", "w") as f:
        json.dump(summary, f, indent=2)

    return summary


def main():
    parser = argparse.ArgumentParser(description="ScreenPilot Challenge Runner")
    parser.add_argument("--challenge", "-c", type=int, default=None,
                        help="Run a specific challenge by ID (1-7)")
    parser.add_argument("--from-id", type=int, default=1,
                        help="Start from this challenge ID")
    parser.add_argument("--to-id", type=int, default=None,
                        help="End at this challenge ID (inclusive)")
    parser.add_argument("--list", "-l", action="store_true",
                        help="List all challenges")
    args = parser.parse_args()

    if args.list:
        print(f"\n{'ID':<4} {'Difficulty':<10} {'Name':<25} Description")
        print("-" * 70)
        for c in CHALLENGES:
            print(f"{c.id:<4} {c.difficulty:<10} {c.name:<25} {c.description}")
        return

    if args.challenge:
        challenges = [c for c in CHALLENGES if c.id == args.challenge]
        if not challenges:
            print(f"Challenge {args.challenge} not found. Use --list to see all.")
            sys.exit(1)
    else:
        to_id = args.to_id or len(CHALLENGES)
        challenges = [c for c in CHALLENGES if args.from_id <= c.id <= to_id]

    print(f"\nScreenPilot Challenge Runner")
    print(f"Running {len(challenges)} challenge(s)")
    print(f"Recordings will be saved to: {RECORDINGS_DIR.resolve()}")

    results = []
    for challenge in challenges:
        summary = run_challenge(challenge)
        results.append(summary)

    # Final report
    print(f"\n{'=' * 60}")
    print(f"FINAL REPORT")
    print(f"{'=' * 60}")
    passed = sum(1 for r in results if r["success"])
    total = len(results)
    print(f"Passed: {passed}/{total}")
    print()
    for r in results:
        status = "PASS" if r["success"] else "FAIL"
        print(f"  #{r['challenge_id']} [{r['difficulty']:<6}] {r['name']:<25} {status} ({r['steps']} steps, {r['time']:.1f}s)")
    print()

    # Save full report
    import json
    report_path = RECORDINGS_DIR / "report.json"
    with open(report_path, "w") as f:
        json.dump({"results": results, "passed": passed, "total": total}, f, indent=2)
    print(f"Report saved: {report_path}")


if __name__ == "__main__":
    main()
