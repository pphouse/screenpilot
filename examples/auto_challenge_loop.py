#!/usr/bin/env python3
"""
ScreenPilot Autonomous Challenge Loop
========================================
Continuously runs challenges, analyzes failures, retries with improved strategies,
and updates the viewer. Runs until API credits are exhausted.

Usage:
    python examples/auto_challenge_loop.py
    python examples/auto_challenge_loop.py --rounds 5
    python examples/auto_challenge_loop.py --only-new
"""

import argparse
import json
import os
import signal
import subprocess
import sys
import time
import traceback
from dataclasses import dataclass
from pathlib import Path

os.environ.setdefault("DISPLAY", ":99")

from screenpilot.agent import ScreenPilotAgent, StepResult, TaskResult
from screenpilot.config import ScreenPilotConfig

RECORDINGS_DIR = Path("recordings/challenges")
RECORDINGS_DIR.mkdir(parents=True, exist_ok=True)

# Import shared utilities from challenge_runner
sys.path.insert(0, str(Path(__file__).parent))
from challenge_runner import (
    Challenge, StepLog, start_recording, stop_recording,
    generate_srt, postprocess_video, navigate_chrome, generate_viewer,
)


# ============================================================================
# VIRAL / HIGH-IMPACT CHALLENGES
# ============================================================================

VIRAL_CHALLENGES = [
    # --- インパクト系: 「AIがこんなことできるの!?」 ---
    Challenge(20, "play_wordle", "expert",
              'This is the NYT Wordle game. Type "CRANE" and press Enter to make the first guess, then observe the result',
              "https://www.nytimes.com/games/wordle/index.html", 10,
              "AI plays Wordle - types a guess word"),
    Challenge(21, "use_calculator", "medium",
              'Click the buttons to calculate 42 × 7: click 4, then 2, then ×, then 7, then =',
              "https://www.online-calculator.com/", 15,
              "AI uses an online calculator"),
    Challenge(22, "google_maps_search", "hard",
              'Type "Tokyo Tower" in the search box and press Enter to find it on the map',
              "https://www.google.com/maps", 12,
              "AI searches for Tokyo Tower on Google Maps"),
    Challenge(23, "crypto_price", "medium",
              'Look at the current Bitcoin price displayed on the page and scroll down to see the price chart',
              "https://www.coingecko.com/en/coins/bitcoin", 10,
              "AI checks Bitcoin price and chart on CoinGecko"),
    Challenge(24, "draw_on_canvas", "expert",
              'Click and drag on the white canvas area to draw a simple line or shape',
              "https://kleki.com/", 12,
              "AI draws on a web canvas - creative AI art"),
    Challenge(25, "speed_typing_test", "hard",
              'Click the text area and start typing the displayed text to begin the typing speed test',
              "https://www.typingtest.com/", 12,
              "AI takes a typing speed test"),
    Challenge(26, "chess_first_move", "expert",
              'Make the first chess move by clicking on the e2 pawn (white pawn in front of the king), then clicking e4',
              "https://www.chess.com/play/computer", 15,
              "AI makes opening chess move e2-e4"),
    Challenge(27, "translate_text", "medium",
              'Type "Hello, I am an AI that controls computers by looking at the screen" in the source text box, then change the target language to Japanese',
              "https://translate.google.com/", 15,
              "AI uses Google Translate to translate text"),
    Challenge(28, "amazon_search", "medium",
              'Type "raspberry pi" in the search box and press Enter to search for products',
              "https://www.amazon.com", 12,
              "AI searches for products on Amazon"),
    Challenge(29, "imdb_movie", "medium",
              'Type "Inception" in the search box and press Enter to look up the movie',
              "https://www.imdb.com", 12,
              "AI searches for a movie on IMDB"),
    Challenge(30, "arxiv_paper", "hard",
              'Type "attention is all you need" in the search box and press Enter to find the famous transformer paper',
              "https://arxiv.org", 12,
              "AI searches for the Transformer paper on arXiv"),
    Challenge(31, "spotify_browse", "medium",
              'Scroll down to browse featured playlists and click on any playlist',
              "https://open.spotify.com", 12,
              "AI browses Spotify playlists"),
    Challenge(32, "github_create_issue_comment", "expert",
              'Scroll down to the comment box at the bottom of the issue, click it, and type "This issue was automatically found and commented by ScreenPilot AI agent"',
              "https://github.com/pphouse/screenpilot/issues/2", 15,
              "AI comments on a GitHub issue (read-only since not logged in)"),
    Challenge(33, "news_headline", "easy",
              'Scroll down to see more headlines and click on any news article to read it',
              "https://news.ycombinator.com/newest", 10,
              "AI browses latest HN stories and reads one"),
    Challenge(34, "wolfram_alpha", "hard",
              'Type "integral of x^2 sin(x)" in the input box and press Enter to compute',
              "https://www.wolframalpha.com/", 12,
              "AI solves a calculus problem on Wolfram Alpha"),
    Challenge(35, "github_profile", "medium",
              'Click on the "Repositories" tab to see the list of repositories',
              "https://github.com/pphouse", 10,
              "AI navigates a GitHub user profile"),
]


