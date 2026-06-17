#!/usr/bin/env python3
"""
companion_growth_bot.py — companion (二次元AIコンパニオン) X集客自動化
=========================================================================
含むタスク: x_tweet, x_like, x_follow, x_reply_viral, x_quote_viral
含まないタスク: 寂しがりリプ・パトロール・楽天ROOM・Threads

設計方針:
- 認証情報・LP URL・対象アカウントは全て環境変数経由 (リポジトリにハードコードしない)
- SFWコピーのみ。出力安全チェック (`companion_growth_data.safety_check_copy`) を通過しない
  テキストは絶対に投稿しない (fail-closed)
- 日次上限は人間に見える範囲で抑える
- companion/CLAUDE.md §0 と整合する形で、未成年想起ワード・実在人物 @ 言及・露骨表現を排除

Usage:
    # 環境変数を設定
    export COMPANION_X_AUTH_TOKEN=...
    export COMPANION_X_CT0=...
    export COMPANION_X_HANDLE=companion_official  # 自分のhandle (自ポスト除外用)
    export COMPANION_LP_URL=https://your-lp.example.com/
    export AZURE_API_KEY=...                       # LLMリプ生成に使用
    export AZURE_RESOURCE_NAME=...

    python3 examples/companion_growth_bot.py --task x_tweet --dry-run
    python3 examples/companion_growth_bot.py --task x_like --count 10
    python3 examples/companion_growth_bot.py --task x_reply_viral --count 2
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

from companion_growth_data import (
    LIKE_QUERIES, FOLLOW_TARGET_ACCOUNTS, VIRAL_QUERIES,
    REPLY_SYSTEM_PROMPT, OWN_HANDLE, BRAND_NAME,
    generate_tweet, CATEGORY_ORDER, safety_check_copy,
)

# ============================================================================
# 認証情報 — 必ず環境変数経由
# ============================================================================

AUTH_TOKEN = os.environ.get("COMPANION_X_AUTH_TOKEN", "")
CT0 = os.environ.get("COMPANION_X_CT0", "")

JST = timezone(timedelta(hours=9))
STATE_FILE = Path(__file__).parent / "companion_growth_state.json"
LOG_FILE = "/tmp/companion_growth.log"

# 1日の上限 — 自然な範囲で抑える (lisaよりやや控えめ)
DAILY_LIMITS = {
    "x_tweet": 3,
    "x_like": 15,
    "x_follow": 3,
    "x_reply_viral": 5,
    "x_quote_viral": 2,
}

# 活動時間 (JST)
ACTIVE_HOURS = (9, 23)

# ============================================================================
# ロギング
# ============================================================================

logger = logging.getLogger("companion_growth")
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
    if STATE_FILE.exists():
        with open(STATE_FILE) as f:
            return json.load(f)
    return {
        "category_index": 0,
        "tweet_history": [],
        "daily_counts": {},
        "daily_date": "",
        "consecutive_errors": {},
        "replied_urls": [],
        "quoted_urls": [],
    }


def save_state(state: dict):
    with open(STATE_FILE, "w") as f:
        json.dump(state, f, indent=2, ensure_ascii=False)


def reset_daily_if_needed(state: dict) -> dict:
    today = datetime.now(JST).strftime("%Y-%m-%d")
    if state.get("daily_date") != today:
        state["daily_counts"] = {}
        state["daily_date"] = today
        state["consecutive_errors"] = {}
    return state


def increment_count(state: dict, task: str):
    counts = state.setdefault("daily_counts", {})
    counts[task] = counts.get(task, 0) + 1


def is_within_limit(state: dict, task: str) -> bool:
    limit = DAILY_LIMITS.get(task, 999)
    current = state.get("daily_counts", {}).get(task, 0)
    return current < limit


def is_active_hours() -> bool:
    now_jst = datetime.now(JST)
    return ACTIVE_HOURS[0] <= now_jst.hour < ACTIVE_HOURS[1]


def record_error(state: dict, task: str):
    errs = state.setdefault("consecutive_errors", {})
    errs[task] = errs.get(task, 0) + 1


def clear_errors(state: dict, task: str):
    errs = state.setdefault("consecutive_errors", {})
    errs[task] = 0


def has_too_many_errors(state: dict, task: str) -> bool:
    return state.get("consecutive_errors", {}).get(task, 0) >= 3


# ============================================================================
# Selenium Chrome + Cookie
# ============================================================================

_DRIVER = None
_x_logged_in = False


def get_driver():
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


def ensure_x_login() -> bool:
    global _x_logged_in
    from selenium.webdriver.common.by import By
    from selenium.webdriver.support.ui import WebDriverWait
    from selenium.webdriver.support import expected_conditions as EC

    if _x_logged_in:
        return True

    if not AUTH_TOKEN or not CT0:
        logger.error("COMPANION_X_AUTH_TOKEN / COMPANION_X_CT0 が未設定")
        return False

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
        logger.info(f"X ログイン成功 (handle={OWN_HANDLE or '?'})")
        _x_logged_in = True
        return True
    except Exception as e:
        logger.error(f"X ログイン失敗: {e}")
        return False


def human_delay(min_s=3, max_s=12):
    time.sleep(random.uniform(min_s, max_s))


def _is_self_tweet(tweet) -> bool:
    """自分のツイートかチェック (OWN_HANDLE 未設定なら常に False)"""
    if not OWN_HANDLE:
        return False
    try:
        from selenium.webdriver.common.by import By
        user_links = tweet.find_elements(By.CSS_SELECTOR, 'div[data-testid="User-Name"] a')
        return any(OWN_HANDLE in (a.get_attribute("href") or "") for a in user_links)
    except Exception:
        return False


# ============================================================================
# タスク: x_tweet
# ============================================================================

def task_x_tweet(state: dict, dry_run=False) -> bool:
    from selenium.webdriver.common.by import By
    from selenium.webdriver.common.keys import Keys
    from selenium.webdriver.support.ui import WebDriverWait
    from selenium.webdriver.support import expected_conditions as EC

    category_index = state.get("category_index", 0)
    history = state.get("tweet_history", [])

    tweet_text, next_index = generate_tweet(category_index, history)
    state["category_index"] = next_index

    # 二重安全チェック (generate_tweet 内でもチェック済みだが念のため)
    ok, reason = safety_check_copy(tweet_text)
    if not ok:
        logger.error(f"安全チェックNG (ツイート): {reason}")
        return False

    category_name = CATEGORY_ORDER[category_index % len(CATEGORY_ORDER)]
    logger.info(f"ツイート生成 (カテゴリ: {category_name})")
    logger.info(f"内容:\n{tweet_text}")

    if dry_run:
        logger.info("[DRY RUN] ツイート投稿をスキップ")
        return True

    driver = get_driver()
    driver.get("https://x.com/compose/post")
    time.sleep(4)

    try:
        textboxes = WebDriverWait(driver, 10).until(
            lambda d: d.find_elements(By.CSS_SELECTOR, 'div[role="dialog"] div[role="textbox"]')
            or d.find_elements(By.CSS_SELECTOR, 'div[role="textbox"]')
        )
        textarea = textboxes[0]
        textarea.click()
        time.sleep(0.5)

        lines = tweet_text.split("\n")
        for i, line in enumerate(lines):
            if line:
                textarea.send_keys(line)
            if i < len(lines) - 1:
                textarea.send_keys(Keys.RETURN)

        time.sleep(1)

        post_btn = WebDriverWait(driver, 5).until(
            EC.presence_of_element_located((By.CSS_SELECTOR,
                'button[data-testid="tweetButton"], button[data-testid="tweetButtonInline"]'))
        )
        driver.execute_script("arguments[0].click();", post_btn)
        time.sleep(3)

        try:
            got_it = driver.find_element(By.XPATH, '//button[contains(., "Got it")]')
            got_it.click()
            logger.info("graduated-access ポップアップ通過")
            time.sleep(2)
        except Exception:
            pass

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
    from selenium.webdriver.common.by import By

    query = random.choice(LIKE_QUERIES)
    search_url = f"https://x.com/search?q={quote_plus(query)}&src=typed_query&f=live"

    logger.info(f"いいね開始: 「{query}」 目標{count}件")

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
                if _is_self_tweet(tweet):
                    continue

                like_btn = tweet.find_element(By.CSS_SELECTOR, 'button[data-testid="like"]')
                like_btn.click()
                liked += 1
                logger.info(f"いいね {liked}/{count}")
                human_delay(3, 10)
            except Exception:
                continue

        driver.execute_script("window.scrollTo(0, document.body.scrollHeight);")
        time.sleep(random.uniform(2, 5))
        scroll_attempts += 1

    logger.info(f"いいね完了: {liked}/{count}件")
    return liked > 0


# ============================================================================
# タスク: x_follow
# ============================================================================

def task_x_follow(state: dict, count=3, dry_run=False) -> bool:
    from selenium.webdriver.common.by import By

    if not FOLLOW_TARGET_ACCOUNTS:
        logger.warning("COMPANION_X_FOLLOW_TARGETS 未設定 — フォロータスクをスキップ")
        return False

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
            btns = driver.find_elements(
                By.CSS_SELECTOR, 'button[data-testid$="-follow"]'
            )
            for btn in btns:
                if followed >= count:
                    break
                try:
                    testid = btn.get_attribute("data-testid") or ""
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
# バズポスト検索
# ============================================================================

def _parse_engagement(label: str) -> dict:
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
    """AI/二次元キャラ周辺のバズポストを検索"""
    from selenium.webdriver.common.by import By
    from selenium.webdriver.support.ui import WebDriverWait
    from selenium.webdriver.support import expected_conditions as EC

    now_jst = datetime.now(JST)
    since_date = (now_jst - timedelta(days=1)).strftime("%Y-%m-%d")
    until_date = (now_jst + timedelta(days=1)).strftime("%Y-%m-%d")
    date_filter = f" since:{since_date} until:{until_date}"

    queries_to_try = random.sample(VIRAL_QUERIES, min(6, len(VIRAL_QUERIES)))

    posts = []
    seen_urls = set()

    for query_info in queries_to_try:
        if len(posts) >= max_posts:
            break

        q = query_info["q"] + date_filter
        search_url = f"https://x.com/search?q={quote_plus(q)}&src=typed_query&f=live"

        logger.info(f"バズポスト検索: 「{q}」")
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
                if _is_self_tweet(tweet):
                    continue

                text_el = tweet.find_elements(By.CSS_SELECTOR, 'div[data-testid="tweetText"]')
                if not text_el:
                    continue
                text = text_el[0].text.strip()
                if not text or len(text) < 10:
                    continue

                # 元ポスト本文に未成年想起ワードが含まれているならスキップ
                # (そういう人にリプして、こちらの投稿が紐付くと印象が悪い)
                src_ok, src_reason = safety_check_copy(text)
                if not src_ok and src_reason.startswith("banned_term"):
                    logger.info(f"元ポストにNGワード — スキップ ({src_reason})")
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
                user_links = tweet.find_elements(By.CSS_SELECTOR, 'div[data-testid="User-Name"] a')
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
                })
            except Exception:
                continue

    # likes多い × replies少ない = 目立つ位置取り
    for p in posts:
        p["score"] = p["likes"] / (p["replies"] + 1)
    posts.sort(key=lambda p: p["score"], reverse=True)

    if posts:
        top = posts[0]
        logger.info(f"候補 {len(posts)}件 — 最良: @{top['handle']} "
                    f"likes={top['likes']} replies={top['replies']} score={top['score']:.1f}")
    return posts


# ============================================================================
# LLM (Azure OpenAI) でリプ生成
# ============================================================================

def _get_llm_client():
    from openai import AzureOpenAI
    return AzureOpenAI(
        api_key=os.environ["AZURE_API_KEY"],
        azure_endpoint=f"https://{os.environ['AZURE_RESOURCE_NAME']}.openai.azure.com/",
        api_version="2024-12-01-preview",
    )


def generate_llm_reply(tweet_text: str, tweet_handle: str, mode: str = "reply") -> str:
    """LLMでリプ/引用テキスト生成 + 安全チェック。NGなら空文字。"""
    system = REPLY_SYSTEM_PROMPT

    if mode == "reply":
        user_prompt = (
            f"以下のポストへのリプライを1つだけ書いて。\n"
            f"リプライのテキストだけを出力して (説明不要)。\n\n"
            f"---\n{tweet_text}\n---"
        )
    else:
        user_prompt = (
            f"以下のポストを引用RTするコメントを1つだけ書いて。\n"
            f"コメントのテキストだけを出力して (説明不要)。ハッシュタグ禁止。\n\n"
            f"---\n{tweet_text}\n---"
        )

    try:
        client = _get_llm_client()
        resp = client.chat.completions.create(
            model="azure-gpt-5",
            messages=[
                {"role": "system", "content": system},
                {"role": "user", "content": user_prompt},
            ],
            max_completion_tokens=600,
        )
        reply = (resp.choices[0].message.content or "").strip()
        reply = reply.strip('"').strip("'").strip()
        # ChromeDriver BMP制限: サロゲートペア除去
        reply = "".join(c for c in reply if ord(c) <= 0xFFFF)

        if not reply:
            logger.error("LLM空レスポンス")
            return ""

        ok, reason = safety_check_copy(reply)
        if not ok:
            logger.warning(f"安全チェックNG (生成リプ): {reason} → '{reply[:80]}'")
            return ""

        logger.info(f"LLM生成 ({mode}): {reply}")
        return reply
    except Exception as e:
        logger.error(f"LLM呼び出し失敗: {e}")
        return ""


# ============================================================================
# タスク: x_reply_viral
# ============================================================================

def task_x_reply_viral(state: dict, count=3, dry_run=False) -> bool:
    from selenium.webdriver.common.by import By
    from selenium.webdriver.common.keys import Keys
    from selenium.webdriver.support.ui import WebDriverWait
    from selenium.webdriver.support import expected_conditions as EC

    driver = get_driver()

    posts = find_viral_posts(driver, max_posts=count + 3)
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

        logger.info(f"リプ対象: @{post['handle']} score={post.get('score',0):.0f} 「{post['text'][:60]}」")

        reply_text = generate_llm_reply(post["text"], post["handle"], mode="reply")
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
                By.CSS_SELECTOR, 'div[data-testid="tweetTextarea_0"]'
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
            logger.info(f"リプライ投稿成功 {replied}/{count}: @{post['handle']}")
            human_delay(15, 40)
        except Exception as e:
            logger.error(f"リプライ投稿失敗: {e}")
            continue

    state["replied_urls"] = list(replied_urls)[-100:]
    logger.info(f"バズリプ完了: {replied}/{count}件")
    return replied > 0


# ============================================================================
# タスク: x_quote_viral
# ============================================================================

def task_x_quote_viral(state: dict, count=2, dry_run=False) -> bool:
    from selenium.webdriver.common.by import By
    from selenium.webdriver.common.keys import Keys
    from selenium.webdriver.support.ui import WebDriverWait
    from selenium.webdriver.support import expected_conditions as EC

    driver = get_driver()

    posts = find_viral_posts(driver, max_posts=count + 3)
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

        logger.info(f"引用RT対象: @{post['handle']} score={post.get('score',0):.0f} 「{post['text'][:60]}」")

        quote_text = generate_llm_reply(post["text"], post["handle"], mode="quote")
        if not quote_text:
            continue

        if dry_run:
            logger.info(f"[DRY RUN] 引用RT: {quote_text}")
            quoted += 1
            continue

        driver.get(post["url"])
        time.sleep(4)

        try:
            repost_btn = WebDriverWait(driver, 5).until(
                EC.presence_of_element_located((By.CSS_SELECTOR,
                    'button[data-testid="retweet"]'))
            )
            driver.execute_script("arguments[0].click();", repost_btn)
            time.sleep(2)

            quote_option = WebDriverWait(driver, 5).until(
                EC.presence_of_element_located((By.CSS_SELECTOR,
                    'a[data-testid="Dropdown-Item-Quote"], '
                    'div[data-testid="Dropdown"] a[href*="compose"], '
                    'a[role="menuitem"][href*="compose"]'))
            )
            driver.execute_script("arguments[0].click();", quote_option)
            time.sleep(3)

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

            post_btn = WebDriverWait(driver, 5).until(
                EC.presence_of_element_located((By.CSS_SELECTOR,
                    'button[data-testid="tweetButton"], button[data-testid="tweetButtonInline"]'))
            )
            driver.execute_script("arguments[0].click();", post_btn)
            time.sleep(3)

            try:
                got_it = driver.find_element(By.XPATH, '//button[contains(., "Got it")]')
                got_it.click()
                time.sleep(2)
            except Exception:
                pass

            quoted += 1
            quoted_urls.add(post["url"])
            logger.info(f"引用RT投稿成功 {quoted}/{count}: @{post['handle']}")
            human_delay(20, 50)
        except Exception as e:
            logger.error(f"引用RT投稿失敗: {e}")
            continue

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
    "x_quote_viral": task_x_quote_viral,
}


def run_task(task_name: str, dry_run=False, count=None) -> bool:
    if task_name not in TASK_FUNCTIONS:
        logger.error(f"不明なタスク: {task_name}")
        return False

    if not is_active_hours() and not dry_run:
        logger.info(f"活動時間外 (JST {ACTIVE_HOURS[0]}:00~{ACTIVE_HOURS[1]}:00)")
        return False

    state = load_state()
    state = reset_daily_if_needed(state)

    if not is_within_limit(state, task_name):
        logger.info(f"{task_name}: 本日の上限 ({DAILY_LIMITS[task_name]}) に到達済み")
        return False

    if has_too_many_errors(state, task_name):
        logger.warning(f"{task_name}: 連続エラー3回 — 次回までスキップ")
        return False

    if not ensure_x_login():
        record_error(state, task_name)
        save_state(state)
        return False

    logger.info(f"タスク開始: {task_name} ({BRAND_NAME})")
    start = time.time()
    task_fn = TASK_FUNCTIONS[task_name]

    try:
        kwargs = {"state": state, "dry_run": dry_run}
        if count is not None and task_name in ("x_like", "x_follow", "x_reply_viral", "x_quote_viral"):
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

    save_state(state)
    return success


# ============================================================================
# CLI
# ============================================================================

def main():
    parser = argparse.ArgumentParser(description=f"{BRAND_NAME} X 集客 bot")
    parser.add_argument("--task", required=True, choices=list(TASK_FUNCTIONS.keys()))
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--count", type=int, default=None)
    args = parser.parse_args()

    logger.info(f"=== companion growth bot: {args.task} ===")
    success = run_task(args.task, dry_run=args.dry_run, count=args.count)
    sys.exit(0 if success else 1)


if __name__ == "__main__":
    main()
