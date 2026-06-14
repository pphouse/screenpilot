#!/usr/bin/env python3
"""
lisa_growth_bot.py — X + 楽天ROOM 自動成長エンジン
====================================================
タスク: x_tweet, x_like, x_follow, room_like, room_collect
各タスクを個別実行 or runner.py からスケジュール呼び出し

Usage:
    python3 examples/lisa_growth_bot.py --task x_like
    python3 examples/lisa_growth_bot.py --task x_tweet --dry-run
    python3 examples/lisa_growth_bot.py --task x_tweet --count 3
"""

import argparse
import json
import logging
import os
import random
import re
import sys
import time
from datetime import datetime, timezone, timedelta
from pathlib import Path
from urllib.parse import quote_plus

os.environ.setdefault("DISPLAY", ":99")

sys.path.insert(0, str(Path(__file__).parent))

from lisa_growth_data import (
    LIKE_QUERIES, FOLLOW_TARGET_ACCOUNTS, PRODUCTS,
    generate_tweet, CATEGORY_ORDER,
    VIRAL_QUERIES, REPLY_SYSTEM_PROMPT,
    LONELY_QUERIES, LONELY_REPLY_SYSTEM_PROMPT,
    PATROL_QUERIES, PATROL_SYSTEM_PROMPT,
)

# ============================================================================
# 定数
# ============================================================================

AUTH_TOKEN = os.environ.get("X_AUTH_TOKEN", "")
CT0 = os.environ.get("X_CT0", "")

JST = timezone(timedelta(hours=9))
STATE_FILE = Path(__file__).parent / "lisa_growth_state.json"
LOG_FILE = "/tmp/lisa_growth.log"

# 1日の上限 — 自然に見える範囲で抑える
DAILY_LIMITS = {
    "x_reply_viral": 8,
    "x_reply_lonely": 5,
    "x_patrol": 5,
    "x_tweet": 3,
    "x_like": 20,
    "x_follow": 5,
    "x_quote_viral": 2,
    "room_like": 20,
    "room_collect": 2,
    # Threads
    "threads_post": 3,
    "threads_reply": 10,
    "threads_like": 20,
    "threads_follow": 5,
    "threads_search_engage": 8,
    "threads_repost": 2,
}

# 活動時間 (JST)
ACTIVE_HOURS = (7, 23)  # 7:00 ~ 23:00

# ============================================================================
# ロギング
# ============================================================================

logger = logging.getLogger("lisa_growth")
logger.setLevel(logging.INFO)

_fmt = logging.Formatter("%(asctime)s [%(levelname)s] %(message)s", datefmt="%Y-%m-%d %H:%M:%S")

_fh = logging.FileHandler(LOG_FILE, encoding="utf-8")
_fh.setFormatter(_fmt)
logger.addHandler(_fh)

_sh = logging.StreamHandler()
_sh.setFormatter(_fmt)
logger.addHandler(_sh)

# ============================================================================
# 状態管理
# ============================================================================

def load_state() -> dict:
    """状態ファイルを読み込む"""
    if STATE_FILE.exists():
        with open(STATE_FILE) as f:
            return json.load(f)
    return {
        "category_index": 0,
        "tweet_history": [],
        "daily_counts": {},
        "daily_date": "",
        "consecutive_errors": {},
    }


def save_state(state: dict):
    """状態ファイルを保存"""
    with open(STATE_FILE, "w") as f:
        json.dump(state, f, indent=2, ensure_ascii=False)


def reset_daily_if_needed(state: dict) -> dict:
    """日付が変わったらカウントリセット"""
    today = datetime.now(JST).strftime("%Y-%m-%d")
    if state.get("daily_date") != today:
        state["daily_counts"] = {}
        state["daily_date"] = today
        state["consecutive_errors"] = {}
    return state


def increment_count(state: dict, task: str):
    """タスク実行カウントを増加"""
    counts = state.setdefault("daily_counts", {})
    counts[task] = counts.get(task, 0) + 1


def is_within_limit(state: dict, task: str) -> bool:
    """上限チェック"""
    limit = DAILY_LIMITS.get(task, 999)
    current = state.get("daily_counts", {}).get(task, 0)
    return current < limit


def is_active_hours() -> bool:
    """活動時間内かチェック"""
    now_jst = datetime.now(JST)
    return ACTIVE_HOURS[0] <= now_jst.hour < ACTIVE_HOURS[1]


# ============================================================================
# Copilot: 一時停止/再開
# ============================================================================

COPILOT_PAUSE_FILE = Path(__file__).parent / ".copilot_paused"

def check_copilot_pause(timeout=300):
    """copilotが一時停止中なら再開されるまで待機 (最大timeout秒)"""
    if not COPILOT_PAUSE_FILE.exists():
        return
    logger.info("⏸ copilot一時停止中 — 人間の操作を待機中...")
    waited = 0
    while COPILOT_PAUSE_FILE.exists() and waited < timeout:
        time.sleep(2)
        waited += 2
    if not COPILOT_PAUSE_FILE.exists():
        logger.info("▶ copilot再開")
    else:
        logger.warning("⏸ copilot待機タイムアウト — 続行")


def record_error(state: dict, task: str):
    """エラー記録 (3連続でタスク停止)"""
    errs = state.setdefault("consecutive_errors", {})
    errs[task] = errs.get(task, 0) + 1


def clear_errors(state: dict, task: str):
    """エラーカウントクリア"""
    errs = state.setdefault("consecutive_errors", {})
    errs[task] = 0


def has_too_many_errors(state: dict, task: str) -> bool:
    """3連続エラーチェック"""
    return state.get("consecutive_errors", {}).get(task, 0) >= 3


# ============================================================================
# Selenium Chrome + Cookie
# ============================================================================

_DRIVER = None


def get_driver():
    """Seleniumドライバーを取得 (遅延初期化)"""
    global _DRIVER
    if _DRIVER is not None:
        return _DRIVER

    from selenium import webdriver
    from selenium.webdriver.chrome.options import Options

    opts = Options()
    opts.binary_location = "/usr/bin/google-chrome-stable"
    opts.add_argument("--no-sandbox")
    opts.add_argument("--disable-dev-shm-usage")
    opts.add_argument("--disable-gpu")
    opts.add_argument("--window-size=1920,1080")
    opts.add_argument("--lang=ja-JP")
    opts.add_argument("--disable-blink-features=AutomationControlled")
    opts.add_experimental_option("excludeSwitches", ["enable-automation"])
    opts.add_experimental_option("useAutomationExtension", False)
    opts.add_experimental_option("detach", True)

    driver = webdriver.Chrome(options=opts)
    driver.execute_cdp_cmd("Page.addScriptToEvaluateOnNewDocument", {
        "source": "Object.defineProperty(navigator, 'webdriver', {get: () => undefined})"
    })

    _DRIVER = driver
    return driver


_x_logged_in = False