# ============================================================================
# Autonomous improvement loop
# ============================================================================

def analyze_failure(summary: dict) -> str:
    """Analyze why a challenge failed and suggest improvement."""
    steps = summary.get("step_details", [])
    error = summary.get("error", "")

    if not steps:
        return "agent_crash"

    # Check for repeated coordinates
    coords = [s["coords"] for s in steps if s["coords"]]
    if len(coords) >= 3:
        unique = set(coords[-3:])
        if len(unique) == 1:
            return "stuck_same_coords"

    # Check for repeated action types
    actions = [s["action"] for s in steps]
    if len(actions) >= 3 and len(set(actions[-3:])) == 1:
        return "stuck_same_action"

    # Check for bot detection keywords
    reasonings = " ".join(s.get("reasoning", "") for s in steps).lower()
    if any(kw in reasonings for kw in ["captcha", "recaptcha", "bot", "blocked", "forbidden"]):
        return "bot_detected"

    # Check if task was nearly complete (reached target page but didn't say done)
    if len(steps) >= summary.get("steps", 0) and not summary["success"]:
        if any("done" not in s["action"] for s in steps):
            return "completion_detection_fail"

    return "navigation_fail"


def run_single_challenge(challenge: Challenge, speed: float = 3.0, attempt: int = 1) -> dict:
    """Run a single challenge with recording (adapted from challenge_runner)."""
    print(f"\n{'=' * 60}")
    print(f"[Attempt {attempt}] Challenge #{challenge.id}: {challenge.name}")
    print(f"Difficulty: {challenge.difficulty.upper()} | Goal: {challenge.goal}")
    print(f"{'=' * 60}\n")

    suffix = f"_v{attempt}" if attempt > 1 else ""
    output_dir = RECORDINGS_DIR / f"{challenge.id:02d}_{challenge.name}{suffix}"
    output_dir.mkdir(parents=True, exist_ok=True)
    raw_video = output_dir / "recording_raw.mp4"
    srt_path = output_dir / "reasoning.srt"
    final_video = output_dir / "recording.mp4"

    # Navigate
    print(f"  [Setup] → {challenge.setup_url}")
    navigate_chrome(challenge.setup_url)
    time.sleep(2)

    # Record
    recorder = start_recording(raw_video)
    rec_start = time.time()
    time.sleep(1.5)

    # Agent
    config = ScreenPilotConfig()
    config.executor.screenshot_after_action = True
    agent = ScreenPilotAgent(config)

    step_logs: list[StepLog] = []
    step_details: list[dict] = []

    def on_step(step: StepResult) -> None:
        ts = time.time() - rec_start
        coords = f"({step.action.x}, {step.action.y})" if step.action.x is not None else ""
        reasoning = step.action.reasoning or ""
        status = "OK" if step.action_result.success else "FAIL"

        step_logs.append(StepLog(
            step.step_number, step.action.action_type.value,
            step.action.target or "", coords, reasoning,
            step.action_result.success, ts,
        ))
        step_details.append({
            "step": step.step_number, "action": step.action.action_type.value,
            "target": step.action.target or "", "coords": coords,
            "reasoning": reasoning[:200], "success": step.action_result.success,
            "timestamp": round(ts, 1),
        })
        print(f"    Step {step.step_number}: {step.action.action_type.value} {coords} [{status}]")

        if step.screenshot_before:
            step.screenshot_before.save(str(output_dir / f"step{step.step_number:02d}_before.png"))
        if step.screenshot_after:
            step.screenshot_after.save(str(output_dir / f"step{step.step_number:02d}_after.png"))

    agent.on_step(on_step)

    start_time = time.time()
    try:
        result = agent.run(challenge.goal, max_steps=challenge.max_steps)
    except Exception as e:
        print(f"    [ERROR] {e}")
        result = TaskResult(goal=challenge.goal, success=False, error=str(e),
                            total_time=time.time() - start_time)

    time.sleep(2)
    stop_recording(recorder)

    # Post-process
    generate_srt(step_logs, srt_path)
    if not postprocess_video(raw_video, srt_path, final_video, speed=speed):
        if raw_video.exists():
            import shutil
            shutil.copy2(raw_video, final_video)

    video_size = final_video.stat().st_size / 1024 if final_video.exists() else 0
    summary = {
        "challenge_id": challenge.id,
        "name": challenge.name + (f" (attempt {attempt})" if attempt > 1 else ""),
        "difficulty": challenge.difficulty,
        "goal": challenge.goal,
        "setup_url": challenge.setup_url,
        "success": result.success,
        "steps": result.num_steps,
        "time": round(result.total_time, 1),
        "error": result.error,
        "video_path": str(final_video),
        "video_size_kb": round(video_size),
        "speed": speed,
        "attempt": attempt,
        "step_details": step_details,
    }

    status_str = "PASS" if result.success else "FAIL"
    print(f"\n  [{status_str}] {result.num_steps} steps | {result.total_time:.1f}s | Video: {video_size:.0f}KB")

    with open(output_dir / "summary.json", "w") as f:
        json.dump(summary, f, indent=2, ensure_ascii=False)

    return summary


