#!/usr/bin/env python3
"""
lisa_growth_runner.py — 自動成長デーモン
==========================================
各タスクをスケジュール通りに自動実行。
nohup起動、PIDファイルで管理、SIGTERM で graceful shutdown。

Usage:
    python3 examples/lisa_growth_runner.py              # フォアグラウンド実行
    python3 examples/lisa_growth_runner.py --daemon      # バックグラウンド実行
    python3 examples/lisa_growth_runner.py --stop        # 停止
    python3 examples/lisa_growth_runner.py --status      # ステータス確認
"""

import argparse
import json
import logging
import os
import random
import signal
import sys
import time
from datetime import datetime, timezone, timedelta
from pathlib import Path

os.environ.setdefault("DISPLAY", ":99")

sys.path.insert(0, str(Path(__file__).parent))

from lisa_growth_bot import run_task, TASK_FUNCTIONS, load_state, logger

# ============================================================================
# 定数
# ============================================================================

JST = timezone(timedelta(hours=9))
PID_FILE = Path("/tmp/lisa_growth.pid")
LAST_RUN_FILE = Path(__file__).parent / "lisa_growth_last_run.json"

# スケジュール設定 (分)
# リプに全振り。引用RTとオリジナルツイートは控えめ
SCHEDULE = {
    "x_reply_viral":  {"interval_min": 90,  "jitter_min": 30},
    "x_like":         {"interval_min": 120, "jitter_min": 30},
    "x_follow":       {"interval_min": 240, "jitter_min": 60},
    "x_tweet":        {"interval_min": 360, "jitter_min": 60},
    "x_quote_viral":  {"interval_min": 360, "jitter_min": 60},
    "room_like":      {"interval_min": 180, "jitter_min": 30},
    "room_collect":   {"interval_min": 480, "jitter_min": 60},
}

CHECK_INTERVAL = 300  # 5分ごとにチェック

ACTIVE_HOURS = (7, 23)  # JST

# ============================================================================
# 直近実行時刻管理
# ============================================================================

def load_last_run() -> dict:
    """各タスクの最終実行時刻を読み込む"""
    if LAST_RUN_FILE.exists():
        with open(LAST_RUN_FILE) as f:
            return json.load(f)
    return {}


def save_last_run(data: dict):
    """各タスクの最終実行時刻を保存"""
    with open(LAST_RUN_FILE, "w") as f:
        json.dump(data, f, indent=2)


def should_run(task_name: str, last_run: dict) -> bool:
    """タスクを今実行すべきか判定"""
    now = time.time()
    sched = SCHEDULE[task_name]
    interval_sec = sched["interval_min"] * 60
    jitter_sec = random.uniform(0, sched["jitter_min"] * 60)

    last_ts = last_run.get(task_name, 0)
    next_run = last_ts + interval_sec + jitter_sec

    return now >= next_run


# ============================================================================
# Graceful Shutdown
# ============================================================================

_shutdown = False


def _signal_handler(signum, frame):
    global _shutdown
    logger.info(f"シグナル {signum} 受信 — シャットダウン開始")
    _shutdown = True


signal.signal(signal.SIGTERM, _signal_handler)
signal.signal(signal.SIGINT, _signal_handler)

# ============================================================================
# メインループ
# ============================================================================

def run_loop():
    """メインスケジューラーループ"""
    logger.info("=" * 60)
    logger.info("  lisa growth runner 起動")
    logger.info(f"  チェック間隔: {CHECK_INTERVAL}秒")
    logger.info(f"  スケジュール:")
    for task, sched in SCHEDULE.items():
        logger.info(f"    {task}: {sched['interval_min']}分 (±{sched['jitter_min']}分)")
    logger.info("=" * 60)

    last_run = load_last_run()

    while not _shutdown:
        now_jst = datetime.now(JST)

        # 活動時間チェック
        if not (ACTIVE_HOURS[0] <= now_jst.hour < ACTIVE_HOURS[1]):
            logger.debug(f"活動時間外: {now_jst.strftime('%H:%M')} JST")
            time.sleep(CHECK_INTERVAL)
            continue

        # 各タスクをチェック
        for task_name in SCHEDULE:
            if _shutdown:
                break

            if not should_run(task_name, last_run):
                continue

            logger.info(f"スケジュール実行: {task_name}")

            try:
                success = run_task(task_name)
                if success:
                    last_run[task_name] = time.time()
                    save_last_run(last_run)
                    logger.info(f"{task_name}: 成功 — 次回 ~{SCHEDULE[task_name]['interval_min']}分後")
                else:
                    # 失敗しても最終実行時刻は更新 (リトライ嵐防止)
                    last_run[task_name] = time.time()
                    save_last_run(last_run)
                    logger.warning(f"{task_name}: 失敗")
            except Exception as e:
                logger.error(f"{task_name} 例外: {e}", exc_info=True)
                last_run[task_name] = time.time()
                save_last_run(last_run)

            # タスク間待機 (人間っぽく)
            if not _shutdown:
                wait = random.uniform(30, 120)
                logger.debug(f"次のタスクまで {wait:.0f}秒 待機")
                time.sleep(wait)

        # チェック間隔待機
        if not _shutdown:
            time.sleep(CHECK_INTERVAL)

    logger.info("lisa growth runner シャットダウン完了")


