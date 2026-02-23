#!/usr/bin/env python3
"""
ScreenPilot Challenge Loop — Cerebras GPT-OSS-120B + Chandra OCR Edition
=========================================================================
Runs the same challenges as the main loop but using:
  - Cerebras GPT-OSS-120B for LLM reasoning (text-only, no vision)
  - Chandra/Datalab Marker API for OCR (screenshot → text)
  - pytesseract for element coordinate mapping

This allows cost/speed/accuracy comparison with the Claude-based approach.

Usage:
    python examples/cerebras_challenge_loop.py --rounds 2
    python examples/cerebras_challenge_loop.py --ids 1,4,9,12
"""

import argparse
import json
import os
import shutil
import signal
import subprocess
import sys
import time
import traceback
from dataclasses import dataclass
from pathlib import Path

os.environ.setdefault("DISPLAY", ":99")

# Import shared utilities from challenge_runner
sys.path.insert(0, str(Path(__file__).parent))
from challenge_runner import (
    Challenge, StepLog, start_recording, stop_recording,
    generate_srt, postprocess_video, navigate_chrome,
)

# Import Cerebras planner
from screenpilot.planner.planner_cerebras import CerebrasPlanner
from screenpilot.planner.planner import Action, ActionType
from screenpilot.vision.capture import Screenshot

RECORDINGS_DIR = Path("recordings/cerebras_challenges")  # default, overridden by --no-chandra

# Use the same challenges as the main loop
CHALLENGES = [
    # Easy/Medium - good baselines
    Challenge(1, "click_issues_tab", "easy",
              "Click on the Issues tab in the GitHub repository page",
              "https://github.com/pphouse/screenpilot", 10,
              "Navigate from repo main page to Issues tab"),
    Challenge(4, "search_github", "medium",
              'Use the GitHub search bar to search for "screenpilot" and press Enter',
              "https://github.com", 15,
              "Navigate GitHub search from the homepage"),
    Challenge(9, "hackernews_browse", "easy",
              "Click on the 2nd story link on the Hacker News front page",
              "https://news.ycombinator.com", 10,
              "Browse and click a story on Hacker News"),
    Challenge(12, "google_search", "medium",
              'Type "ScreenPilot AI desktop automation" in the Google search box and press Enter',
              "https://www.google.com", 12,
              "Perform a Google search query"),
    Challenge(17, "hn_top_comments", "medium",
              "Click on the 'comments' link of the top story to view the discussion",
              "https://news.ycombinator.com", 10,
              "Navigate to HN comment thread"),
    Challenge(18, "github_trending", "medium",
              "Scroll down to see trending repositories and click on the first repo name",
              "https://github.com/trending", 12,
              "Browse GitHub Trending"),
    # Hard
    Challenge(6, "wikipedia_search", "hard",
              'Type "artificial intelligence" in the search box and press Enter',
              "https://en.wikipedia.org", 15,
              "Search Wikipedia"),
    Challenge(27, "translate_text", "medium",
              'Type "Hello, I am an AI agent" in the source text box, then change target language to Japanese',
              "https://translate.google.com/", 15,
              "Use Google Translate"),
    Challenge(30, "arxiv_paper", "hard",
              'Type "attention is all you need" in the search box and press Enter',
              "https://arxiv.org", 12,
              "Search arXiv for the Transformer paper"),
    Challenge(34, "wolfram_alpha", "hard",
              'Type "integral of x^2 sin(x)" in the input box and press Enter',
              "https://www.wolframalpha.com/", 12,
              "Solve calculus on Wolfram Alpha"),
    # Expert
    Challenge(50, "flight_sort_cheapest", "expert",
              'Search for one-way flights from Tokyo to New York departing March 15. After results load, sort by price.',
              "https://www.google.com/travel/flights", 20,
              "Search + sort flights"),
    Challenge(53, "github_deep_code_nav", "expert",
              'Navigate into "screenpilot" folder, then "planner" subfolder, then open "planner.py". Scroll down.',
              "https://github.com/pphouse/screenpilot", 20,
              "Navigate deep into code repo"),
    Challenge(63, "github_pr_review", "expert",
              'Click "Pull requests" tab. Click the most recent PR. Scroll down to see changes.',
              "https://github.com/microsoft/vscode", 20,
              "GitHub PR review workflow"),
    Challenge(68, "npm_package_research", "expert",
              'Type "express" in search, click the first result, scroll down to see README.',
              "https://www.npmjs.com", 15,
              "Research npm packages"),
]