def ensure_x_login():
    """X にログイン済みか確認。Cookie注入。2回目以降はスキップ。"""
    global _x_logged_in
    from selenium.webdriver.common.by import By
    from selenium.webdriver.support.ui import WebDriverWait
    from selenium.webdriver.support import expected_conditions as EC

    if _x_logged_in:
        return True

    driver = get_driver()
    driver.get("https://x.com")
    time.sleep(2)

    for name, value in [("auth_token", AUTH_TOKEN), ("ct0", CT0)]:
        driver.add_cookie({
            "name": name, "value": value,
            "domain": ".x.com", "path": "/", "secure": True,
        })

    driver.get("https://x.com/home")
    time.sleep(4)

    try:
        WebDriverWait(driver, 10).until(
            EC.presence_of_element_located((By.CSS_SELECTOR, '[data-testid="primaryColumn"]'))
        )
        logger.info("X ログイン成功 (@lisapyo3274)")
        _x_logged_in = True
        return True
    except Exception as e:
        logger.error(f"X ログイン失敗: {e}")
        return False


def human_delay(min_s=3, max_s=12):
    """人間っぽいランダム待機"""
    time.sleep(random.uniform(min_s, max_s))


# ============================================================================
# タスク: x_tweet
# ============================================================================

def task_x_tweet(state: dict, dry_run=False) -> bool:
    """ツイート投稿"""
    from selenium.webdriver.common.by import By
    from selenium.webdriver.common.keys import Keys
    from selenium.webdriver.support.ui import WebDriverWait
    from selenium.webdriver.support import expected_conditions as EC

    category_index = state.get("category_index", 0)
    history = state.get("tweet_history", [])

    tweet_text, next_index = generate_tweet(category_index, history)
    state["category_index"] = next_index

    logger.info(f"ツイート生成 (カテゴリ: {CATEGORY_ORDER[category_index % len(CATEGORY_ORDER)]})")
    logger.info(f"内容:\n{tweet_text}")

    if dry_run:
        logger.info("[DRY RUN] ツイート投稿をスキップ")
        return True

    driver = get_driver()
    driver.get("https://x.com/compose/post")
    time.sleep(4)

    try:
        # compose modal のダイアログ内 textbox を取得
        # (ホームのtextboxもあるので、dialog内のものを優先)
        textboxes = WebDriverWait(driver, 10).until(
            lambda d: d.find_elements(By.CSS_SELECTOR, 'div[role="dialog"] div[role="textbox"]')
            or d.find_elements(By.CSS_SELECTOR, 'div[role="textbox"]')
        )
        textarea = textboxes[0]
        textarea.click()
        time.sleep(0.5)

        # send_keys + Keys.RETURN で改行 (execCommandは使わない)
        lines = tweet_text.split("\n")
        for i, line in enumerate(lines):
            if line:
                textarea.send_keys(line)
            if i < len(lines) - 1:
                textarea.send_keys(Keys.RETURN)

        time.sleep(1)

        # 投稿ボタンクリック (JavaScript click でオーバーレイ回避)
        post_btn = WebDriverWait(driver, 5).until(
            EC.presence_of_element_located((By.CSS_SELECTOR,
                'button[data-testid="tweetButton"], button[data-testid="tweetButtonInline"]'))
        )
        driver.execute_script("arguments[0].click();", post_btn)
        time.sleep(3)

        # graduated-access ポップアップ対応
        try:
            got_it = driver.find_element(By.XPATH, '//button[contains(., "Got it")]')
            got_it.click()
            logger.info("graduated-access ポップアップを通過")
            time.sleep(2)
        except Exception:
            pass

        # 履歴に追加 (最新20件のみ保持)
        history.append(tweet_text)
        state["tweet_history"] = history[-20:]

        logger.info("ツイート投稿成功")
        return True

    except Exception as e:
        logger.error(f"ツイート投稿失敗: {e}")
        return False


# ============================================================================
# タスク: x_like
# ============================================================================

def task_x_like(state: dict, count=8, dry_run=False) -> bool:
    """コスメ系ツイートにいいね"""
    from selenium.webdriver.common.by import By
    from selenium.webdriver.support.ui import WebDriverWait
    from selenium.webdriver.support import expected_conditions as EC

    query = random.choice(LIKE_QUERIES)
    search_url = f"https://x.com/search?q={quote_plus(query)}&src=typed_query&f=live"

    logger.info(f"いいね開始: クエリ「{query}」 目標{count}件")

    if dry_run:
        logger.info(f"[DRY RUN] {search_url}")
        return True

    driver = get_driver()
    driver.get(search_url)
    time.sleep(4)

    liked = 0
    scroll_attempts = 0

    while liked < count and scroll_attempts < 5:
        try:
            tweets = driver.find_elements(By.CSS_SELECTOR, 'article[data-testid="tweet"]')
        except Exception:
            break

        for tweet in tweets:
            if liked >= count:
                break
            try:
                # 自分のツイートはスキップ
                user_links = tweet.find_elements(By.CSS_SELECTOR, 'div[data-testid="User-Name"] a')
                is_self = any("lisapyo3274" in (a.get_attribute("href") or "") for a in user_links)
                if is_self:
                    continue

                # いいねボタンを探す
                like_btn = tweet.find_element(By.CSS_SELECTOR, 'button[data-testid="like"]')
                like_btn.click()
                liked += 1
                logger.info(f"いいね {liked}/{count}")
                human_delay(3, 10)

            except Exception:
                # 既にいいね済み or 要素が見つからない
                continue

        # スクロール
        driver.execute_script("window.scrollTo(0, document.body.scrollHeight);")
        time.sleep(random.uniform(2, 5))
        scroll_attempts += 1

    logger.info(f"いいね完了: {liked}/{count}件")
    return liked > 0


# ============================================================================
# タスク: x_follow
# ============================================================================

def task_x_follow(state: dict, count=4, dry_run=False) -> bool:
    """コスメ垢のフォロワーからフォロー"""
    from selenium.webdriver.common.by import By
    from selenium.webdriver.support.ui import WebDriverWait
    from selenium.webdriver.support import expected_conditions as EC

    target = random.choice(FOLLOW_TARGET_ACCOUNTS)
    followers_url = f"https://x.com/{target}/followers"

    logger.info(f"フォロー開始: @{target} のフォロワーから{count}人")

    if dry_run:
        logger.info(f"[DRY RUN] {followers_url}")
        return True

    driver = get_driver()
    driver.get(followers_url)
    time.sleep(5)

    followed = 0
    scroll_attempts = 0

    while followed < count and scroll_attempts < 5:
        try:
            # フォローボタン (「フォロー」テキスト付き)
            # data-testid で未フォローのボタンを探す
            # フォロー済みは data-testid に "unfollow" を含む
            btns = driver.find_elements(
                By.CSS_SELECTOR,
                'button[data-testid$="-follow"]'
            )

            for btn in btns:
                if followed >= count:
                    break
                try:
                    testid = btn.get_attribute("data-testid") or ""
                    # "xxx-follow" は未フォロー、"xxx-unfollow" はフォロー済み
                    if "unfollow" in testid:
                        continue
                    btn.click()
                    followed += 1
                    logger.info(f"フォロー {followed}/{count}")
                    human_delay(5, 15)
                except Exception:
                    continue

        except Exception:
            break

        driver.execute_script("window.scrollTo(0, document.body.scrollHeight);")
        time.sleep(random.uniform(3, 6))
        scroll_attempts += 1

    logger.info(f"フォロー完了: {followed}/{count}人")
    return followed > 0


# ============================================================================
# タスク: room_like
# ============================================================================

