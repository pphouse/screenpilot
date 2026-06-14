#!/usr/bin/env python3
"""
X Actions Runner — like / reply / quote repost を成功するまで繰り返す
===================================================================
1. Selenium で Chrome を起動しクッキー注入（detach で維持）
2. ScreenPilot で各アクションを実行
3. 失敗時はリトライ（最大 MAX_RETRIES 回）
"""

import json
import os
import signal
import subprocess
import sys
import time
from dataclasses import dataclass
from pathlib import Path

os.environ.setdefault("DISPLAY", ":99")

sys.path.insert(0, str(Path(__file__).parent))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from screenpilot.agent import ScreenPilotAgent, StepResult, TaskResult
from screenpilot.config import ScreenPilotConfig, LLMConfig
from challenge_runner import (
    Challenge, StepLog, start_recording, stop_recording,
    generate_srt, postprocess_video,
)

# ============================================================================
# 設定
# ============================================================================

AUTH_TOKEN = os.environ.get("X_AUTH_TOKEN", "")
CT0 = os.environ.get("X_CT0", "")

MAX_RETRIES = 3
RECORDINGS_DIR = Path("recordings/x_actions")
RECORDINGS_DIR.mkdir(parents=True, exist_ok=True)

# ============================================================================
# タスク定義（改善版）
# ============================================================================

TASKS = [
    {
        "id": "like",
        "name": "x_like_tweet",
        "goal": (
            "You are viewing a specific tweet on X (Twitter). "
            "Your task is to click the heart/like button at the bottom of the tweet. "
            "The like button looks like a heart icon (♡) and is in the row of action buttons "
            "(reply, repost, like, bookmark, share) below the tweet text. "
            "Click it once. The heart should turn pink/red when liked. "
            "If it's already red/liked, scroll down to find another tweet and like that one instead. "
            "Report done once a tweet is successfully liked."
        ),
        "setup_url": "https://x.com/elaboratepost",  # Popular account with tweets
        "max_steps": 12,
        "desc_ja": "ツイートにいいね",
    },
    {
        "id": "reply",
        "name": "x_reply_tweet",
        "goal": (
            "You are viewing a tweet on X (Twitter). "
            "Your task is to reply to this tweet. Steps:\n"
            "1. Click the reply icon (speech bubble/💬) below the tweet text. "
            "   It's the first icon in the action row at the bottom of the tweet.\n"
            "2. A reply compose box will appear (either as a modal dialog or inline). "
            "   Click inside the text field that says 'Post your reply'.\n"
            "3. Type exactly: すごい！参考になります✨\n"
            "4. Click the blue 'Reply' or 'Post' button to submit.\n"
            "Report done once the reply is posted."
        ),
        "setup_url": "https://x.com/elaboratepost",
        "max_steps": 15,
        "desc_ja": "ツイートにリプライ",
    },
    {
        "id": "quote",
        "name": "x_quote_repost",
        "goal": (
            "You are viewing a tweet on X (Twitter). "
            "Your task is to quote repost (引用リポスト) this tweet. Steps:\n"
            "1. Click the repost icon (two arrows ♻/🔁) below the tweet. "
            "   It's the second icon from left in the action row.\n"
            "2. A small popup menu will appear with two options: 'Repost' and 'Quote'. "
            "   Click 'Quote' (not 'Repost').\n"
            "3. A compose window will appear showing the original tweet embedded. "
            "   Click in the text area and type: これ面白い！みんなも見てね😊\n"
            "4. Click the blue 'Post' button to submit the quote repost.\n"
            "Report done once posted."
        ),
        "setup_url": "https://x.com/elaboratepost",
        "max_steps": 15,
        "desc_ja": "引用リポスト",
    },
]


# ============================================================================
# Chrome + Cookie 管理
# ============================================================================

_DRIVER = None  # Global Selenium driver

def ensure_chrome_with_cookies():
    """Chrome をクッキー付きで起動し、X にログイン済みか確認。ドライバーを返す。"""
    global _DRIVER
    from selenium import webdriver
    from selenium.webdriver.chrome.options import Options
    from selenium.webdriver.common.by import By
    from selenium.webdriver.support.ui import WebDriverWait
    from selenium.webdriver.support import expected_conditions as EC

    opts = Options()
    opts.binary_location = "/usr/bin/google-chrome-stable"
    opts.add_argument("--no-sandbox")
    opts.add_argument("--disable-dev-shm-usage")
    opts.add_argument("--window-size=1920,1080")
    opts.add_argument("--disable-blink-features=AutomationControlled")
    opts.add_experimental_option("excludeSwitches", ["enable-automation"])
    opts.add_experimental_option("detach", True)  # Keep Chrome running

    driver = webdriver.Chrome(options=opts)
    driver.execute_cdp_cmd("Page.addScriptToEvaluateOnNewDocument", {
        "source": "Object.defineProperty(navigator, 'webdriver', {get: () => undefined})"
    })

    # Inject cookies
    driver.get("https://x.com")
    time.sleep(2)
    for name, value in [("auth_token", AUTH_TOKEN), ("ct0", CT0)]:
        driver.add_cookie({
            "name": name, "value": value,
            "domain": ".x.com", "path": "/", "secure": True,
        })

    # Verify login
    driver.get("https://x.com/home")
    time.sleep(4)

    try:
        WebDriverWait(driver, 10).until(
            EC.presence_of_element_located((By.CSS_SELECTOR, '[data-testid="primaryColumn"]'))
        )
        print("✓ X ログイン成功 (@lisapyo3274)")

        tweets = driver.find_elements(By.CSS_SELECTOR, 'article[data-testid="tweet"]')
        print(f"  タイムラインに {len(tweets)} 件のツイートが表示されています")

        _DRIVER = driver
        return True
    except Exception as e:
        print(f"✗ ログイン失敗: {e}")
        driver.quit()
        return False


