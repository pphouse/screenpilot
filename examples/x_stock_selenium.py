#!/usr/bin/env python3
"""
X (Twitter) AI関連日本株 Seleniumスクレイパー
==============================================
Cookie認証でXにログインし、各銘柄ごとにツイートを検索・収集してCSVに保存。

Usage:
    python examples/x_stock_selenium.py
    python examples/x_stock_selenium.py --max-tweets 10
    python examples/x_stock_selenium.py --stocks "さくらインターネット,PKSHA Technology"
"""

import argparse
import os
import re
import random
import time
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import quote_plus

os.environ.setdefault("DISPLAY", ":99")

import pandas as pd
from selenium import webdriver
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.common.exceptions import (
    TimeoutException, NoSuchElementException, StaleElementReferenceException,
)

from x_stock_config import AI_STOCKS, CSV_COLUMNS, classify_sentiment

# ============================================================================
# 定数
# ============================================================================

OUTPUT_DIR = Path("recordings/x_stock_data")
OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

AUTH_TOKEN = os.environ.get("X_AUTH_TOKEN", "")
CT0 = os.environ.get("X_CT0", "")

MAX_TWEETS_PER_QUERY = 20
SCROLL_PAUSE_MIN = 2.0
SCROLL_PAUSE_MAX = 5.0
SEARCH_PAUSE_MIN = 5.0
SEARCH_PAUSE_MAX = 10.0


# ============================================================================
# Selenium helpers
# ============================================================================

def create_driver() -> webdriver.Chrome:
    """Chrome WebDriverを作成 (Cookie注入方式)"""
    opts = Options()
    opts.add_argument("--no-sandbox")
    opts.add_argument("--disable-dev-shm-usage")
    opts.add_argument("--disable-gpu")
    opts.add_argument("--window-size=1920,1080")
    opts.add_argument("--lang=ja-JP")
    opts.add_argument("--disable-blink-features=AutomationControlled")
    opts.add_experimental_option("excludeSwitches", ["enable-automation"])
    opts.add_experimental_option("useAutomationExtension", False)

    driver = webdriver.Chrome(options=opts)
    driver.execute_cdp_cmd("Page.addScriptToEvaluateOnNewDocument", {
        "source": "Object.defineProperty(navigator, 'webdriver', {get: () => undefined})"
    })
    return driver


def inject_cookies(driver: webdriver.Chrome):
    """X の認証Cookieを注入"""
    driver.get("https://x.com")
    time.sleep(2)

    cookies = [
        {"name": "auth_token", "value": AUTH_TOKEN, "domain": ".x.com", "path": "/", "secure": True},
        {"name": "ct0", "value": CT0, "domain": ".x.com", "path": "/", "secure": True},
    ]
    for c in cookies:
        try:
            driver.add_cookie(c)
        except Exception as e:
            print(f"  [WARN] Cookie注入失敗 ({c['name']}): {e}")

    driver.refresh()
    time.sleep(3)


def is_logged_in(driver: webdriver.Chrome) -> bool:
    """ログイン済みか確認"""
    try:
        driver.get("https://x.com/home")
        time.sleep(3)
        # ログイン済みならタイムラインが表示される
        WebDriverWait(driver, 10).until(
            EC.presence_of_element_located((By.CSS_SELECTOR, '[data-testid="primaryColumn"]'))
        )
        return True
    except TimeoutException:
        return False


# ============================================================================
# ツイート抽出
# ============================================================================