def take_screenshot() -> Screenshot:
    """Take a screenshot of the current display."""
    import subprocess
    import io
    from PIL import Image

    proc = subprocess.run(
        ["import", "-window", "root", "png:-"],
        capture_output=True, timeout=10,
        env={**os.environ, "DISPLAY": ":99"},
    )
    if proc.returncode != 0:
        raise RuntimeError(f"Screenshot failed: {proc.stderr.decode()}")

    image = Image.open(io.BytesIO(proc.stdout))
    return Screenshot(image=image, timestamp=time.time(), monitor_index=0,
                      width=image.width, height=image.height)


def execute_action(action: Action) -> bool:
    """Execute an action using xdotool."""
    try:
        if action.action_type == ActionType.DONE:
            return True
        elif action.action_type == ActionType.FAIL:
            return False
        elif action.action_type == ActionType.CLICK:
            if action.x is not None and action.y is not None:
                subprocess.run(
                    ["xdotool", "mousemove", str(action.x), str(action.y), "click", "1"],
                    capture_output=True, timeout=5,
                )
                time.sleep(0.5)
                return True
        elif action.action_type == ActionType.DOUBLE_CLICK:
            if action.x is not None and action.y is not None:
                subprocess.run(
                    ["xdotool", "mousemove", str(action.x), str(action.y),
                     "click", "--repeat", "2", "--delay", "100", "1"],
                    capture_output=True, timeout=5,
                )
                time.sleep(0.5)
                return True
        elif action.action_type == ActionType.TYPE:
            text = action.text or ""
            if text:
                subprocess.run(
                    ["xdotool", "type", "--clearmodifiers", "--delay", "20", text],
                    capture_output=True, timeout=30,
                )
                time.sleep(0.3)
                return True
        elif action.action_type == ActionType.KEY:
            keys = action.keys or ""
            if keys:
                subprocess.run(
                    ["xdotool", "key", "--clearmodifiers", keys],
                    capture_output=True, timeout=5,
                )
                time.sleep(0.3)
                return True
        elif action.action_type == ActionType.SCROLL:
            direction = action.direction or "down"
            amount = action.amount or 3
            button = "5" if direction == "down" else "4"
            subprocess.run(
                ["xdotool", "click", "--repeat", str(amount), button],
                capture_output=True, timeout=5,
            )
            time.sleep(0.5)
            return True
        elif action.action_type == ActionType.WAIT:
            duration = action.duration or 2.0
            time.sleep(min(duration, 5.0))
            return True
        elif action.action_type == ActionType.DRAG:
            if action.x is not None and action.y is not None:
                # Move to start, press, move to end, release
                end_x = action.metadata.get("end_x", action.x + 100)
                end_y = action.metadata.get("end_y", action.y)
                subprocess.run(
                    ["xdotool", "mousemove", str(action.x), str(action.y),
                     "mousedown", "1"],
                    capture_output=True, timeout=5,
                )
                time.sleep(0.2)
                subprocess.run(
                    ["xdotool", "mousemove", str(end_x), str(end_y),
                     "mouseup", "1"],
                    capture_output=True, timeout=5,
                )
                time.sleep(0.3)
                return True
        elif action.action_type in (ActionType.FIND_AND_CLICK, ActionType.FIND_AND_TYPE):
            # For text-only LLM, these should resolve to click/type with coordinates
            if action.x is not None and action.y is not None:
                subprocess.run(
                    ["xdotool", "mousemove", str(action.x), str(action.y), "click", "1"],
                    capture_output=True, timeout=5,
                )
                time.sleep(0.3)
                if action.action_type == ActionType.FIND_AND_TYPE and action.text:
                    subprocess.run(
                        ["xdotool", "type", "--clearmodifiers", "--delay", "20", action.text],
                        capture_output=True, timeout=30,
                    )
                return True
    except Exception as e:
        print(f"    Action execution error: {e}")
        return False

    return False


