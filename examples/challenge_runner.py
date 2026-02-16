#!/usr/bin/env python3
"""
ScreenPilot Challenge Runner v2
=================================
Runs ScreenPilot agent on real tasks while recording the Xvfb screen with ffmpeg.
Captures LLM reasoning as SRT subtitles and burns them into the video.
Produces speed-adjusted final videos with telop overlay.

Usage:
    python examples/challenge_runner.py --list
    python examples/challenge_runner.py --challenge 15
    python examples/challenge_runner.py --from-id 15 --to-id 16
    python examples/challenge_runner.py --speed 3
"""

import argparse
import json
import os
import signal
import subprocess
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path

os.environ.setdefault("DISPLAY", ":99")

from screenpilot.agent import ScreenPilotAgent, StepResult, TaskResult
from screenpilot.config import ScreenPilotConfig


RECORDINGS_DIR = Path("recordings/challenges")
RECORDINGS_DIR.mkdir(parents=True, exist_ok=True)


@dataclass
class Challenge:
    id: int
    name: str
    difficulty: str
    goal: str
    setup_url: str
    max_steps: int
    description: str


@dataclass
class StepLog:
    """Detailed log of a single step for telop generation."""
    step_number: int
    action_type: str
    target: str
    coords: str
    reasoning: str
    success: bool
    timestamp: float  # seconds since recording start


CHALLENGES = [
    # --- Round 1: GitHub ---
    Challenge(1, "click_issues_tab", "easy",
              "Click on the Issues tab in the GitHub repository page",
              "https://github.com/pphouse/screenpilot", 10,
              "Navigate from repo main page to Issues tab by clicking"),
    Challenge(2, "navigate_to_discussions", "easy",
              "Click on the Discussions tab in the GitHub repository page",
              "https://github.com/pphouse/screenpilot", 10,
              "Navigate from repo main page to Discussions tab"),
    Challenge(3, "star_count_check", "medium",
              'Find and click on the "Code" tab, then scroll down to read the README',
              "https://github.com/pphouse/screenpilot/issues", 15,
              "Start from Issues page, navigate to Code tab and scroll to README"),
    Challenge(4, "search_github", "medium",
              'Use the GitHub search bar to search for "screenpilot" and press Enter',
              "https://github.com", 15,
              "Navigate GitHub search from the homepage"),
    Challenge(5, "open_file_in_repo", "hard",
              'Navigate to the "screenpilot" folder, then click on "agent.py" to view the file',
              "https://github.com/pphouse/screenpilot", 20,
              "Browse the repo file tree and open a specific Python file"),
    Challenge(6, "wikipedia_search", "hard",
              'Go to the Wikipedia search box, type "artificial intelligence", and press Enter to search',
              "https://en.wikipedia.org", 15,
              "Search Wikipedia for a topic using the search box"),
    Challenge(7, "multi_step_navigation", "expert",
              "Navigate to the Issues page, click on issue #2, then go back to the main Code page",
              "https://github.com/pphouse/screenpilot", 25,
              "Multi-step navigation: repo → issues → issue detail → back to code"),
    # --- Round 2: Diverse sites ---
    Challenge(8, "yahoo_finance_stock", "medium",
              'Type "AAPL" in the search/quote box and press Enter to look up Apple stock price',
              "https://finance.yahoo.com", 15,
              "Look up Apple stock price on Yahoo Finance"),
    Challenge(9, "hackernews_browse", "easy",
              "Click on the 2nd story link on the Hacker News front page to read the article",
              "https://news.ycombinator.com", 10,
              "Browse and click a story on Hacker News"),
    Challenge(10, "youtube_search", "hard",
              'Click the search box at the top, type "screenpilot demo", and press Enter to search',
              "https://www.youtube.com", 15,
              "Search for a video on YouTube"),
    Challenge(11, "reddit_browse", "medium",
              "Scroll down to see more posts, then click on any post title to open it",
              "https://old.reddit.com/r/programming", 15,
              "Browse r/programming on old Reddit and open a post"),
    Challenge(12, "google_search", "medium",
              'Type "ScreenPilot AI desktop automation" in the Google search box and press Enter',
              "https://www.google.com", 12,
              "Perform a Google search query"),
    Challenge(13, "weather_check", "hard",
              'Type "Tokyo" in the search box and search to see the weather forecast for Tokyo',
              "https://wttr.in", 12,
              "Check weather forecast for Tokyo"),
    Challenge(14, "wikipedia_jp_navigate", "expert",
              'Search for "人工知能" (artificial intelligence in Japanese), then click the first link in the article body',
              "https://ja.wikipedia.org", 20,
              "Search Japanese Wikipedia and follow a link in the article"),
    # --- Round 3: New unique challenges ---
    Challenge(15, "youtube_search_v2", "hard",
              'Use keyboard shortcut "/" to focus the YouTube search box, then type "python tutorial" and press Enter',
              "https://www.youtube.com", 12,
              "YouTube search using keyboard shortcut (retry with better strategy)"),
    Challenge(16, "google_trends", "hard",
              'Click on the search/explore bar, type "ChatGPT", and press Enter to see the trend',
              "https://trends.google.com/trending?geo=US", 15,
              "Look up ChatGPT trend on Google Trends"),
    Challenge(17, "hn_top_comments", "medium",
              "Click on the 'comments' link of the top story to view the discussion",
              "https://news.ycombinator.com", 10,
              "Navigate to HN comment thread of top story"),
    Challenge(18, "github_trending", "medium",
              "Scroll down to see trending repositories and click on the first repo name",
              "https://github.com/trending", 12,
              "Browse GitHub Trending and open a popular repo"),
]