def task_room_like(state: dict, count=12, dry_run=False) -> bool:
    """楽天ROOMでいいね回り"""
    from selenium.webdriver.common.by import By

    discover_url = "https://room.rakuten.co.jp/all/trending"

    logger.info(f"ROOMいいね開始: 目標{count}件")

    if dry_run:
        logger.info(f"[DRY RUN] {discover_url}")
        return True

    driver = get_driver()

    # 楽天ログイン (SSOフロー)
    _ensure_rakuten_login(driver)

    driver.get(discover_url)
    time.sleep(5)

    liked = 0
    scroll_attempts = 0

    while liked < count and scroll_attempts < 8:
        try:
            # ROOMの「いいね」ボタン: ハートアイコン
            # ROOMではいいねボタンは class に "like" を含む or ハート SVG
            like_btns = driver.find_elements(
                By.CSS_SELECTOR,
                'button[class*="like"], [data-testid*="like"], .item-like-button'
            )

            # フォールバック: SVGハートアイコンのボタンを探す
            if not like_btns:
                like_btns = driver.find_elements(
                    By.CSS_SELECTOR,
                    '[role="button"][aria-label*="いいね"], button[aria-label*="like"]'
                )

            for btn in like_btns:
                if liked >= count:
                    break
                try:
                    # 既にいいね済み (赤/ピンク) はスキップ
                    classes = btn.get_attribute("class") or ""
                    if "liked" in classes or "active" in classes:
                        continue
                    btn.click()
                    liked += 1
                    logger.info(f"ROOMいいね {liked}/{count}")
                    human_delay(2, 8)
                except Exception:
                    continue

        except Exception:
            break

        driver.execute_script("window.scrollTo(0, document.body.scrollHeight);")
        time.sleep(random.uniform(2, 5))
        scroll_attempts += 1

    logger.info(f"ROOMいいね完了: {liked}/{count}件")
    return liked > 0


# ============================================================================
# タスク: room_collect
# ============================================================================

def task_room_collect(state: dict, dry_run=False) -> bool:
    """楽天市場の人気コスメをROOMにコレ!"""
    from selenium.webdriver.common.by import By
    from selenium.webdriver.support.ui import WebDriverWait
    from selenium.webdriver.support import expected_conditions as EC

    # ROOM未登録の商品からランダム選択
    p = random.choice(PRODUCTS)
    search_query = p["name"]
    search_url = f"https://search.rakuten.co.jp/search/mall/{quote_plus(search_query)}/"

    logger.info(f"ROOMコレ!: 「{search_query}」")

    if dry_run:
        logger.info(f"[DRY RUN] {search_url}")
        return True

    driver = get_driver()
    _ensure_rakuten_login(driver)

    driver.get(search_url)
    time.sleep(5)

    try:
        # 「ROOMに投稿」リンクを探す
        room_links = driver.find_elements(By.XPATH, '//a[contains(text(), "ROOMに投稿")]')
        if not room_links:
            # 代替: 商品ページに遷移してROOMボタンを探す
            items = driver.find_elements(By.CSS_SELECTOR, '.searchresultitem a, .dui-card a')
            if items:
                items[0].click()
                time.sleep(4)
                room_links = driver.find_elements(
                    By.XPATH,
                    '//a[contains(text(), "ROOMに投稿")] | //a[contains(@href, "room.rakuten.co.jp")]'
                )

        if room_links:
            room_links[0].click()
            time.sleep(5)

            # コメント入力
            comment_areas = driver.find_elements(By.CSS_SELECTOR, 'textarea, [contenteditable="true"]')
            if comment_areas:
                comment = f"{p['review']} {random.choice(['!', '!!', ''])}"
                comment_areas[0].send_keys(comment)
                time.sleep(1)

            # 完了ボタン
            done_btns = driver.find_elements(
                By.XPATH,
                '//button[contains(text(), "完了")] | //button[contains(text(), "投稿")] | //*[contains(@role, "button")][contains(., "完了")]'
            )
            if done_btns:
                done_btns[0].click()
                time.sleep(3)
                logger.info(f"ROOMコレ! 成功: {p['short']}")
                return True

        logger.warning(f"ROOMコレ! — 投稿リンクが見つからず: {search_query}")
        return False

    except Exception as e:
        logger.error(f"ROOMコレ! 失敗: {e}")
        return False


# ============================================================================
# 楽天ログイン
# ============================================================================

def _ensure_rakuten_login(driver):
    """楽天にログイン (SSOフロー)"""
    from selenium.webdriver.common.by import By
    from selenium.webdriver.common.keys import Keys

    driver.get("https://room.rakuten.co.jp/my/myroom")
    time.sleep(4)

    current_url = driver.current_url
    if "login" in current_url or "grp/0" in current_url:
        logger.info("楽天ログイン開始")
        try:
            email_input = driver.find_element(By.CSS_SELECTOR, 'input[name="u"], input[type="email"], #loginInner_u')
            email_input.clear()
            email_input.send_keys("lisapyo3274@gmail.com")
            email_input.send_keys(Keys.RETURN)
            time.sleep(3)

            pass_input = driver.find_element(By.CSS_SELECTOR, 'input[name="p"], input[type="password"], #loginInner_p')
            pass_input.clear()
            pass_input.send_keys("Lisalisa3274R!")
            pass_input.send_keys(Keys.RETURN)
            time.sleep(5)

            # Skip verification if present
            try:
                skip_btn = driver.find_element(By.XPATH, '//a[contains(text(), "Skip")] | //button[contains(text(), "Skip")] | //a[contains(text(), "あとで")]')
                skip_btn.click()
                time.sleep(3)
            except Exception:
                pass

            logger.info("楽天ログイン成功")
        except Exception as e:
            logger.error(f"楽天ログイン失敗: {e}")
    else:
        logger.info("楽天ログイン済み")


# ============================================================================
# バズポスト検索 + LLM生成リプ
# ============================================================================

def _parse_engagement(label: str) -> dict:
    """aria-label からエンゲージメント数をパース"""
    result = {"replies": 0, "retweets": 0, "likes": 0, "views": 0}
    patterns = [
        (r"(\d[\d,]*)\s*repl", "replies"),
        (r"(\d[\d,]*)\s*repost", "retweets"),
        (r"(\d[\d,]*)\s*like", "likes"),
        (r"(\d[\d,]*)\s*view", "views"),
        (r"(\d[\d,]*)\s*件の返信", "replies"),
        (r"(\d[\d,]*)\s*件のリポスト", "retweets"),
        (r"(\d[\d,]*)\s*件のいいね", "likes"),
        (r"(\d[\d,]*)\s*件の表示", "views"),
    ]
    for pat, key in patterns:
        m = re.search(pat, label, re.IGNORECASE)
        if m:
            result[key] = int(m.group(1).replace(",", ""))
    return result