def update_viewer():
    """Regenerate the HTML viewer from all existing summaries."""
    all_results = {}
    for d in sorted(RECORDINGS_DIR.iterdir()):
        if not d.is_dir():
            continue
        s = d / "summary.json"
        if s.exists():
            data = json.loads(s.read_text())
            # Use challenge_id + attempt as key to keep all attempts
            key = (data["challenge_id"], data.get("attempt", 1))
            all_results[key] = data
    sorted_results = [all_results[k] for k in sorted(all_results.keys())]
    viewer = generate_viewer(sorted_results)
    print(f"  Viewer updated: {viewer} ({len(sorted_results)} entries)")

    report_path = RECORDINGS_DIR / "report.json"
    with open(report_path, "w") as f:
        json.dump({"results": sorted_results,
                    "passed": sum(1 for r in sorted_results if r["success"]),
                    "total": len(sorted_results)}, f, indent=2, ensure_ascii=False)


def autonomous_loop(rounds: int = 999, speed: float = 3.0, only_new: bool = False):
    """Main autonomous loop: run → analyze → retry → repeat."""

    # Load existing results to know what's been tried
    existing = {}
    for d in sorted(RECORDINGS_DIR.iterdir()):
        if not d.is_dir():
            continue
        s = d / "summary.json"
        if s.exists():
            data = json.loads(s.read_text())
            cid = data["challenge_id"]
            if cid not in existing or data["success"]:
                existing[cid] = data

    all_challenges = VIRAL_CHALLENGES[:]
    # Also include any from challenge_runner not yet tried
    from challenge_runner import CHALLENGES as BASE_CHALLENGES
    all_challenges = BASE_CHALLENGES + VIRAL_CHALLENGES

    round_num = 0
    total_api_calls = 0

    print(f"\n{'#' * 60}")
    print(f"  ScreenPilot Autonomous Challenge Loop")
    print(f"  Max rounds: {rounds} | Speed: {speed}x")
    print(f"  Total challenges available: {len(all_challenges)}")
    print(f"  Already completed: {sum(1 for v in existing.values() if v['success'])}")
    print(f"{'#' * 60}\n")

    while round_num < rounds:
        round_num += 1
        print(f"\n{'━' * 60}")
        print(f"  ROUND {round_num}")
        print(f"{'━' * 60}")

        # Pick challenges to run this round
        # Priority: 1) untried challenges, 2) failed challenges for retry
        untried = [c for c in all_challenges if c.id not in existing]
        failed = [c for c in all_challenges
                  if c.id in existing and not existing[c.id]["success"]
                  and existing[c.id].get("attempt", 1) < 3  # max 3 attempts
                  and analyze_failure(existing[c.id]) != "bot_detected"]  # skip bot-blocked

        if only_new:
            queue = untried
        else:
            # Alternate: 2 new, 1 retry
            queue = []
            u_iter = iter(untried)
            f_iter = iter(failed)
            for _ in range(6):  # up to 6 per round
                try:
                    queue.append(next(u_iter))
                except StopIteration:
                    pass
                try:
                    queue.append(next(u_iter))
                except StopIteration:
                    pass
                try:
                    queue.append(next(f_iter))
                except StopIteration:
                    pass

        if not queue:
            print("  No more challenges to run! All done or max retries reached.")
            break

        # Limit per round
        queue = queue[:6]
        print(f"  Running {len(queue)} challenges this round:")
        for c in queue:
            is_retry = c.id in existing
            tag = f" (retry #{existing[c.id].get('attempt', 1) + 1})" if is_retry else ""
            print(f"    #{c.id} {c.name}{tag} [{c.difficulty}]")

        for challenge in queue:
            attempt = existing.get(challenge.id, {}).get("attempt", 0) + 1

            try:
                summary = run_single_challenge(challenge, speed=speed, attempt=attempt)
                total_api_calls += summary["steps"]

                # Update existing tracker
                existing[challenge.id] = summary

                # Analyze failure
                if not summary["success"]:
                    failure_type = analyze_failure(summary)
                    print(f"  Failure analysis: {failure_type}")

            except Exception as e:
                err_msg = str(e)
                print(f"\n  [FATAL ERROR] {err_msg}")
                if "credit" in err_msg.lower() or "rate" in err_msg.lower() or "quota" in err_msg.lower():
                    print("  API credits likely exhausted. Stopping loop.")
                    update_viewer()
                    return
                if "authentication" in err_msg.lower() or "api_key" in err_msg.lower():
                    print("  API key issue. Stopping loop.")
                    update_viewer()
                    return
                traceback.print_exc()

        # Update viewer after each round
        update_viewer()

        # Stats
        passed = sum(1 for v in existing.values() if v["success"])
        total = len(existing)
        print(f"\n  Round {round_num} complete. Overall: {passed}/{total} passed ({passed/total*100:.0f}%)")
        print(f"  Total API steps so far: {total_api_calls}")

    # Final summary
    update_viewer()
    passed = sum(1 for v in existing.values() if v["success"])
    total = len(existing)
    print(f"\n{'#' * 60}")
    print(f"  LOOP COMPLETE")
    print(f"  Rounds: {round_num} | Passed: {passed}/{total} ({passed/total*100:.0f}%)")
    print(f"  Total API steps: {total_api_calls}")
    print(f"  Viewer: {RECORDINGS_DIR / 'viewer.html'}")
    print(f"{'#' * 60}")


def main():
    parser = argparse.ArgumentParser(description="ScreenPilot Autonomous Challenge Loop")
    parser.add_argument("--rounds", "-r", type=int, default=999,
                        help="Max rounds (default: 999 = until credits run out)")
    parser.add_argument("--speed", "-s", type=float, default=3.0)
    parser.add_argument("--only-new", action="store_true",
                        help="Only run untried challenges, skip retries")
    args = parser.parse_args()

    autonomous_loop(rounds=args.rounds, speed=args.speed, only_new=args.only_new)


if __name__ == "__main__":
    main()