# ---------------------------------------------------------------------------
# Recording & video processing
# ---------------------------------------------------------------------------

def start_recording(output_path: Path, display: str = ":99", fps: int = 10) -> subprocess.Popen:
    cmd = [
        "ffmpeg", "-y", "-f", "x11grab",
        "-framerate", str(fps), "-video_size", "1920x1080",
        "-i", display,
        "-c:v", "libx264", "-preset", "ultrafast", "-crf", "28",
        "-pix_fmt", "yuv420p",
        str(output_path),
    ]
    proc = subprocess.Popen(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    time.sleep(0.5)
    return proc


def stop_recording(proc: subprocess.Popen) -> None:
    proc.send_signal(signal.SIGINT)
    try:
        proc.wait(timeout=10)
    except subprocess.TimeoutExpired:
        proc.kill()


def generate_srt(step_logs: list[StepLog], output_path: Path) -> None:
    """Generate SRT subtitle file from step logs."""
    lines = []
    for i, step in enumerate(step_logs):
        start = step.timestamp
        # End: either next step's start or +4 seconds
        end = step_logs[i + 1].timestamp if i + 1 < len(step_logs) else start + 4.0

        def fmt_time(t: float) -> str:
            h = int(t // 3600)
            m = int((t % 3600) // 60)
            s = int(t % 60)
            ms = int((t % 1) * 1000)
            return f"{h:02d}:{m:02d}:{s:02d},{ms:03d}"

        # Truncate reasoning to fit on screen
        reasoning = step.reasoning[:120].replace("\n", " ")
        status = "OK" if step.success else "FAIL"
        text = f"Step {step.step_number}: {step.action_type} {step.coords} [{status}]\\N{reasoning}"

        lines.append(f"{i + 1}")
        lines.append(f"{fmt_time(start)} --> {fmt_time(end)}")
        lines.append(text)
        lines.append("")

    output_path.write_text("\n".join(lines), encoding="utf-8")


def postprocess_video(
    raw_path: Path, srt_path: Path, output_path: Path, speed: float = 2.0
) -> bool:
    """Burn subtitles and apply speed-up to create final video."""
    if not raw_path.exists():
        return False

    # Build subtitle filter with styling
    srt_escaped = str(srt_path).replace(":", "\\:").replace("'", "\\'")
    sub_filter = (
        f"subtitles='{srt_escaped}':force_style="
        f"'FontSize=18,FontName=Arial,PrimaryColour=&H00FFFFFF,"
        f"OutlineColour=&H00000000,Outline=2,Shadow=1,"
        f"MarginV=40,Alignment=2'"
    )

    # Speed filter
    speed_filter = f"setpts={1/speed}*PTS"

    # Combine filters
    vf = f"{sub_filter},{speed_filter}"

    cmd = [
        "ffmpeg", "-y", "-i", str(raw_path),
        "-vf", vf,
        "-c:v", "libx264", "-preset", "fast", "-crf", "23",
        "-pix_fmt", "yuv420p",
        "-an",  # no audio
        str(output_path),
    ]
    result = subprocess.run(cmd, capture_output=True, timeout=120)
    return output_path.exists() and output_path.stat().st_size > 0


# ---------------------------------------------------------------------------
# Chrome navigation
# ---------------------------------------------------------------------------

def navigate_chrome(url: str) -> None:
    subprocess.run(
        ["xdotool", "search", "--onlyvisible", "--name", "Chrome", "windowactivate"],
        capture_output=True, timeout=5,
    )
    time.sleep(0.3)
    subprocess.run(["xdotool", "key", "ctrl+l"], capture_output=True, timeout=5)
    time.sleep(0.3)
    subprocess.run(["xdotool", "type", "--clearmodifiers", url], capture_output=True, timeout=10)
    time.sleep(0.2)
    subprocess.run(["xdotool", "key", "Return"], capture_output=True, timeout=5)
    time.sleep(3)


# ---------------------------------------------------------------------------
# Challenge execution
# ---------------------------------------------------------------------------

def run_challenge(challenge: Challenge, speed: float = 2.0) -> dict:
    print(f"\n{'=' * 60}")
    print(f"Challenge #{challenge.id}: {challenge.name}")
    print(f"Difficulty: {challenge.difficulty.upper()}")
    print(f"Goal: {challenge.goal}")
    print(f"{'=' * 60}\n")

    output_dir = RECORDINGS_DIR / f"{challenge.id:02d}_{challenge.name}"
    output_dir.mkdir(parents=True, exist_ok=True)
    raw_video = output_dir / "recording_raw.mp4"
    srt_path = output_dir / "reasoning.srt"
    final_video = output_dir / "recording.mp4"

    # Navigate
    print(f"[Setup] Navigating to {challenge.setup_url}...")
    navigate_chrome(challenge.setup_url)
    time.sleep(2)

    # Start recording
    print(f"[Recording] Starting screen capture...")
    recorder = start_recording(raw_video)
    rec_start = time.time()
    time.sleep(1.5)

    # Run agent
    print(f"[Agent] Starting ScreenPilot (max_steps={challenge.max_steps})...")
    config = ScreenPilotConfig()
    config.executor.screenshot_after_action = True
    agent = ScreenPilotAgent(config)

    step_logs: list[StepLog] = []
    step_details: list[dict] = []

    def on_step(step: StepResult) -> None:
        ts = time.time() - rec_start
        status = "OK" if step.action_result.success else "FAIL"
        coords = ""
        if step.action.x is not None:
            coords = f"({step.action.x}, {step.action.y})"
        reasoning = step.action.reasoning or ""

        step_logs.append(StepLog(
            step_number=step.step_number,
            action_type=step.action.action_type.value,
            target=step.action.target or "",
            coords=coords,
            reasoning=reasoning,
            success=step.action_result.success,
            timestamp=ts,
        ))
        step_details.append({
            "step": step.step_number,
            "action": step.action.action_type.value,
            "target": step.action.target or "",
            "coords": coords,
            "reasoning": reasoning[:200],
            "success": step.action_result.success,
            "timestamp": round(ts, 1),
        })

        print(f"  Step {step.step_number}: {step.action.action_type.value} {coords} [{status}]")
        if reasoning:
            print(f"    → {reasoning[:80]}")

        # Save screenshots
        if step.screenshot_before:
            step.screenshot_before.save(str(output_dir / f"step{step.step_number:02d}_before.png"))
        if step.screenshot_after:
            step.screenshot_after.save(str(output_dir / f"step{step.step_number:02d}_after.png"))

    agent.on_step(on_step)

    start_time = time.time()
    try:
        result = agent.run(challenge.goal, max_steps=challenge.max_steps)
    except Exception as e:
        print(f"  [ERROR] Agent crashed: {e}")
        result = TaskResult(
            goal=challenge.goal, success=False, error=str(e),
            total_time=time.time() - start_time,
        )

    time.sleep(2)
    stop_recording(recorder)

    # Generate SRT subtitles
    print(f"[Subtitles] Generating SRT with {len(step_logs)} steps...")
    generate_srt(step_logs, srt_path)

    # Post-process: burn subtitles + speed up
    print(f"[Video] Burning subtitles and applying {speed}x speed...")
    if postprocess_video(raw_video, srt_path, final_video, speed=speed):
        raw_size = raw_video.stat().st_size / 1024
        final_size = final_video.stat().st_size / 1024
        print(f"  Raw: {raw_size:.0f} KB → Final: {final_size:.0f} KB ({speed}x speed)")
        # Keep raw for re-processing, but it's optional
    else:
        print(f"  [WARN] Post-processing failed, keeping raw video")
        # Fallback: rename raw to final
        if raw_video.exists():
            import shutil
            shutil.copy2(raw_video, final_video)

    # Summary
    video_size = final_video.stat().st_size / 1024 if final_video.exists() else 0
    summary = {
        "challenge_id": challenge.id,
        "name": challenge.name,
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
        "step_details": step_details,
    }

    status_str = "PASS" if result.success else "FAIL"
    print(f"\n[Result] {status_str} | {result.num_steps} steps | {result.total_time:.1f}s | Video: {video_size:.0f} KB")

    with open(output_dir / "summary.json", "w") as f:
        json.dump(summary, f, indent=2, ensure_ascii=False)

    return summary


# ---------------------------------------------------------------------------
# HTML Viewer generation
# ---------------------------------------------------------------------------

def generate_viewer(results: list[dict]) -> Path:
    """Generate an HTML viewer for all challenge results."""
    viewer_path = RECORDINGS_DIR / "viewer.html"

    # Build challenge cards
    cards_html = ""
    for r in results:
        status_class = "pass" if r["success"] else "fail"
        status_text = "PASS" if r["success"] else "FAIL"
        video_rel = Path(r["video_path"]).name if "/" not in r["video_path"] else \
            str(Path(r["video_path"]).relative_to(RECORDINGS_DIR))

        # Step timeline
        steps_html = ""
        for s in r.get("step_details", []):
            s_class = "step-ok" if s["success"] else "step-fail"
            steps_html += f"""<div class="step {s_class}" title="{s['reasoning'][:100]}">
                <span class="step-num">#{s['step']}</span>
                <span class="step-action">{s['action']}</span>
                <span class="step-coords">{s['coords']}</span>
                <span class="step-time">{s['timestamp']}s</span>
            </div>"""

        error_html = f'<div class="error">{r["error"]}</div>' if r.get("error") else ""

        cards_html += f"""
        <div class="card {status_class}">
            <div class="card-header">
                <span class="challenge-id">#{r['challenge_id']}</span>
                <span class="difficulty {r['difficulty']}">{r['difficulty'].upper()}</span>
                <span class="status-badge {status_class}">{status_text}</span>
                <h3>{r['name']}</h3>
            </div>
            <div class="card-meta">
                <span>Goal: {r.get('goal', '')}</span>
            </div>
            <div class="card-stats">
                <span>{r['steps']} steps</span>
                <span>{r['time']}s</span>
                <span>{r.get('speed', 1)}x speed</span>
                <span>{r['video_size_kb']} KB</span>
            </div>
            {error_html}
            <div class="video-container">
                <video controls preload="metadata" width="100%">
                    <source src="{video_rel}" type="video/mp4">
                </video>
                <div class="video-controls">
                    <button onclick="this.closest('.card').querySelector('video').playbackRate=0.5">0.5x</button>
                    <button onclick="this.closest('.card').querySelector('video').playbackRate=1">1x</button>
                    <button onclick="this.closest('.card').querySelector('video').playbackRate=2">2x</button>
                    <button onclick="this.closest('.card').querySelector('video').playbackRate=4">4x</button>
                </div>
            </div>
            <details class="steps-detail">
                <summary>Step-by-step reasoning ({len(r.get('step_details', []))} steps)</summary>
                <div class="steps-timeline">{steps_html}</div>
            </details>
        </div>
        """

    passed = sum(1 for r in results if r["success"])
    total = len(results)

    html = f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>ScreenPilot Challenge Viewer</title>
<style>
* {{ margin: 0; padding: 0; box-sizing: border-box; }}
body {{ font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif;
       background: #0d1117; color: #c9d1d9; padding: 20px; }}
h1 {{ color: #58a6ff; margin-bottom: 8px; }}
.subtitle {{ color: #8b949e; margin-bottom: 20px; }}
.summary-bar {{ display: flex; gap: 20px; margin-bottom: 24px; padding: 16px;
               background: #161b22; border: 1px solid #30363d; border-radius: 8px; }}
.summary-stat {{ text-align: center; }}
.summary-stat .value {{ font-size: 28px; font-weight: bold; color: #58a6ff; }}
.summary-stat .label {{ font-size: 12px; color: #8b949e; }}
.filters {{ margin-bottom: 20px; display: flex; gap: 8px; flex-wrap: wrap; }}
.filters button {{ padding: 6px 14px; border: 1px solid #30363d; background: #21262d;
                  color: #c9d1d9; border-radius: 20px; cursor: pointer; font-size: 13px; }}
.filters button:hover, .filters button.active {{ background: #388bfd; border-color: #388bfd; color: white; }}
.grid {{ display: grid; grid-template-columns: repeat(auto-fill, minmax(560px, 1fr)); gap: 20px; }}
.card {{ background: #161b22; border: 1px solid #30363d; border-radius: 10px;
        padding: 16px; transition: 0.2s; }}
.card:hover {{ border-color: #58a6ff; }}
.card.pass {{ border-left: 4px solid #3fb950; }}
.card.fail {{ border-left: 4px solid #f85149; }}
.card-header {{ display: flex; align-items: center; gap: 8px; margin-bottom: 8px; flex-wrap: wrap; }}
.challenge-id {{ color: #8b949e; font-weight: bold; }}
.difficulty {{ padding: 2px 8px; border-radius: 12px; font-size: 11px; font-weight: bold; }}
.difficulty.easy {{ background: #238636; color: white; }}
.difficulty.medium {{ background: #9e6a03; color: white; }}
.difficulty.hard {{ background: #da3633; color: white; }}
.difficulty.expert {{ background: #8957e5; color: white; }}
.status-badge {{ padding: 2px 10px; border-radius: 12px; font-size: 12px; font-weight: bold; }}
.status-badge.pass {{ background: #238636; color: white; }}
.status-badge.fail {{ background: #da3633; color: white; }}
h3 {{ color: #e6edf3; font-size: 15px; }}
.card-meta {{ font-size: 13px; color: #8b949e; margin-bottom: 8px; }}
.card-stats {{ display: flex; gap: 16px; font-size: 13px; color: #58a6ff; margin-bottom: 8px; }}
.error {{ font-size: 12px; color: #f85149; margin-bottom: 8px; padding: 6px;
         background: #1c0c0c; border-radius: 4px; }}
.video-container {{ margin: 12px 0; }}
video {{ border-radius: 6px; background: #000; }}
.video-controls {{ display: flex; gap: 6px; margin-top: 6px; }}
.video-controls button {{ padding: 4px 12px; background: #21262d; border: 1px solid #30363d;
                         color: #c9d1d9; border-radius: 4px; cursor: pointer; font-size: 12px; }}
.video-controls button:hover {{ background: #388bfd; }}
.steps-detail {{ margin-top: 8px; }}
summary {{ cursor: pointer; color: #58a6ff; font-size: 13px; }}
.steps-timeline {{ margin-top: 8px; max-height: 300px; overflow-y: auto; }}
.step {{ padding: 6px 8px; border-left: 3px solid #30363d; margin-bottom: 4px;
        font-size: 12px; font-family: monospace; display: flex; gap: 8px; align-items: center; }}
.step.step-ok {{ border-left-color: #3fb950; }}
.step.step-fail {{ border-left-color: #f85149; }}
.step-num {{ color: #8b949e; min-width: 30px; }}
.step-action {{ color: #79c0ff; min-width: 100px; }}
.step-coords {{ color: #d2a8ff; min-width: 80px; }}
.step-time {{ color: #8b949e; margin-left: auto; }}
</style>
</head>
<body>
<h1>ScreenPilot Challenge Viewer</h1>
<p class="subtitle">AI agent attempting real browser tasks — vision + LLM, no scripting</p>

<div class="summary-bar">
    <div class="summary-stat"><div class="value">{passed}/{total}</div><div class="label">Passed</div></div>
    <div class="summary-stat"><div class="value">{total}</div><div class="label">Total</div></div>
    <div class="summary-stat"><div class="value">{passed/total*100:.0f}%</div><div class="label">Pass Rate</div></div>
</div>

<div class="filters">
    <button class="active" onclick="filterCards('all', this)">All</button>
    <button onclick="filterCards('pass', this)">Passed</button>
    <button onclick="filterCards('fail', this)">Failed</button>
    <button onclick="filterCards('easy', this)">Easy</button>
    <button onclick="filterCards('medium', this)">Medium</button>
    <button onclick="filterCards('hard', this)">Hard</button>
    <button onclick="filterCards('expert', this)">Expert</button>
</div>

<div class="grid" id="grid">
{cards_html}
</div>

<script>
function filterCards(filter, btn) {{
    document.querySelectorAll('.filters button').forEach(b => b.classList.remove('active'));
    btn.classList.add('active');
    document.querySelectorAll('.card').forEach(card => {{
        if (filter === 'all') {{ card.style.display = ''; return; }}
        if (['pass','fail'].includes(filter)) {{
            card.style.display = card.classList.contains(filter) ? '' : 'none';
        }} else {{
            card.style.display = card.querySelector('.difficulty.' + filter) ? '' : 'none';
        }}
    }});
}}
</script>
</body>
</html>"""

    viewer_path.write_text(html, encoding="utf-8")
    return viewer_path


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(description="ScreenPilot Challenge Runner v2")
    parser.add_argument("--challenge", "-c", type=int, default=None,
                        help="Run a specific challenge by ID")
    parser.add_argument("--from-id", type=int, default=1)
    parser.add_argument("--to-id", type=int, default=None)
    parser.add_argument("--speed", "-s", type=float, default=3.0,
                        help="Video speed multiplier (default: 3x)")
    parser.add_argument("--list", "-l", action="store_true")
    parser.add_argument("--viewer-only", action="store_true",
                        help="Only regenerate HTML viewer from existing summaries")
    args = parser.parse_args()

    if args.list:
        print(f"\n{'ID':<4} {'Diff':<8} {'Name':<28} Description")
        print("-" * 75)
        for c in CHALLENGES:
            print(f"{c.id:<4} {c.difficulty:<8} {c.name:<28} {c.description}")
        return

    if args.viewer_only:
        # Load all existing summaries
        results = []
        for d in sorted(RECORDINGS_DIR.iterdir()):
            s = d / "summary.json"
            if s.exists():
                results.append(json.loads(s.read_text()))
        if results:
            viewer = generate_viewer(results)
            print(f"Viewer generated: {viewer}")
        else:
            print("No summaries found.")
        return

    if args.challenge:
        challenges = [c for c in CHALLENGES if c.id == args.challenge]
        if not challenges:
            print(f"Challenge {args.challenge} not found. Use --list.")
            sys.exit(1)
    else:
        to_id = args.to_id or max(c.id for c in CHALLENGES)
        challenges = [c for c in CHALLENGES if args.from_id <= c.id <= to_id]

    print(f"\nScreenPilot Challenge Runner v2")
    print(f"Running {len(challenges)} challenge(s) at {args.speed}x speed")
    print(f"Recordings: {RECORDINGS_DIR.resolve()}\n")

    results = []
    for challenge in challenges:
        summary = run_challenge(challenge, speed=args.speed)
        results.append(summary)

    # Also load previous results for the viewer
    all_results = {}
    for d in sorted(RECORDINGS_DIR.iterdir()):
        s = d / "summary.json"
        if s.exists():
            data = json.loads(s.read_text())
            all_results[data["challenge_id"]] = data
    # Overwrite with current run
    for r in results:
        all_results[r["challenge_id"]] = r
    all_sorted = [all_results[k] for k in sorted(all_results.keys())]

    # Final report
    print(f"\n{'=' * 60}")
    print(f"RUN REPORT")
    print(f"{'=' * 60}")
    passed = sum(1 for r in results if r["success"])
    total = len(results)
    print(f"This run: {passed}/{total}")
    for r in results:
        st = "PASS" if r["success"] else "FAIL"
        print(f"  #{r['challenge_id']} [{r['difficulty']:<6}] {r['name']:<28} {st} ({r['steps']} steps, {r['time']}s)")

    # Generate viewer
    viewer = generate_viewer(all_sorted)
    print(f"\nViewer: {viewer}")

    # Save combined report
    report_path = RECORDINGS_DIR / "report.json"
    with open(report_path, "w") as f:
        json.dump({"results": all_sorted, "passed": sum(1 for r in all_sorted if r["success"]),
                    "total": len(all_sorted)}, f, indent=2, ensure_ascii=False)
    print(f"Report: {report_path}")


if __name__ == "__main__":
    main()