def find_viral_posts(driver, max_posts=5) -> list[dict]:
    """今日バズってるコスメ系ポストを検索して返す。最大3クエリでリトライ。"""
    from selenium.webdriver.common.by import By
    from selenium.webdriver.support.ui import WebDriverWait
    from selenium.webdriver.support import expected_conditions as EC

    # 今日と昨日の日付 (JST) → since:昨日 until:明日 で直近24h以内に絞る
    now_jst = datetime.now(JST)
    since_date = (now_jst - timedelta(days=1)).strftime("%Y-%m-%d")
    until_date = (now_jst + timedelta(days=1)).strftime("%Y-%m-%d")
    date_filter = f" since:{since_date} until:{until_date}"

    # 最大6クエリ試す (ヒット率にバラつきがあるため多めに)
    queries_to_try = random.sample(VIRAL_QUERIES, min(6, len(VIRAL_QUERIES)))

    posts = []
    seen_urls = set()

    for query_info in queries_to_try:
        if len(posts) >= max_posts:
            break

        q = query_info["q"] + date_filter
        # 最新タブ (f=live) でリアルタイムにバズってるポストを拾う
        search_url = f"https://x.com/search?q={quote_plus(q)}&src=typed_query&f=live"

        logger.info(f"バズポスト検索: 「{q}」")
        driver.get(search_url)
        time.sleep(5)

        # スクロールしてツイートを読み込む
        driver.execute_script("window.scrollTo(0, 300);")
        time.sleep(2)

        try:
            WebDriverWait(driver, 8).until(
                EC.presence_of_element_located((By.CSS_SELECTOR, 'article[data-testid="tweet"]'))
            )
        except Exception:
            logger.info(f"検索結果なし: {q}")
            continue

        # このクエリ結果のツイートをパースして蓄積
        tweets = driver.find_elements(By.CSS_SELECTOR, 'article[data-testid="tweet"]')
        added_this_query = 0

        for tweet in tweets:
            if len(posts) >= max_posts:
                break
            try:
                # 自分のツイートはスキップ
                user_links = tweet.find_elements(By.CSS_SELECTOR, 'div[data-testid="User-Name"] a')
                is_self = any("lisapyo3274" in (a.get_attribute("href") or "") for a in user_links)
                if is_self:
                    continue

                # ツイート本文
                text_el = tweet.find_elements(By.CSS_SELECTOR, 'div[data-testid="tweetText"]')
                if not text_el:
                    continue
                text = text_el[0].text.strip()
                if not text or len(text) < 10:
                    continue

                # ツイートURL
                time_el = tweet.find_elements(By.CSS_SELECTOR, 'time[datetime]')
                tweet_url = ""
                if time_el:
                    parent_a = time_el[0].find_element(By.XPATH, './..')
                    tweet_url = parent_a.get_attribute("href") or ""

                if tweet_url in seen_urls:
                    continue
                seen_urls.add(tweet_url)

                # 投稿者
                handle = ""
                for a in user_links:
                    href = a.get_attribute("href") or ""
                    if href.startswith("https://x.com/") and "/status/" not in href:
                        handle = href.split("/")[-1]
                        break

                # エンゲージメント
                engagement = {"likes": 0, "views": 0, "replies": 0}
                groups = tweet.find_elements(By.CSS_SELECTOR, 'div[role="group"]')
                if groups:
                    label = groups[-1].get_attribute("aria-label") or ""
                    engagement = _parse_engagement(label)

                likes = engagement.get("likes", 0)
                replies = engagement.get("replies", 0)

                posts.append({
                    "text": text,
                    "url": tweet_url,
                    "handle": handle,
                    "likes": likes,
                    "replies": replies,
                    "views": engagement.get("views", 0),
                })
                added_this_query += 1

            except Exception:
                continue

        logger.info(f"クエリ結果: {added_this_query}件追加 (合計 {len(posts)}件)")

    # 穴場スコアでソート: likes多い × リプ少ない = リプが目立つ
    # score = likes / (replies + 1)  → likes 30, replies 1 → score 15 (最高)
    #                                → likes 500, replies 200 → score 2.5 (埋もれる)
    for p in posts:
        p["score"] = p["likes"] / (p["replies"] + 1)

    posts.sort(key=lambda p: p["score"], reverse=True)

    if posts:
        top = posts[0]
        logger.info(f"候補 {len(posts)}件 — 最良: @{top['handle']} "
                     f"likes={top['likes']} replies={top['replies']} score={top['score']:.1f}")
    else:
        logger.warning("全クエリで検索結果なし")
    return posts


def _get_llm_client():
    """Azure OpenAI クライアントを取得 (遅延初期化)"""
    from openai import AzureOpenAI
    return AzureOpenAI(
        api_key=os.environ["AZURE_API_KEY"],
        azure_endpoint=f"https://{os.environ['AZURE_RESOURCE_NAME']}.openai.azure.com/",
        api_version="2024-12-01-preview",
    )


LLM_STREAM_FILE = Path("/tmp/lisa_llm_stream.jsonl")

def _emit_llm_event(event_type: str, data: str):
    """LLM思考過程をファイルに書き出す (copilot SSEが読む)"""
    import json as _json
    entry = _json.dumps({
        "type": event_type,
        "data": data,
        "ts": datetime.now(JST).strftime("%H:%M:%S"),
    }, ensure_ascii=False)
    with open(LLM_STREAM_FILE, "a", encoding="utf-8") as f:
        f.write(entry + "\n")


def generate_llm_reply(tweet_text: str, tweet_handle: str, mode="reply") -> str:
    """Azure GPT-5 でバズポストへの鋭いリプ/引用RTテキストを生成 (ストリーミング)"""
    system = REPLY_SYSTEM_PROMPT

    if mode == "reply":
        user_prompt = (
            f"以下のポスト (@{tweet_handle}) に対するリプライを1つだけ書いて。\n"
            f"リプライのテキストだけを出力して (説明不要)。\n\n"
            f"---\n{tweet_text}\n---"
        )
    else:
        user_prompt = (
            f"以下のポスト (@{tweet_handle}) を引用RTするコメントを1つだけ書いて。\n"
            f"コメントのテキストだけを出力して (説明不要)。ハッシュタグ禁止。\n\n"
            f"---\n{tweet_text}\n---"
        )

    # LLMストリームにコンテキストを書き出す
    _emit_llm_event("context", f"📨 対象ポスト (@{tweet_handle}):\n{tweet_text[:200]}")
    _emit_llm_event("prompt", f"🎭 lisaのペルソナでリプライ生成中...")
    _emit_llm_event("thinking", "💭 考え中...")

    try:
        client = _get_llm_client()
        stream = client.chat.completions.create(
            model="azure-gpt-5",
            messages=[
                {"role": "system", "content": system},
                {"role": "user", "content": user_prompt},
            ],
            max_completion_tokens=2000,
            stream=True,
        )

        reply_parts = []
        reasoning_parts = []

        for chunk in stream:
            delta = chunk.choices[0].delta if chunk.choices else None
            if not delta:
                continue

            # reasoning (思考トークン)
            reasoning = getattr(delta, "reasoning_content", None) or getattr(delta, "reasoning", None)
            if reasoning:
                reasoning_parts.append(reasoning)
                _emit_llm_event("reasoning", reasoning)

            # content (出力トークン)
            if delta.content:
                reply_parts.append(delta.content)
                _emit_llm_event("content_token", delta.content)

        reply = "".join(reply_parts).strip()
        reasoning_full = "".join(reasoning_parts)

        if reasoning_full:
            _emit_llm_event("reasoning_done", f"💭 思考完了 ({len(reasoning_full)}文字)")

        if not reply:
            logger.error("LLM空レスポンス")
            _emit_llm_event("error", "❌ 空レスポンス")
            return ""

        _emit_llm_event("done", f"✅ 生成完了: {reply[:100]}")
        # 余計な引用符やマーカーを除去
        reply = reply.strip('"').strip("'").strip()
        # ChromeDriver BMP制限: サロゲートペア文字 (非BMP絵文字等) を除去
        reply = "".join(c for c in reply if ord(c) <= 0xFFFF)
        logger.info(f"LLM生成 ({mode}): {reply}")
        return reply
    except Exception as e:
        logger.error(f"LLM呼び出し失敗: {e}")
        return ""