def navigate_to(url: str):
    """Selenium ドライバーで URL に遷移 (xdotool を使わない)。"""
    global _DRIVER
    if _DRIVER:
        _DRIVER.get(url)
        time.sleep(4)
    else:
        # Fallback: xdotool
        subprocess.run(
            ["xdotool", "search", "--onlyvisible", "--name", "Chrome", "windowactivate"],
            capture_output=True, timeout=5,
        )
        time.sleep(0.3)
        subprocess.run(["xdotool", "key", "ctrl+l"], capture_output=True, timeout=3)
        time.sleep(0.3)
        subprocess.run(["xdotool", "type", "--clearmodifiers", url],
                        capture_output=True, timeout=5)
        subprocess.run(["xdotool", "key", "Return"], capture_output=True, timeout=3)
        time.sleep(4)


# ============================================================================
# ScreenPilot 実行
# ============================================================================

def run_task(task: dict, attempt: int = 1) -> dict:
    """ScreenPilot でタスクを実行。"""
    task_id = task["id"]
    name = task["name"]
    goal = task["goal"]
    setup_url = task["setup_url"]
    max_steps = task["max_steps"]

    suffix = f"_v{attempt}" if attempt > 1 else ""
    output_dir = RECORDINGS_DIR / f"{name}{suffix}"
    output_dir.mkdir(parents=True, exist_ok=True)
    raw_video = output_dir / "recording_raw.mp4"
    srt_path = output_dir / "reasoning.srt"
    final_video = output_dir / "recording.mp4"

    print(f"\n{'='*60}")
    print(f"  [{task_id.upper()}] attempt={attempt} | {task['desc_ja']}")
    print(f"  URL: {setup_url}")
    print(f"{'='*60}")

    # Navigate using Selenium driver (avoids xdotool conflicts)
    navigate_to(setup_url)
    time.sleep(2)

    # Start recording
    recorder = start_recording(raw_video)
    rec_start = time.time()
    time.sleep(1)

    # Create ScreenPilot agent with Claude Code CLI backend
    cc_model = os.environ.get("CLAUDE_CODE_MODEL", "claude-sonnet-4-6")
    llm = LLMConfig(
        provider="claude_code",
        model=cc_model,
        max_tokens=4096,
        temperature=0.0,
    )
    config = ScreenPilotConfig(llm=llm)
    config.executor.screenshot_after_action = True
    agent = ScreenPilotAgent(config)

    step_logs = []
    step_details = []

    def on_step(step: StepResult):
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
        })
        print(f"    Step {step.step_number}: {step.action.action_type.value} {coords} [{status}] {reasoning[:60]}")

        if step.screenshot_before:
            step.screenshot_before.save(str(output_dir / f"step{step.step_number:02d}_before.png"))
        if step.screenshot_after:
            step.screenshot_after.save(str(output_dir / f"step{step.step_number:02d}_after.png"))

    agent.on_step(on_step)

    start_time = time.time()
    try:
        result = agent.run(goal, max_steps=max_steps)
    except Exception as e:
        print(f"    [ERROR] {e}")
        result = TaskResult(goal=goal, success=False, error=str(e),
                            total_time=time.time() - start_time)

    time.sleep(2)
    stop_recording(recorder)

    # Post-process video
    generate_srt(step_logs, srt_path)
    postprocess_video(raw_video, srt_path, final_video, speed=3.0)

    status_str = "PASS ✓" if result.success else "FAIL ✗"
    print(f"\n  [{status_str}] {result.num_steps} steps | {result.total_time:.1f}s")

    summary = {
        "task_id": task_id,
        "name": name,
        "attempt": attempt,
        "success": result.success,
        "steps": result.num_steps,
        "time": round(result.total_time, 1),
        "error": result.error,
        "step_details": step_details,
    }
    with open(output_dir / "summary.json", "w") as f:
        json.dump(summary, f, indent=2, ensure_ascii=False)

    return summary


# ============================================================================
# メインループ
# ============================================================================

def main():
    print("=" * 60)
    print("  X Actions Runner — like / reply / quote repost")
    print("=" * 60)

    # Step 1: Ensure Chrome with cookies
    print("\n[1/2] Chrome + クッキー設定...")
    if not ensure_chrome_with_cookies():
        print("クッキーが無効です。新しいクッキーが必要です。")
        sys.exit(1)

    # Step 2: Run each task with retries
    print("\n[2/2] タスク実行開始...\n")
    results = {}

    for task in TASKS:
        task_id = task["id"]
        for attempt in range(1, MAX_RETRIES + 1):
            summary = run_task(task, attempt)
            if summary["success"]:
                results[task_id] = "PASS"
                print(f"\n  ★ {task['desc_ja']} — 成功！ (attempt {attempt})")
                break
            else:
                print(f"\n  ✗ {task['desc_ja']} — 失敗 (attempt {attempt}/{MAX_RETRIES})")
                if attempt < MAX_RETRIES:
                    print(f"    10秒後にリトライします...")
                    time.sleep(10)
        else:
            results[task_id] = "FAIL"
            print(f"\n  ✗✗ {task['desc_ja']} — {MAX_RETRIES}回全て失敗")

    # Summary
    print("\n" + "=" * 60)
    print("  最終結果")
    print("=" * 60)
    for task in TASKS:
        tid = task["id"]
        status = results.get(tid, "SKIP")
        icon = "✓" if status == "PASS" else "✗"
        print(f"  {icon} {task['desc_ja']:20s} [{status}]")

    passed = sum(1 for v in results.values() if v == "PASS")
    print(f"\n  合計: {passed}/{len(TASKS)} PASS")


if __name__ == "__main__":
    main()
