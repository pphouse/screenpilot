#!/usr/bin/env python3
"""
X (Twitter) AI関連日本株 ScreenPilotチャレンジ (デモ)
======================================================
ScreenPilotが視覚的にXでAI関連株のツイートを検索・読み取るチャレンジ。
Selenium cookie維持パターンで認証を引き継ぐ。

Usage:
    python examples/x_stock_challenge.py
    python examples/x_stock_challenge.py --ids 400,401
"""

import argparse
import json
import os
import sys
import time
from pathlib import Path

os.environ.setdefault("DISPLAY", ":99")

from screenpilot.agent import ScreenPilotAgent, StepResult, TaskResult
from screenpilot.config import ScreenPilotConfig

sys.path.insert(0, str(Path(__file__).parent))
from challenge_runner import (
    Challenge, StepLog, start_recording, stop_recording,
    generate_srt, postprocess_video, navigate_chrome, generate_viewer,
)
from x_stock_config import AI_STOCKS

# ============================================================================
# チャレンジ定義 (#400〜406)
# ============================================================================

STOCK_CHALLENGES = []
for i, stock in enumerate(AI_STOCKS):
    query = stock.search_queries[0] if stock.search_queries else stock.name
    cid = 400 + i
    STOCK_CHALLENGES.append(Challenge(
        id=cid,
        name=f"x_stock_{stock.name.replace(' ', '_').lower()}",
        difficulty="hard",
        goal=(
            f'X (Twitter) で「{query}」を検索する。'
            f'検索ボックスに「{query}」と入力してEnterを押す。'
            f'「最新」タブ(Latest)をクリックして最新ツイートを表示する。'
            f'表示されたツイートを3件以上読んで、内容をobservationで報告する。'
            f'Report done.'
        ),
        setup_url="https://x.com/explore",
        max_steps=15,
        tweet_text=f"AI日本株検索: {stock.name} ({stock.ticker})",
    ))

RECORDINGS_DIR = Path("recordings/x_stock_challenges")
RECORDINGS_DIR.mkdir(parents=True, exist_ok=True)


# ============================================================================
# チャレンジ実行
# ============================================================================

def run_stock_challenge(challenge: Challenge, speed: float = 3.0) -> dict:
    """1つの銘柄チャレンジを実行"""
    print(f"\n{'=' * 60}")
    print(f"Challenge #{challenge.id}: {challenge.name}")
    print(f"Goal: {challenge.goal[:100]}...")
    print(f"{'=' * 60}\n")

    output_dir = RECORDINGS_DIR / f"{challenge.id:03d}_{challenge.name}"
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
            "step": step.step_number,
            "action": step.action.action_type.value,
            "target": step.action.target or "",
            "coords": coords,
            "reasoning": reasoning[:200],
            "success": step.action_result.success,
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

    # Post-process video
    generate_srt(step_logs, srt_path)
    if not postprocess_video(raw_video, srt_path, final_video, speed=speed):
        if raw_video.exists():
            import shutil
            shutil.copy2(raw_video, final_video)

    input_tokens = getattr(agent.planner, "total_input_tokens", 0)
    output_tokens = getattr(agent.planner, "total_output_tokens", 0)
    cost_usd = getattr(agent.planner, "estimated_cost_usd", 0.0)

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
        "input_tokens": input_tokens,
        "output_tokens": output_tokens,
        "cost_usd": round(cost_usd, 4),
        "step_details": step_details,
    }

    status_str = "PASS" if result.success else "FAIL"
    print(f"\n  [{status_str}] {result.num_steps} steps | {result.total_time:.1f}s | Cost: ${cost_usd:.4f}")

    with open(output_dir / "summary.json", "w") as f:
        json.dump(summary, f, indent=2, ensure_ascii=False)

    return summary


def main():
    parser = argparse.ArgumentParser(description="X AI関連日本株 ScreenPilotチャレンジ")
    parser.add_argument("--ids", type=str, default=None,
                        help="実行するチャレンジID (カンマ区切り、例: 400,401,402)")
    parser.add_argument("--speed", type=float, default=3.0,
                        help="動画再生速度 (default: 3.0)")
    args = parser.parse_args()

    challenges = STOCK_CHALLENGES
    if args.ids:
        ids = [int(x) for x in args.ids.split(",")]
        challenges = [c for c in STOCK_CHALLENGES if c.id in ids]

    print("#" * 60)
    print("  X AI関連日本株 ScreenPilotチャレンジ")
    print(f"  対象: {len(challenges)}チャレンジ")
    print("#" * 60)

    results = []
    for challenge in challenges:
        try:
            summary = run_stock_challenge(challenge, speed=args.speed)
            results.append(summary)
        except Exception as e:
            print(f"  [FATAL] {e}")
            import traceback
            traceback.print_exc()

        # チャレンジ間の待機
        if challenge != challenges[-1]:
            time.sleep(3)

    # サマリー
    passed = sum(1 for r in results if r["success"])
    total = len(results)
    total_cost = sum(r["cost_usd"] for r in results)
    print(f"\n{'#' * 60}")
    print(f"  結果: {passed}/{total} PASS")
    print(f"  合計コスト: ${total_cost:.4f}")
    print(f"  動画: {RECORDINGS_DIR}")
    print(f"{'#' * 60}")

    # ビューア生成
    viewer = generate_viewer(results, recordings_dir=RECORDINGS_DIR)
    print(f"  Viewer: {viewer}")


if __name__ == "__main__":
    main()