# ============================================================================
# デーモン管理
# ============================================================================

def start_daemon():
    """バックグラウンドで起動"""
    if PID_FILE.exists():
        pid = int(PID_FILE.read_text().strip())
        try:
            os.kill(pid, 0)
            print(f"既に実行中 (PID {pid})")
            return
        except ProcessLookupError:
            PID_FILE.unlink()

    pid = os.fork()
    if pid > 0:
        # 親プロセス
        print(f"lisa growth runner 起動 (PID {pid})")
        print(f"  ログ: /tmp/lisa_growth.log")
        print(f"  停止: python3 {__file__} --stop")
        sys.exit(0)

    # 子プロセス
    os.setsid()
    PID_FILE.write_text(str(os.getpid()))

    # stdout/stderr をログファイルにリダイレクト
    log_fd = open("/tmp/lisa_growth.log", "a")
    os.dup2(log_fd.fileno(), sys.stdout.fileno())
    os.dup2(log_fd.fileno(), sys.stderr.fileno())

    try:
        run_loop()
    finally:
        if PID_FILE.exists():
            PID_FILE.unlink()


def stop_daemon():
    """デーモンを停止"""
    if not PID_FILE.exists():
        print("実行中のプロセスが見つかりません")
        return

    pid = int(PID_FILE.read_text().strip())
    try:
        os.kill(pid, signal.SIGTERM)
        print(f"停止シグナル送信 (PID {pid})")

        # 終了を待つ (最大10秒)
        for _ in range(20):
            try:
                os.kill(pid, 0)
                time.sleep(0.5)
            except ProcessLookupError:
                print("停止完了")
                break
        else:
            print("強制終了")
            os.kill(pid, signal.SIGKILL)

    except ProcessLookupError:
        print("プロセスは既に停止しています")

    if PID_FILE.exists():
        PID_FILE.unlink()


def show_status():
    """ステータス表示"""
    # PID
    if PID_FILE.exists():
        pid = int(PID_FILE.read_text().strip())
        try:
            os.kill(pid, 0)
            print(f"ステータス: 実行中 (PID {pid})")
        except ProcessLookupError:
            print("ステータス: 停止 (PIDファイル残留)")
    else:
        print("ステータス: 停止")

    # 状態
    state = load_state()
    print(f"\n日付: {state.get('daily_date', 'N/A')}")
    print("本日の実行回数:")
    for task, limit in [("x_reply_viral", 8), ("x_quote_viral", 2),
                         ("x_tweet", 3), ("x_like", 20), ("x_follow", 5),
                         ("room_like", 20), ("room_collect", 2)]:
        count = state.get("daily_counts", {}).get(task, 0)
        print(f"  {task:15s}: {count}/{limit}")

    # 最終実行時刻
    last_run = load_last_run()
    if last_run:
        print("\n最終実行時刻:")
        for task, ts in sorted(last_run.items()):
            dt = datetime.fromtimestamp(ts, tz=JST)
            print(f"  {task:15s}: {dt.strftime('%Y-%m-%d %H:%M:%S')} JST")

    # エラー
    errs = state.get("consecutive_errors", {})
    if any(v > 0 for v in errs.values()):
        print("\n連続エラー:")
        for task, count in errs.items():
            if count > 0:
                print(f"  {task:15s}: {count}回")


# ============================================================================
# CLI
# ============================================================================

def main():
    parser = argparse.ArgumentParser(description="lisa growth runner")
    parser.add_argument("--daemon", action="store_true",
                        help="バックグラウンド実行")
    parser.add_argument("--stop", action="store_true",
                        help="実行中のデーモンを停止")
    parser.add_argument("--status", action="store_true",
                        help="ステータス表示")
    args = parser.parse_args()

    if args.stop:
        stop_daemon()
    elif args.status:
        show_status()
    elif args.daemon:
        start_daemon()
    else:
        # フォアグラウンド実行
        PID_FILE.write_text(str(os.getpid()))
        try:
            run_loop()
        finally:
            if PID_FILE.exists():
                PID_FILE.unlink()


if __name__ == "__main__":
    main()