# ============================================================================
# タスク: x_reply_viral
# ============================================================================

def task_x_reply_viral(state: dict, count=3, dry_run=False) -> bool:
    """バズポストに鋭いリプライ"""
    from selenium.webdriver.common.by import By
    from selenium.webdriver.common.keys import Keys
    from selenium.webdriver.support.ui import WebDriverWait
    from selenium.webdriver.support import expected_conditions as EC

    driver = get_driver()

    # バズポスト検索
    posts = find_viral_posts(driver, max_posts=count + 2)
    if not posts:
        logger.warning("バズポストが見つからず")
        return False

    replied = 0
    replied_urls = set(state.get("replied_urls", []))

    for post in posts:
        if replied >= count:
            break
        if post["url"] in replied_urls:
            continue

        logger.info(f"リプ対象: @{post['handle']} (likes={post['likes']} replies={post['replies']} score={post.get('score',0):.0f}) {post['text'][:60]}...")

        # LLMでリプ生成
        reply_text = generate_llm_reply(post["text"], post["handle"], mode="reply")
        if not reply_text:
            continue

        if dry_run:
            logger.info(f"[DRY RUN] リプ: {reply_text}")
            replied += 1
            continue

        # ツイート個別ページに遷移してリプライ
        driver.get(post["url"])
        time.sleep(4)

        try:
            # リプライ入力欄を探す (ツイート詳細ページの返信ボックス)
            # "Post your reply" or "返信をポスト" テキストボックス
            reply_boxes = driver.find_elements(
                By.CSS_SELECTOR,
                'div[data-testid="tweetTextarea_0"]'
            )
            if not reply_boxes:
                logger.warning("リプライボックスが見つからず")
                continue

            reply_box = reply_boxes[0]
            reply_box.click()
            time.sleep(1)

            # テキスト入力 (send_keys + Keys.RETURN で改行)
            lines = reply_text.split("\n")
            for i, line in enumerate(lines):
                if line:
                    reply_box.send_keys(line)
                if i < len(lines) - 1:
                    reply_box.send_keys(Keys.RETURN)

            time.sleep(1)

            # 投稿ボタン (リプライ用は tweetButtonInline)
            reply_btn = WebDriverWait(driver, 5).until(
                EC.presence_of_element_located((By.CSS_SELECTOR,
                    'button[data-testid="tweetButtonInline"]'))
            )
            driver.execute_script("arguments[0].click();", reply_btn)
            time.sleep(3)

            # graduated-access 対応
            try:
                got_it = driver.find_element(By.XPATH, '//button[contains(., "Got it")]')
                got_it.click()
                time.sleep(2)
            except Exception:
                pass

            replied += 1
            replied_urls.add(post["url"])
            logger.info(f"リプライ投稿成功 {replied}/{count}: @{post['handle']}")
            human_delay(10, 30)

        except Exception as e:
            logger.error(f"リプライ投稿失敗: {e}")
            continue

    # リプ済みURL保存 (最新100件)
    state["replied_urls"] = list(replied_urls)[-100:]

    logger.info(f"バズリプ完了: {replied}/{count}件")
    return replied > 0


# ============================================================================
# タスク: x_reply_lonely — 暇・寂しがってる子にリプ
# ============================================================================

def find_lonely_posts(driver, max_posts=5) -> list[dict]:
    """暇・寂しがってる子のツイートを検索"""
    from selenium.webdriver.common.by import By
    from selenium.webdriver.support.ui import WebDriverWait
    from selenium.webdriver.support import expected_conditions as EC

    now_jst = datetime.now(JST)
    since_date = (now_jst - timedelta(hours=6)).strftime("%Y-%m-%d")
    until_date = (now_jst + timedelta(days=1)).strftime("%Y-%m-%d")
    date_filter = f" since:{since_date} until:{until_date}"

    queries_to_try = random.sample(LONELY_QUERIES, min(4, len(LONELY_QUERIES)))

    posts = []
    seen_urls = set()

    for query_info in queries_to_try:
        if len(posts) >= max_posts:
            break

        q = query_info["q"] + date_filter
        search_url = f"https://x.com/search?q={quote_plus(q)}&src=typed_query&f=live"

        logger.info(f"寂しがり検索: 「{q}」")
        driver.get(search_url)
        time.sleep(5)

        driver.execute_script("window.scrollTo(0, 300);")
        time.sleep(2)

        try:
            WebDriverWait(driver, 8).until(
                EC.presence_of_element_located((By.CSS_SELECTOR, 'article[data-testid="tweet"]'))
            )
        except Exception:
            logger.info(f"検索結果なし: {q}")
            continue

        tweets = driver.find_elements(By.CSS_SELECTOR, 'article[data-testid="tweet"]')

        for tweet in tweets:
            if len(posts) >= max_posts:
                break
            try:
                # 自分のツイートはスキップ
                user_links = tweet.find_elements(By.CSS_SELECTOR, 'div[data-testid="User-Name"] a')
                is_self = any("lisapyo3274" in (a.get_attribute("href") or "") for a in user_links)
                if is_self:
                    continue

                # ツイート本文
                text_el = tweet.find_elements(By.CSS_SELECTOR, 'div[data-testid="tweetText"]')
                if not text_el:
                    continue
                text = text_el[0].text.strip()
                if not text or len(text) < 5:
                    continue

                # ツイートURL
                time_el = tweet.find_elements(By.CSS_SELECTOR, 'time[datetime]')
                tweet_url = ""
                if time_el:
                    parent_a = time_el[0].find_element(By.XPATH, './..')
                    tweet_url = parent_a.get_attribute("href") or ""

                if tweet_url in seen_urls:
                    continue
                seen_urls.add(tweet_url)

                # 投稿者
                handle = ""
                for a in user_links:
                    href = a.get_attribute("href") or ""
                    if href.startswith("https://x.com/") and "/status/" not in href:
                        handle = href.split("/")[-1]
                        break

                # エンゲージメント
                engagement = {"likes": 0, "views": 0, "replies": 0}
                groups = tweet.find_elements(By.CSS_SELECTOR, 'div[role="group"]')
                if groups:
                    label = groups[-1].get_attribute("aria-label") or ""
                    engagement = _parse_engagement(label)

                posts.append({
                    "text": text,
                    "url": tweet_url,
                    "handle": handle,
                    "likes": engagement.get("likes", 0),
                    "replies": engagement.get("replies", 0),
                    "views": engagement.get("views", 0),
                })

            except Exception:
                continue

        logger.info(f"寂しがり検索結果: {len(posts)}件")

    # リプ少ない順 (返事まだ来てない子) を優先
    posts.sort(key=lambda p: p["replies"])

    if posts:
        logger.info(f"寂しがり候補 {len(posts)}件 — 先頭: @{posts[0]['handle']} 「{posts[0]['text'][:40]}」")
    return posts