def run_single_challenge(
    challenge: Challenge,
    planner: CerebrasPlanner,
    speed: float = 3.0,
    attempt: int = 1,
) -> dict:
    """Run a single challenge with Cerebras planner."""
    print(f"\n{'=' * 60}")
    print(f"[Cerebras] Challenge #{challenge.id}: {challenge.name}")
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
    time.sleep(3)

    # Record
    recorder = start_recording(raw_video)
    rec_start = time.time()
    time.sleep(1.5)

    # Reset planner for new task
    planner.reset()

    step_logs: list[StepLog] = []
    step_details: list[dict] = []
    success = False
    num_steps = 0
    error_msg = ""

    start_time = time.time()

    try:
        for step in range(1, challenge.max_steps + 1):
            num_steps = step

            # Take screenshot
            screenshot = take_screenshot()

            # Get action from Cerebras planner
            action = planner.get_next_action(
                goal=challenge.goal,
                screenshot=screenshot,
                max_steps=challenge.max_steps,
            )

            ts = time.time() - rec_start
            coords = f"({action.x}, {action.y})" if action.x is not None else ""
            reasoning = action.reasoning or ""

            step_logs.append(StepLog(
                step, action.action_type.value,
                action.target or "", coords, reasoning,
                True, ts,
            ))
            step_details.append({
                "step": step, "action": action.action_type.value,
                "target": action.target or "", "coords": coords,
                "reasoning": reasoning[:200], "success": True,
                "timestamp": round(ts, 1),
            })

            status_icon = "→"
            print(f"    Step {step}: {action.action_type.value} {coords} [{status_icon}]")

            # Save screenshots
            screenshot.image.save(str(output_dir / f"step{step:02d}_before.png"))

            # Check for terminal actions
            if action.action_type == ActionType.DONE:
                success = True
                print(f"    [DONE] Task completed!")
                break
            elif action.action_type == ActionType.FAIL:
                success = False
                error_msg = action.reasoning
                print(f"    [FAIL] {action.reasoning[:80]}")
                break

            # Execute action
            action_ok = execute_action(action)
            if not action_ok:
                step_details[-1]["success"] = False
                step_logs[-1] = StepLog(
                    step, action.action_type.value,
                    action.target or "", coords, reasoning,
                    False, ts,
                )

            time.sleep(0.5)

    except Exception as e:
        error_msg = str(e)
        print(f"    [ERROR] {e}")
        traceback.print_exc()

    total_time = time.time() - start_time

    time.sleep(2)
    stop_recording(recorder)

    # Get cost info
    cost_usd = planner.estimated_cost_usd
    breakdown = planner.cost_breakdown

    # Post-process video
    generate_srt(step_logs, srt_path)
    if not postprocess_video(raw_video, srt_path, final_video, speed=speed):
        if raw_video.exists():
            shutil.copy2(raw_video, final_video)

    video_size = final_video.stat().st_size / 1024 if final_video.exists() else 0

    summary = {
        "challenge_id": challenge.id,
        "name": challenge.name + (f" (attempt {attempt})" if attempt > 1 else ""),
        "difficulty": challenge.difficulty,
        "goal": challenge.goal,
        "setup_url": challenge.setup_url,
        "success": success,
        "steps": num_steps,
        "time": round(total_time, 1),
        "error": error_msg,
        "video_path": str(final_video),
        "video_size_kb": round(video_size),
        "speed": speed,
        "attempt": attempt,
        "input_tokens": planner.total_input_tokens,
        "output_tokens": planner.total_output_tokens,
        "cost_usd": round(cost_usd, 6),
        "cost_breakdown": breakdown,
        "engine": planner.engine_name,
        "ocr": "chandra+pytesseract" if planner.chandra else "pytesseract",
        "step_details": step_details,
    }

    status_str = "PASS" if success else "FAIL"
    print(f"\n  [{status_str}] {num_steps} steps | {total_time:.1f}s | Cost: ${cost_usd:.4f}")
    print(f"    LLM: ${breakdown['llm_input_cost']+breakdown['llm_output_cost']:.4f} | OCR: ${breakdown['ocr_cost']:.4f}")
    print(f"    LLM time: {breakdown['llm_time']:.1f}s | OCR time: {breakdown['ocr_time']:.1f}s")

    with open(output_dir / "summary.json", "w") as f:
        json.dump(summary, f, indent=2, ensure_ascii=False)

    return summary


