#!/usr/bin/env python3
"""
lisa_threads_bot.py — Threads自動成長エンジン
=============================================
タスク: threads_post, threads_reply, threads_like, threads_follow,
        threads_search_engage, threads_repost
Selenium (既存Chrome接続) で全操作。

Usage:
    python3 examples/lisa_threads_bot.py --task threads_like
    python3 examples/lisa_threads_bot.py --task threads_post --dry-run
    python3 examples/lisa_threads_bot.py --task threads_reply --count 3
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

os.environ.setdefault("DISPLAY", ":99")

sys.path.insert(0, str(Path(__file__).parent))

from lisa_threads_data import (
    THREADS_SEARCH_QUERIES,
    THREADS_REPLY_SYSTEM_PROMPT,
    generate_threads_post,
    THREADS_CATEGORY_ORDER,
)

# ============================================================================
# 定数
# ============================================================================

JST = timezone(timedelta(hours=9))
STATE_FILE = Path(__file__).parent / "lisa_threads_state.json"
LOG_FILE = "/tmp/lisa_growth.log"
LLM_STREAM_FILE = Path("/tmp/lisa_llm_stream.jsonl")

THREADS_BASE = "https://www.threads.net"

# Azure GPT-5 (X botと同じ環境変数を使う)
AZURE_API_KEY = os.environ.get("AZURE_API_KEY", "")
AZURE_RESOURCE_NAME = os.environ.get("AZURE_RESOURCE_NAME", "")
AZURE_ENDPOINT = f"https://{AZURE_RESOURCE_NAME}.openai.azure.com/" if AZURE_RESOURCE_NAME else ""
AZURE_DEPLOYMENT = "azure-gpt-5"
AZURE_API_VERSION = "2024-12-01-preview"

# 1日の上限
DAILY_LIMITS = {
    "threads_post": 3,
    "threads_reply": 10,
    "threads_like": 20,
    "threads_follow": 5,
    "threads_search_engage": 8,
    "threads_repost": 2,
}

# ============================================================================
# ロガー設定
# ============================================================================

logger = logging.getLogger("lisa_threads")
logger.setLevel(logging.INFO)

if not logger.handlers:
    fh = logging.FileHandler(LOG_FILE, encoding="utf-8")
    fh.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(message)s"))
    logger.addHandler(fh)
    sh = logging.StreamHandler()
    sh.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(message)s"))
    logger.addHandler(sh)

# ============================================================================
# 状態管理
# ============================================================================

def load_state() -> dict:
    if STATE_FILE.exists():
        with open(STATE_FILE) as f:
            return json.load(f)
    return {}


def save_state(state: dict):
    with open(STATE_FILE, "w") as f:
        json.dump(state, f, indent=2, ensure_ascii=False)


def check_daily_limit(state: dict, task: str) -> bool:
    today = datetime.now(JST).strftime("%Y-%m-%d")
    if state.get("daily_date") != today:
        state["daily_date"] = today
        state["daily_counts"] = {}
    count = state.get("daily_counts", {}).get(task, 0)
    limit = DAILY_LIMITS.get(task, 999)
    if count >= limit:
        logger.info(f"{task}: 日次上限 ({count}/{limit}) 到達")
        return False
    return True


def increment_count(state: dict, task: str):
    if "daily_counts" not in state:
        state["daily_counts"] = {}
    state["daily_counts"][task] = state["daily_counts"].get(task, 0) + 1
    save_state(state)

# ============================================================================
# LLM ストリーミング (Azure GPT-5)
# ============================================================================

def _llm_stream_log(event_type: str, data: str):
    """LLMストリームファイルにイベントを書き込む"""
    ts = datetime.now(JST).strftime("%H:%M:%S")
    entry = json.dumps({"type": event_type, "data": data, "ts": ts}, ensure_ascii=False)
    with open(LLM_STREAM_FILE, "a", encoding="utf-8") as f:
        f.write(entry + "\n")


def _sanitize_bmp(text: str) -> str:
    """BMP外の文字を除去 (X/Threadsで投稿エラー防止)"""
    return "".join(c for c in text if ord(c) <= 0xFFFF)


def generate_reply_with_llm(post_text: str, author: str = "") -> str | None:
    """Azure GPT-5 でリプライを生成"""
    try:
        from openai import AzureOpenAI
    except ImportError:
        logger.error("openai パッケージがインストールされていません")
        return None

    if not AZURE_API_KEY:
        logger.error("AZURE_OPENAI_API_KEY が設定されていません")
        return None

    _llm_stream_log("context", f"Threads リプライ生成: @{author}")
    _llm_stream_log("prompt", f"ポスト: {post_text[:100]}...")

    client = AzureOpenAI(
        azure_endpoint=AZURE_ENDPOINT,
        api_key=AZURE_API_KEY,
        api_version=AZURE_API_VERSION,
    )

    messages = [
        {"role": "system", "content": THREADS_REPLY_SYSTEM_PROMPT},
        {"role": "user", "content": f"以下のThreadsポストにリプライを書いて:\n\n@{author}: {post_text}"},
    ]

    try:
        response = client.chat.completions.create(
            model=AZURE_DEPLOYMENT,
            messages=messages,
            max_completion_tokens=2000,
            stream=True,
        )

        reply_text = ""
        for chunk in response:
            if chunk.choices and chunk.choices[0].delta.content:
                token = chunk.choices[0].delta.content
                reply_text += token
                _llm_stream_log("content_token", token)

        reply_text = _sanitize_bmp(reply_text.strip())
        _llm_stream_log("done", f"生成完了 ({len(reply_text)}文字)")
        logger.info(f"LLMリプライ生成: {reply_text[:50]}...")
        return reply_text

    except Exception as e:
        _llm_stream_log("error", str(e))
        logger.error(f"LLMリプライ生成エラー: {e}")
        return None

# ============================================================================
# Selenium Chrome接続
# ============================================================================

_driver = None

def get_driver():
    """ログイン済みChromeに接続"""
    global _driver
    if _driver is not None:
        try:
            _driver.current_url  # 接続テスト
            return _driver
        except Exception:
            _driver = None

    from selenium import webdriver
    from selenium.webdriver.chrome.options import Options

    opts = Options()
    opts.add_experimental_option("debuggerAddress", "127.0.0.1:9222")
    _driver = webdriver.Chrome(options=opts)
    logger.info("Chrome接続完了 (debuggerAddress)")
    return _driver


def safe_click(driver, element):
    """JavaScriptでクリック (SVG等も対応)"""
    from selenium.webdriver.common.action_chains import ActionChains
    try:
        # SVG要素は .click() が無いので dispatchEvent を使う
        driver.execute_script("""
            var el = arguments[0];
            if (typeof el.click === 'function') {
                el.click();
            } else {
                el.dispatchEvent(new MouseEvent('click', {bubbles: true, cancelable: true}));
            }
        """, element)
    except Exception:
        ActionChains(driver).move_to_element(element).click().perform()


def human_delay(min_s=1.0, max_s=3.0):
    """人間っぽい待機"""
    time.sleep(random.uniform(min_s, max_s))

# ============================================================================
# Threads DOM操作
# ============================================================================

def ensure_threads_login(driver) -> bool:
    """Threadsにログイン済みか確認"""
    driver.get(THREADS_BASE)
    time.sleep(3)

    url = driver.current_url
    # ログインページにリダイレクトされたらNG
    if "login" in url or "accounts" in url:
        logger.error("Threadsにログインしていません — 手動ログインしてください")
        return False

    logger.info("Threadsログイン確認OK")
    return True


def navigate_to_threads_home(driver):
    """Threadsホームに遷移"""
    if "threads.net" not in driver.current_url:
        driver.get(THREADS_BASE)
        time.sleep(3)


def compose_and_post(driver, text: str) -> bool:
    """Threadsに新規投稿する"""
    from selenium.webdriver.common.by import By
    from selenium.webdriver.common.keys import Keys
    from selenium.webdriver.support.ui import WebDriverWait
    from selenium.webdriver.support import expected_conditions as EC

    try:
        navigate_to_threads_home(driver)
        time.sleep(2)

        # 「+」ボタン or 「What's new?」をクリックしてコンポーザー展開
        # サイドバーの新規作成ボタン (+ アイコン)
        compose_opened = False

        # 方法1: サイドバーの「作成」リンク (aria-label)
        try:
            create_btn = driver.find_element(
                By.CSS_SELECTOR, 'a[aria-label="作成"], a[aria-label="Create"]'
            )
            safe_click(driver, create_btn)
            time.sleep(2)
            compose_opened = True
        except Exception:
            pass

        # 方法2: 「Start a thread...」/ 「What's new?」テキストをクリック
        if not compose_opened:
            try:
                whats_new = driver.find_element(
                    By.XPATH,
                    "//*[contains(text(), 'What') and contains(text(), 'new')]"
                    " | //*[contains(text(), 'Start a thread')]"
                    " | //*[contains(text(), 'スレッドを開始')]"
                )
                safe_click(driver, whats_new)
                time.sleep(2)
                compose_opened = True
            except Exception:
                pass

        # 方法3: SVGベースの+ボタン
        if not compose_opened:
            try:
                plus_btns = driver.find_elements(
                    By.CSS_SELECTOR, 'svg[aria-label="作成"], svg[aria-label="Create"]'
                )
                if plus_btns:
                    safe_click(driver, plus_btns[0])
                    time.sleep(2)
                    compose_opened = True
            except Exception:
                pass

        if not compose_opened:
            logger.error("コンポーザーを開けませんでした")
            return False

        # テキスト入力エリアを見つける
        # contenteditable div or textarea
        text_area = None
        for selector in [
            'div[contenteditable="true"]',
            'div[role="textbox"]',
            'p[data-placeholder]',
        ]:
            try:
                elements = driver.find_elements(By.CSS_SELECTOR, selector)
                if elements:
                    text_area = elements[-1]  # 最後のものが入力エリアの可能性が高い
                    break
            except Exception:
                continue

        if text_area is None:
            logger.error("テキスト入力エリアが見つかりません")
            return False

        # テキスト入力 (send_keys + Keys.RETURN で改行)
        safe_click(driver, text_area)
        time.sleep(0.5)

        lines = text.split("\n")
        for i, line in enumerate(lines):
            text_area.send_keys(line)
            if i < len(lines) - 1:
                text_area.send_keys(Keys.RETURN)
            time.sleep(0.1)

        human_delay(1.0, 2.0)

        # Post ボタンクリック
        posted = False
        for label in ["Post", "投稿", "投稿する"]:
            try:
                post_btn = driver.find_element(
                    By.XPATH,
                    f"//div[@role='button' and contains(text(), '{label}')]"
                    f" | //button[contains(text(), '{label}')]"
                )
                safe_click(driver, post_btn)
                posted = True
                break
            except Exception:
                continue

        if not posted:
            # フォールバック: role=button の中で投稿っぽいものを探す
            try:
                btns = driver.find_elements(By.CSS_SELECTOR, 'div[role="button"]')
                for btn in btns:
                    txt = btn.text.strip().lower()
                    if txt in ("post", "投稿", "投稿する"):
                        safe_click(driver, btn)
                        posted = True
                        break
            except Exception:
                pass

        if not posted:
            logger.error("Postボタンが見つかりません")
            return False

        time.sleep(3)
        logger.info(f"Threads投稿完了: {text[:40]}...")
        return True

    except Exception as e:
        logger.error(f"Threads投稿エラー: {e}", exc_info=True)
        return False


def find_threads_posts(driver, query: str, max_results: int = 10) -> list[dict]:
    """Threads検索で投稿を取得"""
    from selenium.webdriver.common.by import By
    from selenium.webdriver.common.keys import Keys

    posts = []
    try:
        driver.get(f"{THREADS_BASE}/search")
        time.sleep(3)

        # 検索バーにキーワード入力
        search_input = None
        for selector in [
            'input[type="search"]',
            'input[aria-label="検索"]',
            'input[aria-label="Search"]',
            'input[placeholder*="検索"]',
            'input[placeholder*="Search"]',
        ]:
            try:
                search_input = driver.find_element(By.CSS_SELECTOR, selector)
                break
            except Exception:
                continue

        if search_input is None:
            logger.warning("検索バーが見つかりません")
            return posts

        search_input.clear()
        search_input.send_keys(query)
        search_input.send_keys(Keys.RETURN)
        time.sleep(4)

        # スクロールして結果を取得
        for scroll_i in range(3):
            driver.execute_script("window.scrollBy(0, 600)")
            time.sleep(1.5)

        # 投稿要素を取得
        # Threadsのフィード投稿は通常 article タグ or 特定のdiv構造
        post_elements = driver.find_elements(
            By.CSS_SELECTOR,
            'div[data-pressable-container="true"], article'
        )

        for el in post_elements[:max_results]:
            try:
                text = el.text.strip()
                if not text or len(text) < 10:
                    continue

                # 投稿テキストとメトリクス抽出
                lines = text.split("\n")
                author = lines[0] if lines else ""
                content = "\n".join(lines[1:]) if len(lines) > 1 else text

                # いいね数・リプライ数のパース
                likes = 0
                replies = 0
                for line in lines:
                    line_lower = line.strip().lower()
                    # 「12 likes」「5件のいいね」etc.
                    like_match = re.search(r'(\d+)\s*(like|いいね)', line_lower)
                    if like_match:
                        likes = int(like_match.group(1))
                    reply_match = re.search(r'(\d+)\s*(repl|返信|件の返信)', line_lower)
                    if reply_match:
                        replies = int(reply_match.group(1))

                posts.append({
                    "element": el,
                    "author": author,
                    "text": content[:300],
                    "likes": likes,
                    "replies": replies,
                    "score": likes / (replies + 1),  # 穴場スコア
                })
            except Exception:
                continue

        logger.info(f"検索 '{query}': {len(posts)}件取得")
        return posts

    except Exception as e:
        logger.error(f"Threads検索エラー: {e}", exc_info=True)
        return posts


def like_post(driver, post_element) -> bool:
    """投稿にいいねする"""
    from selenium.webdriver.common.by import By

    try:
        # ハートアイコン (SVG aria-label)
        heart = None
        for label in ["Like", "いいね", "「いいね！」"]:
            try:
                heart = post_element.find_element(
                    By.CSS_SELECTOR, f'svg[aria-label="{label}"]'
                )
                break
            except Exception:
                continue

        if heart is None:
            # フォールバック: 親要素内のハートっぽいボタン
            try:
                hearts = post_element.find_elements(
                    By.CSS_SELECTOR, 'div[role="button"]'
                )
                for h in hearts:
                    if any(kw in h.get_attribute("aria-label") or ""
                           for kw in ["Like", "いいね"]):
                        heart = h
                        break
            except Exception:
                pass

        if heart is None:
            return False

        safe_click(driver, heart)
        human_delay(0.5, 1.5)
        return True

    except Exception as e:
        logger.error(f"いいねエラー: {e}")
        return False


def reply_to_post(driver, post_element, reply_text: str) -> bool:
    """投稿にリプライする"""
    from selenium.webdriver.common.by import By
    from selenium.webdriver.common.keys import Keys

    try:
        # リプライアイコンクリック
        reply_icon = None
        for label in ["Reply", "返信", "コメント", "Comment"]:
            try:
                reply_icon = post_element.find_element(
                    By.CSS_SELECTOR, f'svg[aria-label="{label}"]'
                )
                break
            except Exception:
                continue

        if reply_icon is None:
            # 投稿自体をクリックして詳細ページに遷移
            try:
                safe_click(driver, post_element)
                time.sleep(3)
            except Exception:
                return False
        else:
            safe_click(driver, reply_icon)
            time.sleep(2)

        # リプライ入力エリア
        reply_area = None
        for selector in [
            'div[contenteditable="true"]',
            'div[role="textbox"]',
        ]:
            try:
                elements = driver.find_elements(By.CSS_SELECTOR, selector)
                if elements:
                    reply_area = elements[-1]
                    break
            except Exception:
                continue

        if reply_area is None:
            logger.error("リプライ入力エリアが見つかりません")
            return False

        safe_click(driver, reply_area)
        time.sleep(0.5)

        lines = reply_text.split("\n")
        for i, line in enumerate(lines):
            reply_area.send_keys(line)
            if i < len(lines) - 1:
                reply_area.send_keys(Keys.RETURN)
            time.sleep(0.1)

        human_delay(1.0, 2.0)

        # Reply/返信 ボタン
        posted = False
        for label in ["Reply", "Post", "返信", "投稿"]:
            try:
                btn = driver.find_element(
                    By.XPATH,
                    f"//div[@role='button' and contains(text(), '{label}')]"
                    f" | //button[contains(text(), '{label}')]"
                )
                safe_click(driver, btn)
                posted = True
                break
            except Exception:
                continue

        if not posted:
            try:
                btns = driver.find_elements(By.CSS_SELECTOR, 'div[role="button"]')
                for btn in btns:
                    txt = btn.text.strip().lower()
                    if txt in ("reply", "post", "返信", "投稿"):
                        safe_click(driver, btn)
                        posted = True
                        break
            except Exception:
                pass

        if posted:
            time.sleep(2)
            logger.info(f"リプライ投稿完了: {reply_text[:40]}...")
            return True
        else:
            logger.error("リプライ投稿ボタンが見つかりません")
            return False

    except Exception as e:
        logger.error(f"リプライエラー: {e}", exc_info=True)
        return False


def follow_user(driver, username: str) -> bool:
    """ユーザーをフォローする"""
    from selenium.webdriver.common.by import By

    try:
        driver.get(f"{THREADS_BASE}/@{username}")
        time.sleep(4)

        # Followボタン — Threads では div[role="button"] にテキスト "Follow" がある
        follow_btn = None
        btns = driver.find_elements(By.CSS_SELECTOR, 'div[role="button"], button')
        for btn in btns:
            txt = btn.text.strip()
            if txt in ("Follow", "フォロー", "フォローする"):
                follow_btn = btn
                break
            elif txt in ("Following", "フォロー中", "Requested", "リクエスト済み"):
                logger.info(f"@{username}: 既にフォロー中")
                return True

        if follow_btn is None:
            logger.warning(f"@{username}: Followボタンが見つかりません")
            return False

        safe_click(driver, follow_btn)
        human_delay(1.0, 2.0)
        logger.info(f"@{username} をフォロー")
        return True

    except Exception as e:
        logger.error(f"フォローエラー (@{username}): {e}")
        return False


def repost(driver, post_element) -> bool:
    """投稿をリポストする"""
    from selenium.webdriver.common.by import By

    try:
        # リポストアイコン
        repost_icon = None
        for label in ["Repost", "リポスト", "再投稿"]:
            try:
                repost_icon = post_element.find_element(
                    By.CSS_SELECTOR, f'svg[aria-label="{label}"]'
                )
                break
            except Exception:
                continue

        if repost_icon is None:
            return False

        safe_click(driver, repost_icon)
        time.sleep(1.5)

        # 「Repost」メニューアイテムをクリック
        for label in ["Repost", "リポスト"]:
            try:
                menu_item = driver.find_element(
                    By.XPATH,
                    f"//*[contains(text(), '{label}') and not(contains(text(), 'Quote'))]"
                )
                safe_click(driver, menu_item)
                time.sleep(2)
                logger.info("リポスト完了")
                return True
            except Exception:
                continue

        return False

    except Exception as e:
        logger.error(f"リポストエラー: {e}")
        return False

# ============================================================================
# タスク関数
# ============================================================================

def task_threads_post(dry_run=False) -> bool:
    """オリジナル投稿"""
    state = load_state()
    if not check_daily_limit(state, "threads_post"):
        return False

    cat_idx = state.get("threads_category_index", 0)
    history = state.get("threads_post_history", [])

    text, next_idx = generate_threads_post(cat_idx, history)

    logger.info(f"[threads_post] カテゴリ: {THREADS_CATEGORY_ORDER[cat_idx % len(THREADS_CATEGORY_ORDER)]}")
    logger.info(f"[threads_post] テキスト:\n{text}")

    if dry_run:
        logger.info("[threads_post] dry-run — 投稿スキップ")
        return True

    driver = get_driver()
    if not ensure_threads_login(driver):
        return False

    success = compose_and_post(driver, text)
    if success:
        state["threads_category_index"] = next_idx
        history.append(text)
        state["threads_post_history"] = history[-10:]
        increment_count(state, "threads_post")
        save_state(state)
    return success


def task_threads_reply(dry_run=False, count=1) -> bool:
    """人気投稿にLLMリプライ"""
    state = load_state()

    driver = get_driver()
    if not ensure_threads_login(driver):
        return False

    query = random.choice(THREADS_SEARCH_QUERIES)
    posts = find_threads_posts(driver, query, max_results=15)

    if not posts:
        logger.warning("[threads_reply] 投稿が見つかりません")
        return False

    # 穴場スコアでソート (高い順)
    posts.sort(key=lambda p: p["score"], reverse=True)

    replied = 0
    for post in posts:
        if replied >= count:
            break
        if not check_daily_limit(state, "threads_reply"):
            break

        post_text = post["text"]
        author = post["author"]

        if len(post_text) < 15:
            continue

        logger.info(f"[threads_reply] 対象: @{author} (score={post['score']:.1f})")

        if dry_run:
            logger.info("[threads_reply] dry-run — スキップ")
            replied += 1
            continue

        reply_text = generate_reply_with_llm(post_text, author)
        if not reply_text:
            continue

        # 検索ページに戻って対象投稿を再取得
        posts_fresh = find_threads_posts(driver, query, max_results=15)
        target = None
        for p in posts_fresh:
            if p["author"] == author and p["text"][:50] == post_text[:50]:
                target = p
                break

        if target is None:
            # 元のpost_elementを使う (stale可能性あり)
            target = post

        success = reply_to_post(driver, target["element"], reply_text)
        if success:
            increment_count(state, "threads_reply")
            replied += 1
            human_delay(5.0, 15.0)

    return replied > 0


def task_threads_like(dry_run=False, count=5) -> bool:
    """コスメ系投稿にいいね"""
    state = load_state()

    driver = get_driver()
    if not ensure_threads_login(driver):
        return False

    query = random.choice(THREADS_SEARCH_QUERIES)
    posts = find_threads_posts(driver, query, max_results=20)

    if not posts:
        logger.warning("[threads_like] 投稿が見つかりません")
        return False

    liked = 0
    for post in posts:
        if liked >= count:
            break
        if not check_daily_limit(state, "threads_like"):
            break

        if dry_run:
            logger.info(f"[threads_like] dry-run: @{post['author']}")
            liked += 1
            continue

        if like_post(driver, post["element"]):
            increment_count(state, "threads_like")
            liked += 1
            human_delay(2.0, 5.0)

    logger.info(f"[threads_like] {liked}件いいね完了")
    return liked > 0


def task_threads_follow(dry_run=False, count=3) -> bool:
    """コスメ系アカウントフォロー"""
    state = load_state()

    driver = get_driver()
    if not ensure_threads_login(driver):
        return False

    # 検索して投稿者をフォロー
    query = random.choice(THREADS_SEARCH_QUERIES)
    posts = find_threads_posts(driver, query, max_results=15)

    if not posts:
        logger.warning("[threads_follow] 投稿が見つかりません")
        return False

    followed = 0
    seen_authors = set()
    for post in posts:
        if followed >= count:
            break
        if not check_daily_limit(state, "threads_follow"):
            break

        author = post["author"].lstrip("@").split("\n")[0].strip()
        if not author or author in seen_authors:
            continue
        seen_authors.add(author)

        if dry_run:
            logger.info(f"[threads_follow] dry-run: @{author}")
            followed += 1
            continue

        if follow_user(driver, author):
            increment_count(state, "threads_follow")
            followed += 1
            human_delay(3.0, 8.0)

    logger.info(f"[threads_follow] {followed}人フォロー完了")
    return followed > 0


def task_threads_search_engage(dry_run=False, count=3) -> bool:
    """検索→いいね+リプ複合"""
    state = load_state()

    driver = get_driver()
    if not ensure_threads_login(driver):
        return False

    query = random.choice(THREADS_SEARCH_QUERIES)
    posts = find_threads_posts(driver, query, max_results=15)

    if not posts:
        logger.warning("[threads_search_engage] 投稿が見つかりません")
        return False

    # 穴場スコア順
    posts.sort(key=lambda p: p["score"], reverse=True)

    engaged = 0
    for post in posts:
        if engaged >= count:
            break
        if not check_daily_limit(state, "threads_search_engage"):
            break

        if dry_run:
            logger.info(f"[threads_search_engage] dry-run: @{post['author']}")
            engaged += 1
            continue

        # いいね
        like_post(driver, post["element"])
        human_delay(1.0, 3.0)

        # 短すぎる投稿にはリプしない
        if len(post["text"]) < 20:
            increment_count(state, "threads_search_engage")
            engaged += 1
            continue

        # LLMリプライ
        reply_text = generate_reply_with_llm(post["text"], post["author"])
        if reply_text:
            # 検索ページに戻る
            posts_fresh = find_threads_posts(driver, query, max_results=15)
            target = None
            for p in posts_fresh:
                if p["author"] == post["author"] and p["text"][:50] == post["text"][:50]:
                    target = p
                    break
            if target:
                reply_to_post(driver, target["element"], reply_text)

        increment_count(state, "threads_search_engage")
        engaged += 1
        human_delay(5.0, 15.0)

    logger.info(f"[threads_search_engage] {engaged}件エンゲージメント完了")
    return engaged > 0


def task_threads_repost(dry_run=False, count=1) -> bool:
    """バズ投稿をリポスト"""
    state = load_state()

    driver = get_driver()
    if not ensure_threads_login(driver):
        return False

    query = random.choice(THREADS_SEARCH_QUERIES)
    posts = find_threads_posts(driver, query, max_results=15)

    if not posts:
        logger.warning("[threads_repost] 投稿が見つかりません")
        return False

    # likes が多い順
    posts.sort(key=lambda p: p["likes"], reverse=True)

    reposted = 0
    for post in posts:
        if reposted >= count:
            break
        if not check_daily_limit(state, "threads_repost"):
            break

        if dry_run:
            logger.info(f"[threads_repost] dry-run: @{post['author']}")
            reposted += 1
            continue

        if repost(driver, post["element"]):
            increment_count(state, "threads_repost")
            reposted += 1
            human_delay(3.0, 8.0)

    logger.info(f"[threads_repost] {reposted}件リポスト完了")
    return reposted > 0

# ============================================================================
# タスク関数マップ
# ============================================================================

THREADS_TASK_FUNCTIONS = {
    "threads_post": lambda dr=False, c=1: task_threads_post(dry_run=dr),
    "threads_reply": lambda dr=False, c=1: task_threads_reply(dry_run=dr, count=c),
    "threads_like": lambda dr=False, c=5: task_threads_like(dry_run=dr, count=c),
    "threads_follow": lambda dr=False, c=3: task_threads_follow(dry_run=dr, count=c),
    "threads_search_engage": lambda dr=False, c=3: task_threads_search_engage(dry_run=dr, count=c),
    "threads_repost": lambda dr=False, c=1: task_threads_repost(dry_run=dr, count=c),
}

THREADS_DAILY_LIMITS = DAILY_LIMITS

# ============================================================================
# タスク実行
# ============================================================================

def run_task(task_name: str, dry_run=False, count=None) -> bool:
    """タスクを実行"""
    if task_name not in THREADS_TASK_FUNCTIONS:
        logger.error(f"不明なタスク: {task_name}")
        return False

    logger.info(f"=== タスク開始: {task_name} ===")

    try:
        func = THREADS_TASK_FUNCTIONS[task_name]
        if count is not None:
            result = func(dr=dry_run, c=count)
        else:
            result = func(dr=dry_run)

        if result:
            logger.info(f"=== タスク完了: {task_name} (成功) ===")
        else:
            logger.warning(f"=== タスク完了: {task_name} (失敗) ===")
        return result

    except Exception as e:
        logger.error(f"=== タスク例外: {task_name}: {e} ===", exc_info=True)
        return False


# ============================================================================
# CLI
# ============================================================================

def main():
    parser = argparse.ArgumentParser(description="lisa threads growth bot")
    parser.add_argument("--task", required=True, choices=list(THREADS_TASK_FUNCTIONS.keys()))
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--count", type=int, default=None)
    args = parser.parse_args()

    success = run_task(args.task, dry_run=args.dry_run, count=args.count)
    sys.exit(0 if success else 1)


if __name__ == "__main__":
    main()