def generate_lonely_reply(tweet_text: str, tweet_handle: str) -> str:
    """暇・寂しがってる子向けのフレンドリーなリプを生成"""
    system = LONELY_REPLY_SYSTEM_PROMPT
    user_prompt = (
        f"以下のポスト (@{tweet_handle}) に対する気軽なリプライを1つだけ書いて。\n"
        f"リプライのテキストだけを出力して (説明不要)。\n\n"
        f"---\n{tweet_text}\n---"
    )

    _emit_llm_event("context", f"📨 対象ポスト (@{tweet_handle}):\n{tweet_text[:200]}")
    _emit_llm_event("prompt", f"🎭 lisaのペルソナでフレンドリーリプ生成中...")
    _emit_llm_event("thinking", "💭 考え中...")

    try:
        client = _get_llm_client()
        stream = client.chat.completions.create(
            model="azure-gpt-5",
            messages=[
                {"role": "system", "content": system},
                {"role": "user", "content": user_prompt},
            ],
            max_completion_tokens=2000,
            stream=True,
        )

        reply_parts = []
        reasoning_parts = []

        for chunk in stream:
            delta = chunk.choices[0].delta if chunk.choices else None
            if not delta:
                continue
            reasoning = getattr(delta, "reasoning_content", None) or getattr(delta, "reasoning", None)
            if reasoning:
                reasoning_parts.append(reasoning)
                _emit_llm_event("reasoning", reasoning)
            if delta.content:
                reply_parts.append(delta.content)
                _emit_llm_event("content_token", delta.content)

        reply = "".join(reply_parts).strip()
        reasoning_full = "".join(reasoning_parts)

        if reasoning_full:
            _emit_llm_event("reasoning_done", f"💭 思考完了 ({len(reasoning_full)}文字)")

        if not reply:
            logger.error("LLM空レスポンス")
            _emit_llm_event("error", "❌ 空レスポンス")
            return ""

        _emit_llm_event("done", f"✅ 生成完了: {reply[:100]}")
        reply = reply.strip('"').strip("'").strip()
        reply = "".join(c for c in reply if ord(c) <= 0xFFFF)
        logger.info(f"LLM生成 (lonely): {reply}")
        return reply
    except Exception as e:
        logger.error(f"LLM呼び出し失敗: {e}")
        _emit_llm_event("error", f"❌ エラー: {e}")
        return ""


def task_x_reply_lonely(state: dict, count=3, dry_run=False) -> bool:
    """暇・寂しがってる子にフレンドリーなリプライ"""
    from selenium.webdriver.common.by import By
    from selenium.webdriver.common.keys import Keys
    from selenium.webdriver.support.ui import WebDriverWait
    from selenium.webdriver.support import expected_conditions as EC

    driver = get_driver()

    posts = find_lonely_posts(driver, max_posts=count + 3)
    if not posts:
        logger.warning("寂しがりポストが見つからず")
        return False

    replied = 0
    replied_urls = set(state.get("replied_urls", []))

    for post in posts:
        if replied >= count:
            break
        if post["url"] in replied_urls:
            continue

        logger.info(f"リプ対象 (寂しがり): @{post['handle']} replies={post['replies']} 「{post['text'][:60]}」")

        reply_text = generate_lonely_reply(post["text"], post["handle"])
        if not reply_text:
            continue

        if dry_run:
            logger.info(f"[DRY RUN] リプ: {reply_text}")
            replied += 1
            continue

        driver.get(post["url"])
        time.sleep(4)

        try:
            reply_boxes = driver.find_elements(
                By.CSS_SELECTOR,
                'div[data-testid="tweetTextarea_0"]'
            )
            if not reply_boxes:
                logger.warning("リプライボックスが見つからず")
                continue

            reply_box = reply_boxes[0]
            reply_box.click()
            time.sleep(1)

            lines = reply_text.split("\n")
            for i, line in enumerate(lines):
                if line:
                    reply_box.send_keys(line)
                if i < len(lines) - 1:
                    reply_box.send_keys(Keys.RETURN)

            time.sleep(1)

            reply_btn = WebDriverWait(driver, 5).until(
                EC.presence_of_element_located((By.CSS_SELECTOR,
                    'button[data-testid="tweetButtonInline"]'))
            )
            driver.execute_script("arguments[0].click();", reply_btn)
            time.sleep(3)

            # graduated-access 対応
            try:
                got_it = driver.find_element(By.XPATH, '//button[contains(., "Got it")]')
                got_it.click()
                time.sleep(2)
            except Exception:
                pass

            replied += 1
            replied_urls.add(post["url"])
            logger.info(f"寂しがりリプ成功 {replied}/{count}: @{post['handle']}")
            human_delay(10, 30)

        except Exception as e:
            logger.error(f"リプライ投稿失敗: {e}")
            continue

    state["replied_urls"] = list(replied_urls)[-100:]

    logger.info(f"寂しがりリプ完了: {replied}/{count}件")
    return replied > 0


# ============================================================================
# タスク: x_patrol — 法的リスク・重大ミス指摘パトロール
# ============================================================================

def find_patrol_posts(driver, max_posts=5) -> list[dict]:
    """法的リスクや危険な美容情報のツイートを検索"""
    from selenium.webdriver.common.by import By
    from selenium.webdriver.support.ui import WebDriverWait
    from selenium.webdriver.support import expected_conditions as EC

    now_jst = datetime.now(JST)
    since_date = (now_jst - timedelta(days=3)).strftime("%Y-%m-%d")
    until_date = (now_jst + timedelta(days=1)).strftime("%Y-%m-%d")
    date_filter = f" since:{since_date} until:{until_date}"

    queries_to_try = random.sample(PATROL_QUERIES, min(5, len(PATROL_QUERIES)))

    posts = []
    seen_urls = set()

    for query_info in queries_to_try:
        if len(posts) >= max_posts:
            break

        q = query_info["q"] + date_filter
        search_url = f"https://x.com/search?q={quote_plus(q)}&src=typed_query&f=live"

        logger.info(f"パトロール検索: 「{q}」")
        driver.get(search_url)
        time.sleep(5)

        driver.execute_script("window.scrollTo(0, 300);")
        time.sleep(2)

        try:
            WebDriverWait(driver, 8).until(
                EC.presence_of_element_located((By.CSS_SELECTOR, 'article[data-testid="tweet"]'))
            )
        except Exception:
            logger.info(f"検索結果なし: {q}")
            continue

        tweets = driver.find_elements(By.CSS_SELECTOR, 'article[data-testid="tweet"]')

        for tweet in tweets[:5]:
            if len(posts) >= max_posts:
                break
            try:
                user_links = tweet.find_elements(By.CSS_SELECTOR, 'div[data-testid="User-Name"] a')
                is_self = any("lisapyo3274" in (a.get_attribute("href") or "") for a in user_links)
                if is_self:
                    continue

                text_el = tweet.find_elements(By.CSS_SELECTOR, 'div[data-testid="tweetText"]')
                if not text_el:
                    continue
                text = text_el[0].text.strip()
                if not text or len(text) < 15:
                    continue

                time_el = tweet.find_elements(By.CSS_SELECTOR, 'time[datetime]')
                tweet_url = ""
                if time_el:
                    parent_a = time_el[0].find_element(By.XPATH, './..')
                    tweet_url = parent_a.get_attribute("href") or ""

                if tweet_url in seen_urls:
                    continue
                seen_urls.add(tweet_url)

                handle = ""
                for a in user_links:
                    href = a.get_attribute("href") or ""
                    if href.startswith("https://x.com/") and "/status/" not in href:
                        handle = href.split("/")[-1]
                        break

                engagement = {"likes": 0, "views": 0, "replies": 0}
                groups = tweet.find_elements(By.CSS_SELECTOR, 'div[role="group"]')
                if groups:
                    label = groups[-1].get_attribute("aria-label") or ""
                    engagement = _parse_engagement(label)

                posts.append({
                    "text": text,
                    "url": tweet_url,
                    "handle": handle,
                    "likes": engagement.get("likes", 0),
                    "replies": engagement.get("replies", 0),
                    "views": engagement.get("views", 0),
                    "query": query_info["q"],
                })

            except Exception:
                continue

        logger.info(f"パトロール結果: {len(posts)}件")

    if posts:
        logger.info(f"パトロール候補 {len(posts)}件 — 先頭: @{posts[0]['handle']} 「{posts[0]['text'][:50]}」")
    return posts