def generate_cerebras_viewer(results: list[dict]) -> Path:
    """Generate an HTML viewer for Cerebras challenge results."""
    viewer_path = RECORDINGS_DIR / "viewer.html"

    cards_html = ""
    for r in results:
        status_class = "pass" if r["success"] else "fail"
        status_text = "PASS" if r["success"] else "FAIL"
        video_rel = Path(r["video_path"]).name if "/" not in r["video_path"] else \
            str(Path(r["video_path"]).relative_to(RECORDINGS_DIR))

        steps_html = ""
        for s in r.get("step_details", []):
            s_class = "step-ok" if s["success"] else "step-fail"
            steps_html += f"""<div class="step {s_class}" title="{s['reasoning'][:100]}">
                <span class="step-num">#{s['step']}</span>
                <span class="step-action">{s['action']}</span>
                <span class="step-coords">{s['coords']}</span>
            </div>"""

        error_html = f'<div class="error">{r["error"]}</div>' if r.get("error") else ""
        bd = r.get("cost_breakdown", {})

        cards_html += f"""
        <div class="card {status_class}">
            <div class="card-header">
                <span class="challenge-id">#{r['challenge_id']}</span>
                <span class="difficulty {r['difficulty']}">{r['difficulty'].upper()}</span>
                <span class="status-badge {status_class}">{status_text}</span>
                <span class="engine-badge">Cerebras</span>
                <h3>{r['name']}</h3>
            </div>
            <div class="card-meta">
                <span>Goal: {r.get('goal', '')[:100]}</span>
            </div>
            <div class="card-stats">
                <span>{r['steps']} steps</span>
                <span>{r['time']}s</span>
                <span>LLM: ${bd.get('llm_input_cost',0)+bd.get('llm_output_cost',0):.4f}</span>
                <span>OCR: ${bd.get('ocr_cost',0):.4f}</span>
                <span>Total: ${r.get('cost_usd',0):.4f}</span>
            </div>
            {error_html}
            <div class="video-container">
                <video controls preload="metadata" width="100%">
                    <source src="{video_rel}" type="video/mp4">
                </video>
            </div>
            <details class="steps-detail">
                <summary>Steps ({len(r.get('step_details', []))} steps)</summary>
                <div class="steps-timeline">{steps_html}</div>
            </details>
        </div>
        """

    passed = sum(1 for r in results if r["success"])
    total = len(results)
    total_cost = sum(r.get("cost_usd", 0) for r in results)

    html = f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>ScreenPilot Cerebras Challenge Viewer</title>