def parse_engagement_label(label: str) -> dict:
    """aria-label からエンゲージメント数をパース
    group の aria-label 例: '120 replies, 230 reposts, 1421 likes, 712 bookmarks, 125277 views'
    button の aria-label 例: '120 Replies. Reply'
    link の aria-label 例:   '125277 views. View post analytics'
    """
    result = {"replies": 0, "retweets": 0, "likes": 0, "views": 0}
    if not label:
        return result

    patterns = [
        (r"(\d[\d,]*)\s*repl", "replies"),
        (r"(\d[\d,]*)\s*repost", "retweets"),
        (r"(\d[\d,]*)\s*like", "likes"),
        (r"(\d[\d,]*)\s*view", "views"),
        # 日本語対応
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


def extract_tweets(driver: webdriver.Chrome) -> list[dict]:
    """現在のページからツイートを抽出"""
    tweets = []
    try:
        articles = driver.find_elements(By.CSS_SELECTOR, 'article[data-testid="tweet"]')
    except Exception:
        return tweets

    for article in articles:
        try:
            # テキスト
            try:
                text_el = article.find_element(By.CSS_SELECTOR, 'div[data-testid="tweetText"]')
                text = text_el.text.strip()
            except NoSuchElementException:
                text = ""

            if not text:
                continue

            # 投稿者
            author_handle = ""
            author_name = ""
            try:
                user_links = article.find_elements(By.CSS_SELECTOR, 'div[data-testid="User-Name"] a')
                if user_links:
                    author_name = user_links[0].text.strip()
                    for link in user_links:
                        href = link.get_attribute("href") or ""
                        if href.startswith("https://x.com/") and "/status/" not in href:
                            author_handle = href.split("/")[-1]
                            break
            except (NoSuchElementException, StaleElementReferenceException):
                pass

            # タイムスタンプ
            timestamp = ""
            tweet_url = ""
            try:
                time_el = article.find_element(By.CSS_SELECTOR, "time[datetime]")
                timestamp = time_el.get_attribute("datetime")
                parent_a = time_el.find_element(By.XPATH, "./..")
                tweet_url = parent_a.get_attribute("href") or ""
            except (NoSuchElementException, StaleElementReferenceException):
                pass

            # エンゲージメント — group の aria-label に全メトリクスが入っている
            engagement = {"replies": 0, "retweets": 0, "likes": 0, "views": 0}
            try:
                group = article.find_element(By.CSS_SELECTOR, 'div[role="group"]')
                group_label = group.get_attribute("aria-label") or ""
                if group_label:
                    engagement = parse_engagement_label(group_label)
                else:
                    # フォールバック: 個別 button + a タグ
                    for el in group.find_elements(By.CSS_SELECTOR, "button, a"):
                        label = el.get_attribute("aria-label") or ""
                        eng = parse_engagement_label(label)
                        for k, v in eng.items():
                            if v > 0:
                                engagement[k] = v
            except (NoSuchElementException, StaleElementReferenceException):
                pass

            tweets.append({
                "tweet_text": text,
                "author_handle": author_handle,
                "author_name": author_name,
                "timestamp": timestamp,
                "likes": engagement["likes"],
                "retweets": engagement["retweets"],
                "replies": engagement["replies"],
                "views": engagement["views"],
                "tweet_url": tweet_url,
            })

        except StaleElementReferenceException:
            continue

    return tweets


def scrape_query(driver: webdriver.Chrome, query: str, max_tweets: int) -> list[dict]:
    """1つの検索クエリでツイートを収集"""
    encoded = quote_plus(query)
    url = f"https://x.com/search?q={encoded}&src=typed_query&f=live"
    print(f"    検索中: {query}")
    print(f"    URL: {url}")

    driver.get(url)
    time.sleep(random.uniform(3, 5))

    all_tweets = []
    seen_urls = set()
    scroll_attempts = 0
    max_scrolls = 10

    while len(all_tweets) < max_tweets and scroll_attempts < max_scrolls:
        tweets = extract_tweets(driver)
        new_count = 0

        for t in tweets:
            key = t["tweet_url"] or t["tweet_text"][:80]
            if key not in seen_urls:
                seen_urls.add(key)
                all_tweets.append(t)
                new_count += 1

        if new_count == 0:
            scroll_attempts += 1
        else:
            scroll_attempts = 0

        if len(all_tweets) >= max_tweets:
            break

        # スクロール
        driver.execute_script("window.scrollTo(0, document.body.scrollHeight);")
        time.sleep(random.uniform(SCROLL_PAUSE_MIN, SCROLL_PAUSE_MAX))

    print(f"    → {len(all_tweets)}件 取得")
    return all_tweets[:max_tweets]


# ============================================================================
# メイン処理
# ============================================================================

def run_scraper(max_tweets: int = MAX_TWEETS_PER_QUERY, stock_filter: list[str] | None = None):
    """全銘柄のツイートを収集してCSV保存"""
    print("=" * 60)
    print("  X (Twitter) AI関連日本株 スクレイパー")
    print(f"  対象銘柄: {len(AI_STOCKS)}社")
    print(f"  最大ツイート数/クエリ: {max_tweets}")
    print("=" * 60)

    stocks = AI_STOCKS
    if stock_filter:
        stocks = [s for s in AI_STOCKS if s.name in stock_filter or s.ticker in stock_filter]
        print(f"  フィルタ適用: {[s.name for s in stocks]}")

    driver = create_driver()
    try:
        # ログイン確認
        print("\n[1/3] Xにログイン中...")
        if not is_logged_in(driver):
            print("  Cookie注入でログイン試行...")
            inject_cookies(driver)
            if not is_logged_in(driver):
                print("  [ERROR] ログイン失敗。Cookie情報を確認してください。")
                return
        print("  ログイン成功!")

        # 銘柄ごとにスクレイピング
        print("\n[2/3] ツイート収集開始...")
        all_rows = []
        scraped_at = datetime.now(timezone.utc).isoformat()

        for i, stock in enumerate(stocks):
            print(f"\n  [{i+1}/{len(stocks)}] {stock.name} ({stock.ticker})")

            # 最初のクエリのみ使用 (レート制限対策)
            query = stock.search_queries[0] if stock.search_queries else stock.name
            tweets = scrape_query(driver, query, max_tweets)

            for t in tweets:
                row = {
                    "stock_name": stock.name,
                    "ticker": stock.ticker,
                    "search_query": query,
                    "sentiment": classify_sentiment(t["tweet_text"]),
                    "scraped_at": scraped_at,
                    **t,
                }
                all_rows.append(row)

            # 検索間の遅延
            if i < len(stocks) - 1:
                pause = random.uniform(SEARCH_PAUSE_MIN, SEARCH_PAUSE_MAX)
                print(f"    ({pause:.1f}秒待機...)")
                time.sleep(pause)

        # CSV保存
        print(f"\n[3/3] CSV保存中...")
        if all_rows:
            df = pd.DataFrame(all_rows, columns=CSV_COLUMNS)
            # 重複除去 (tweet_url ベース)
            before = len(df)
            df = df.drop_duplicates(subset=["tweet_url"], keep="first")
            after = len(df)
            if before != after:
                print(f"  重複除去: {before} → {after}件")

            timestamp_str = datetime.now().strftime("%Y%m%d_%H%M%S")
            csv_path = OUTPUT_DIR / f"ai_stocks_{timestamp_str}.csv"
            df.to_csv(csv_path, index=False, encoding="utf-8-sig")
            print(f"  保存完了: {csv_path}")
            print(f"  合計: {len(df)}件")

            # 銘柄別サマリー
            print("\n  --- 銘柄別サマリー ---")
            summary = df.groupby("stock_name").agg(
                tweets=("tweet_text", "count"),
                bullish=("sentiment", lambda x: (x == "bullish").sum()),
                bearish=("sentiment", lambda x: (x == "bearish").sum()),
                neutral=("sentiment", lambda x: (x == "neutral").sum()),
                avg_likes=("likes", "mean"),
            ).reset_index()
            print(summary.to_string(index=False))

            # 個別銘柄CSVも保存
            for stock_name, group in df.groupby("stock_name"):
                safe_name = stock_name.replace(" ", "_").replace("/", "_")
                stock_csv = OUTPUT_DIR / f"{safe_name}_{timestamp_str}.csv"
                group.to_csv(stock_csv, index=False, encoding="utf-8-sig")
                print(f"    {stock_name}: {len(group)}件 → {stock_csv.name}")
        else:
            print("  ツイートが取得できませんでした。")

    finally:
        driver.quit()

    print("\n" + "=" * 60)
    print("  完了!")
    print("=" * 60)


def main():
    parser = argparse.ArgumentParser(description="X AI関連日本株スクレイパー")
    parser.add_argument("--max-tweets", type=int, default=MAX_TWEETS_PER_QUERY,
                        help=f"1クエリあたりの最大ツイート数 (default: {MAX_TWEETS_PER_QUERY})")
    parser.add_argument("--stocks", type=str, default=None,
                        help="対象銘柄 (カンマ区切り、例: 'さくらインターネット,PKSHA Technology')")
    args = parser.parse_args()

    stock_filter = args.stocks.split(",") if args.stocks else None
    run_scraper(max_tweets=args.max_tweets, stock_filter=stock_filter)


if __name__ == "__main__":
    main()