def generate_patrol_reply(tweet_text: str, tweet_handle: str, query: str) -> str:
    """法的リスクや危険情報に対するやさしい指摘リプを生成。
    LLMにまず問題を判定させ、問題なしなら空文字を返す。"""
    system = PATROL_SYSTEM_PROMPT
    user_prompt = (
        f"以下のポスト (@{tweet_handle}) を読んで判断して。\n"
        f"検索クエリ「{query}」でヒットしたポストです。\n\n"
        f"---\n{tweet_text}\n---\n\n"
        f"このポストに法的リスク・健康リスク・重大な誤りがある場合のみ、\n"
        f"やさしく指摘するリプライを1つだけ書いて。\n"
        f"問題がない場合は「SKIP」とだけ出力して。\n"
        f"リプライのテキストだけを出力して (説明不要)。"
    )

    _emit_llm_event("context", f"🔍 パトロール対象 (@{tweet_handle}):\n{tweet_text[:200]}")
    _emit_llm_event("prompt", f"🛡️ 法的リスク・危険情報チェック中...")
    _emit_llm_event("thinking", "💭 分析中...")

    try:
        client = _get_llm_client()
        stream = client.chat.completions.create(
            model="azure-gpt-5",
            messages=[
                {"role": "system", "content": system},
                {"role": "user", "content": user_prompt},
            ],
            max_completion_tokens=2000,
            stream=True,
        )

        reply_parts = []
        reasoning_parts = []

        for chunk in stream:
            delta = chunk.choices[0].delta if chunk.choices else None
            if not delta:
                continue
            reasoning = getattr(delta, "reasoning_content", None) or getattr(delta, "reasoning", None)
            if reasoning:
                reasoning_parts.append(reasoning)
                _emit_llm_event("reasoning", reasoning)
            if delta.content:
                reply_parts.append(delta.content)
                _emit_llm_event("content_token", delta.content)

        reply = "".join(reply_parts).strip()
        reasoning_full = "".join(reasoning_parts)

        if reasoning_full:
            _emit_llm_event("reasoning_done", f"💭 分析完了 ({len(reasoning_full)}文字)")

        if not reply or reply.upper().strip() == "SKIP":
            _emit_llm_event("done", "⏭️ 問題なし — スキップ")
            logger.info(f"パトロール: @{tweet_handle} — 問題なし、スキップ")
            return ""

        _emit_llm_event("done", f"🛡️ 指摘生成完了: {reply[:100]}")
        reply = reply.strip('"').strip("'").strip()
        reply = "".join(c for c in reply if ord(c) <= 0xFFFF)
        logger.info(f"LLM生成 (patrol): {reply}")
        return reply
    except Exception as e:
        logger.error(f"LLM呼び出し失敗: {e}")
        _emit_llm_event("error", f"❌ エラー: {e}")
        return ""


def task_x_patrol(state: dict, count=3, dry_run=False) -> bool:
    """美容・コスメ系の法的リスクや危険情報をパトロールして指摘"""
    from selenium.webdriver.common.by import By
    from selenium.webdriver.common.keys import Keys
    from selenium.webdriver.support.ui import WebDriverWait
    from selenium.webdriver.support import expected_conditions as EC

    driver = get_driver()

    posts = find_patrol_posts(driver, max_posts=count + 5)
    if not posts:
        logger.warning("パトロール対象が見つからず")
        return False

    replied = 0
    replied_urls = set(state.get("replied_urls", []))

    for post in posts:
        if replied >= count:
            break
        if post["url"] in replied_urls:
            continue

        logger.info(f"パトロール対象: @{post['handle']} (query={post.get('query','')}) 「{post['text'][:60]}」")

        reply_text = generate_patrol_reply(post["text"], post["handle"], post.get("query", ""))
        if not reply_text:
            # LLMが問題なしと判断 → スキップ
            continue

        if dry_run:
            logger.info(f"[DRY RUN] パトロールリプ: {reply_text}")
            replied += 1
            continue

        driver.get(post["url"])
        time.sleep(4)

        try:
            reply_boxes = driver.find_elements(
                By.CSS_SELECTOR,
                'div[data-testid="tweetTextarea_0"]'
            )
            if not reply_boxes:
                logger.warning("リプライボックスが見つからず")
                continue

            reply_box = reply_boxes[0]
            reply_box.click()
            time.sleep(1)

            lines = reply_text.split("\n")
            for i, line in enumerate(lines):
                if line:
                    reply_box.send_keys(line)
                if i < len(lines) - 1:
                    reply_box.send_keys(Keys.RETURN)

            time.sleep(1)

            reply_btn = WebDriverWait(driver, 5).until(
                EC.presence_of_element_located((By.CSS_SELECTOR,
                    'button[data-testid="tweetButtonInline"]'))
            )
            driver.execute_script("arguments[0].click();", reply_btn)
            time.sleep(3)

            try:
                got_it = driver.find_element(By.XPATH, '//button[contains(., "Got it")]')
                got_it.click()
                time.sleep(2)
            except Exception:
                pass

            replied += 1
            replied_urls.add(post["url"])
            logger.info(f"パトロールリプ成功 {replied}/{count}: @{post['handle']}")
            human_delay(15, 40)

        except Exception as e:
            logger.error(f"パトロールリプ投稿失敗: {e}")
            continue

    state["replied_urls"] = list(replied_urls)[-100:]

    logger.info(f"パトロール完了: {replied}/{count}件")
    return replied > 0


# ============================================================================
# タスク: x_quote_viral
# ============================================================================