<style>
* {{ margin: 0; padding: 0; box-sizing: border-box; }}
body {{ font-family: -apple-system, BlinkMacSystemFont, sans-serif;
       background: #0d1117; color: #c9d1d9; padding: 20px; }}
h1 {{ color: #f0883e; margin-bottom: 8px; }}
.subtitle {{ color: #8b949e; margin-bottom: 20px; }}
.summary-bar {{ display: flex; gap: 20px; margin-bottom: 24px; padding: 16px;
               background: #161b22; border: 1px solid #30363d; border-radius: 8px; flex-wrap: wrap; }}
.summary-stat {{ text-align: center; min-width: 80px; }}
.summary-stat .value {{ font-size: 24px; font-weight: bold; color: #f0883e; }}
.summary-stat .label {{ font-size: 12px; color: #8b949e; }}
.grid {{ display: grid; grid-template-columns: repeat(auto-fill, minmax(560px, 1fr)); gap: 20px; }}
.card {{ background: #161b22; border: 1px solid #30363d; border-radius: 10px;
        padding: 16px; transition: 0.2s; }}
.card:hover {{ border-color: #f0883e; }}
.card.pass {{ border-left: 4px solid #3fb950; }}
.card.fail {{ border-left: 4px solid #f85149; }}
.card-header {{ display: flex; align-items: center; gap: 8px; margin-bottom: 8px; flex-wrap: wrap; }}
.challenge-id {{ color: #8b949e; font-weight: bold; }}
.difficulty {{ padding: 2px 8px; border-radius: 12px; font-size: 11px; font-weight: bold; }}
.difficulty.easy {{ background: #238636; color: white; }}
.difficulty.medium {{ background: #9e6a03; color: white; }}
.difficulty.hard {{ background: #da3633; color: white; }}
.difficulty.expert {{ background: #8957e5; color: white; }}
.status-badge {{ padding: 2px 8px; border-radius: 4px; font-size: 12px; font-weight: bold; }}
.status-badge.pass {{ background: #238636; color: white; }}
.status-badge.fail {{ background: #da3633; color: white; }}
.engine-badge {{ padding: 2px 8px; border-radius: 4px; font-size: 11px;
                background: #f0883e; color: #0d1117; font-weight: bold; }}
h3 {{ color: #c9d1d9; font-size: 16px; }}
.card-meta {{ color: #8b949e; font-size: 13px; margin-bottom: 8px; }}
.card-stats {{ display: flex; gap: 12px; color: #8b949e; font-size: 13px; margin-bottom: 8px; flex-wrap: wrap; }}
.error {{ color: #f85149; font-size: 12px; margin-bottom: 8px; }}
.video-container {{ margin: 10px 0; }}
video {{ border-radius: 8px; }}
.steps-detail {{ margin-top: 10px; }}
summary {{ cursor: pointer; color: #58a6ff; font-size: 13px; }}
.steps-timeline {{ margin-top: 8px; }}
.step {{ display: flex; gap: 8px; padding: 4px 0; font-size: 12px; border-bottom: 1px solid #21262d; }}
.step-ok {{ color: #3fb950; }}
.step-fail {{ color: #f85149; }}
.step-num {{ font-weight: bold; width: 30px; }}
.step-action {{ width: 80px; }}
</style>
</head>
<body>
<h1>ScreenPilot x Cerebras GPT-OSS-120B</h1>
<p class="subtitle">Cerebras + Chandra OCR vs Claude comparison</p>
<div class="summary-bar">
    <div class="summary-stat"><div class="value">{passed}/{total}</div><div class="label">Passed</div></div>
    <div class="summary-stat"><div class="value">{passed/total*100:.0f}%</div><div class="label">Success</div></div>
    <div class="summary-stat"><div class="value">${total_cost:.3f}</div><div class="label">Total Cost</div></div>
    <div class="summary-stat"><div class="value">Cerebras</div><div class="label">LLM Engine</div></div>
    <div class="summary-stat"><div class="value">Chandra</div><div class="label">OCR Engine</div></div>
</div>
<div class="grid">{cards_html}</div>
</body></html>"""

    viewer_path.write_text(html, encoding="utf-8")
    return viewer_path


def update_viewer():
    """Regenerate viewer from all summaries."""
    all_results = {}
    for d in sorted(RECORDINGS_DIR.iterdir()):
        if not d.is_dir():
            continue
        s = d / "summary.json"
        if s.exists():
            data = json.loads(s.read_text())
            key = (data["challenge_id"], data.get("attempt", 1))
            all_results[key] = data
    sorted_results = [all_results[k] for k in sorted(all_results.keys())]
    viewer = generate_cerebras_viewer(sorted_results)
    print(f"  Viewer updated: {viewer} ({len(sorted_results)} entries)")

    report_path = RECORDINGS_DIR / "report.json"
    with open(report_path, "w") as f:
        json.dump({
            "engine": planner.engine_name,
            "ocr": "chandra+pytesseract",
            "results": sorted_results,
            "passed": sum(1 for r in sorted_results if r["success"]),
            "total": len(sorted_results),
            "total_cost": sum(r.get("cost_usd", 0) for r in sorted_results),
        }, f, indent=2, ensure_ascii=False)


def main():
    parser = argparse.ArgumentParser(description="ScreenPilot Challenge Loop (multi-backend)")
    parser.add_argument("--rounds", "-r", type=int, default=1)
    parser.add_argument("--speed", "-s", type=float, default=3.0)
    parser.add_argument("--ids", help="Comma-separated challenge IDs to run")
    parser.add_argument("--no-chandra", action="store_true",
                        help="Skip Chandra OCR, use pytesseract only (free)")
    parser.add_argument("--azure", action="store_true",
                        help="Use Azure OpenAI instead of Cerebras")
    args = parser.parse_args()

    chandra_key = "" if args.no_chandra else os.environ.get("CHANDRA_API_KEY", "")

    if args.azure:
        # Azure OpenAI GPT-5
        planner = CerebrasPlanner(
            backend="azure",
            azure_endpoint=os.environ.get("AZURE_OPENAI_ENDPOINT", ""),
            azure_api_key=os.environ.get("AZURE_OPENAI_API_KEY", ""),
            azure_deployment=os.environ.get("AZURE_OPENAI_DEPLOYMENT", ""),
            chandra_api_key=chandra_key,
        )
    else:
        # Cerebras GPT-OSS-120B
        cerebras_key = os.environ.get("CEREBRAS_API_KEY", "")
        if not cerebras_key:
            print("ERROR: CEREBRAS_API_KEY not set")
            sys.exit(1)
        planner = CerebrasPlanner(
            cerebras_api_key=cerebras_key,
            chandra_api_key=chandra_key,
        )

    # Select challenges
    if args.ids:
        ids = [int(x) for x in args.ids.split(",")]
        challenges = [c for c in CHALLENGES if c.id in ids]
    else:
        challenges = CHALLENGES[:]

    # Switch output directory based on backend
    global RECORDINGS_DIR
    if args.azure:
        RECORDINGS_DIR = Path("recordings/azure_gpt5")
    elif args.no_chandra:
        RECORDINGS_DIR = Path("recordings/cerebras_pytesseract")
    RECORDINGS_DIR.mkdir(parents=True, exist_ok=True)

    ocr_mode = "pytesseract only (FREE)" if args.no_chandra else "Chandra + pytesseract"
    engine_label = planner.engine_name
    print(f"\n{'#' * 60}")
    print(f"  ScreenPilot x {engine_label}")
    print(f"  OCR: {ocr_mode}")
    print(f"  Challenges: {len(challenges)}")
    print(f"{'#' * 60}\n")

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

    for round_num in range(1, args.rounds + 1):
        print(f"\n{'━' * 60}")
        print(f"  ROUND {round_num}")
        print(f"{'━' * 60}")

        queue = [c for c in challenges if c.id not in existing or not existing[c.id]["success"]]
        if not queue:
            print("  All challenges passed!")
            break

        queue = queue[:6]
        print(f"  Running {len(queue)} challenges:")
        for c in queue:
            print(f"    #{c.id} {c.name} [{c.difficulty}]")

        for ci, challenge in enumerate(queue):
            attempt = existing.get(challenge.id, {}).get("attempt", 0) + 1
            if ci > 0:
                print(f"  [Cooldown] Waiting 30s before next challenge...")
                time.sleep(30)
            try:
                summary = run_single_challenge(
                    challenge, planner, speed=args.speed, attempt=attempt,
                )
                existing[challenge.id] = summary
            except Exception as e:
                print(f"\n  [FATAL] {e}")
                traceback.print_exc()
                if "credit" in str(e).lower() or "api_key" in str(e).lower():
                    print("  API issue. Stopping.")
                    update_viewer()
                    return

        update_viewer()
        passed = sum(1 for v in existing.values() if v["success"])
        total = len(existing)
        total_cost = sum(v.get("cost_usd", 0) for v in existing.values())
        print(f"\n  Round {round_num}: {passed}/{total} ({passed/total*100:.0f}%) | Total cost: ${total_cost:.4f}")

    update_viewer()
    passed = sum(1 for v in existing.values() if v["success"])
    total = len(existing)
    total_cost = sum(v.get("cost_usd", 0) for v in existing.values())
    print(f"\n{'#' * 60}")
    print(f"  COMPLETE: {passed}/{total} ({passed/total*100:.0f}%)")
    print(f"  Total cost: ${total_cost:.4f}")
    print(f"  Viewer: {RECORDINGS_DIR / 'viewer.html'}")
    print(f"{'#' * 60}")


if __name__ == "__main__":
    main()