def task_x_quote_viral(state: dict, count=2, dry_run=False) -> bool:
    """バズポストを引用RT"""
    from selenium.webdriver.common.by import By
    from selenium.webdriver.common.keys import Keys
    from selenium.webdriver.support.ui import WebDriverWait
    from selenium.webdriver.support import expected_conditions as EC

    driver = get_driver()

    # バズポスト検索
    posts = find_viral_posts(driver, max_posts=count + 2)
    if not posts:
        logger.warning("バズポストが見つからず")
        return False

    quoted = 0
    quoted_urls = set(state.get("quoted_urls", []))

    for post in posts:
        if quoted >= count:
            break
        if post["url"] in quoted_urls:
            continue

        logger.info(f"引用RT対象: @{post['handle']} (likes={post['likes']} replies={post['replies']} score={post.get('score',0):.0f}) {post['text'][:60]}...")

        # LLMで引用コメント生成
        quote_text = generate_llm_reply(post["text"], post["handle"], mode="quote")
        if not quote_text:
            continue

        if dry_run:
            logger.info(f"[DRY RUN] 引用RT: {quote_text}")
            quoted += 1
            continue

        # ツイート個別ページに遷移
        driver.get(post["url"])
        time.sleep(4)

        try:
            # リポストアイコンをクリック
            repost_btn = WebDriverWait(driver, 5).until(
                EC.presence_of_element_located((By.CSS_SELECTOR,
                    'button[data-testid="retweet"]'))
            )
            driver.execute_script("arguments[0].click();", repost_btn)
            time.sleep(2)

            # 「Quote」メニューを選択
            quote_option = WebDriverWait(driver, 5).until(
                EC.presence_of_element_located((By.CSS_SELECTOR,
                    'a[data-testid="Dropdown-Item-Quote"], '
                    'div[data-testid="Dropdown"] a[href*="compose"], '
                    'a[role="menuitem"][href*="compose"]'))
            )
            driver.execute_script("arguments[0].click();", quote_option)
            time.sleep(3)

            # compose画面でテキスト入力
            textboxes = WebDriverWait(driver, 10).until(
                lambda d: d.find_elements(By.CSS_SELECTOR, 'div[role="dialog"] div[role="textbox"]')
                or d.find_elements(By.CSS_SELECTOR, 'div[role="textbox"]')
            )
            textarea = textboxes[0]
            textarea.click()
            time.sleep(0.5)

            lines = quote_text.split("\n")
            for i, line in enumerate(lines):
                if line:
                    textarea.send_keys(line)
                if i < len(lines) - 1:
                    textarea.send_keys(Keys.RETURN)

            time.sleep(1)

            # 投稿ボタン
            post_btn = WebDriverWait(driver, 5).until(
                EC.presence_of_element_located((By.CSS_SELECTOR,
                    'button[data-testid="tweetButton"], button[data-testid="tweetButtonInline"]'))
            )
            driver.execute_script("arguments[0].click();", post_btn)
            time.sleep(3)

            # graduated-access 対応
            try:
                got_it = driver.find_element(By.XPATH, '//button[contains(., "Got it")]')
                got_it.click()
                time.sleep(2)
            except Exception:
                pass

            quoted += 1
            quoted_urls.add(post["url"])
            logger.info(f"引用RT投稿成功 {quoted}/{count}: @{post['handle']}")
            human_delay(15, 40)

        except Exception as e:
            logger.error(f"引用RT投稿失敗: {e}")
            continue

    # 引用済みURL保存
    state["quoted_urls"] = list(quoted_urls)[-100:]

    logger.info(f"引用RT完了: {quoted}/{count}件")
    return quoted > 0


# ============================================================================
# タスクディスパッチャ
# ============================================================================

TASK_FUNCTIONS = {
    "x_tweet": task_x_tweet,
    "x_like": task_x_like,
    "x_follow": task_x_follow,
    "x_reply_viral": task_x_reply_viral,
    "x_reply_lonely": task_x_reply_lonely,
    "x_patrol": task_x_patrol,
    "x_quote_viral": task_x_quote_viral,
    "room_like": task_room_like,
    "room_collect": task_room_collect,
}

# Threads タスクを追加 (lisa_threads_bot.py から)
try:
    from lisa_threads_bot import THREADS_TASK_FUNCTIONS as _threads_fns
    TASK_FUNCTIONS.update(_threads_fns)
except ImportError:
    pass

X_TASKS = {"x_tweet", "x_like", "x_follow", "x_reply_viral", "x_reply_lonely", "x_patrol", "x_quote_viral"}
THREADS_TASKS = {"threads_post", "threads_reply", "threads_like", "threads_follow", "threads_search_engage", "threads_repost"}


def run_task(task_name: str, dry_run=False, count=None) -> bool:
    """
    タスクを実行。

    Args:
        task_name: タスク名
        dry_run: ドライラン
        count: 実行回数 (いいね/フォロー用)

    Returns:
        成功したかどうか
    """
    if task_name not in TASK_FUNCTIONS:
        logger.error(f"不明なタスク: {task_name}")
        return False

    # 活動時間チェック
    if not is_active_hours() and not dry_run:
        logger.info(f"活動時間外 (JST {ACTIVE_HOURS[0]}:00~{ACTIVE_HOURS[1]}:00)")
        return False

    # 状態読み込み + 日次リセット
    state = load_state()
    state = reset_daily_if_needed(state)

    # 上限チェック
    if not is_within_limit(state, task_name):
        logger.info(f"{task_name}: 本日の上限 ({DAILY_LIMITS[task_name]}) に到達済み")
        return False

    # エラー連続チェック
    if has_too_many_errors(state, task_name):
        logger.warning(f"{task_name}: 連続エラー3回 — 次回までスキップ")
        return False

    # Copilot一時停止チェック
    check_copilot_pause()

    # Threads系タスクは lisa_threads_bot.run_task に委譲
    if task_name in THREADS_TASKS:
        try:
            from lisa_threads_bot import run_task as threads_run_task
            logger.info(f"タスク開始: {task_name} (Threads)")
            return threads_run_task(task_name, dry_run=dry_run, count=count)
        except ImportError:
            logger.error("lisa_threads_bot が見つかりません")
            return False

    # X系タスクはログイン必要 (dry_runでも検索は実行するのでログイン必須)
    if task_name in X_TASKS:
        if not ensure_x_login():
            record_error(state, task_name)
            save_state(state)
            return False

    # タスク実行
    logger.info(f"タスク開始: {task_name}")
    start = time.time()

    task_fn = TASK_FUNCTIONS[task_name]

    try:
        kwargs = {"state": state, "dry_run": dry_run}
        if count is not None and task_name in ("x_like", "x_follow", "room_like", "x_reply_viral", "x_reply_lonely", "x_patrol", "x_quote_viral"):
            kwargs["count"] = count

        success = task_fn(**kwargs)

        if success:
            increment_count(state, task_name)
            clear_errors(state, task_name)
        else:
            record_error(state, task_name)

    except Exception as e:
        logger.error(f"{task_name} 例外: {e}", exc_info=True)
        record_error(state, task_name)
        success = False

    elapsed = time.time() - start
    logger.info(f"タスク完了: {task_name} ({'成功' if success else '失敗'}) {elapsed:.1f}秒")

    # 状態保存
    save_state(state)
    return success


# ============================================================================
# CLI
# ============================================================================

def main():
    parser = argparse.ArgumentParser(description="lisa growth bot")
    parser.add_argument("--task", required=True, choices=list(TASK_FUNCTIONS.keys()),
                        help="実行するタスク")
    parser.add_argument("--dry-run", action="store_true",
                        help="ドライラン (実際には実行しない)")
    parser.add_argument("--count", type=int, default=None,
                        help="いいね/フォロー件数")
    args = parser.parse_args()

    logger.info(f"=== lisa growth bot: {args.task} ===")

    success = run_task(args.task, dry_run=args.dry_run, count=args.count)
    sys.exit(0 if success else 1)


if __name__ == "__main__":
    main()
