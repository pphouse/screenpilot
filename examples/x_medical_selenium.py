#!/usr/bin/env python3
"""
X (Twitter) 医療業界ニュース・補助金・診療報酬 Seleniumスクレイパー

Usage:
    python3 examples/x_medical_selenium.py
    python3 examples/x_medical_selenium.py --max-tweets 10
    python3 examples/x_medical_selenium.py --category fee_revision
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
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.common.exceptions import (
    TimeoutException, NoSuchElementException, StaleElementReferenceException,
)

from x_medical_config import MEDICAL_TOPICS, CSV_COLUMNS, classify_sentiment

OUTPUT_DIR = Path("recordings/x_medical_data")
OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

AUTH_TOKEN = os.environ.get("X_AUTH_TOKEN", "")
CT0 = os.environ.get("X_CT0", "")

MAX_TWEETS_PER_QUERY = 20
SCROLL_PAUSE_MIN = 2.0
SCROLL_PAUSE_MAX = 5.0
SEARCH_PAUSE_MIN = 5.0
SEARCH_PAUSE_MAX = 10.0


def create_driver() -> webdriver.Chrome:
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
    driver.get("https://x.com")
    time.sleep(2)
    for name, value in [("auth_token", AUTH_TOKEN), ("ct0", CT0)]:
        try:
            driver.add_cookie({"name": name, "value": value, "domain": ".x.com", "path": "/", "secure": True})
        except Exception as e:
            print(f"  [WARN] Cookie注入失敗 ({name}): {e}")
    driver.refresh()
    time.sleep(3)


def is_logged_in(driver: webdriver.Chrome) -> bool:
    try:
        driver.get("https://x.com/home")
        time.sleep(3)
        WebDriverWait(driver, 10).until(
            EC.presence_of_element_located((By.CSS_SELECTOR, '[data-testid="primaryColumn"]'))
        )
        return True
    except TimeoutException:
        return False


def parse_engagement(label: str) -> dict:
    result = {"replies": 0, "retweets": 0, "likes": 0, "views": 0}
    if not label:
        return result
    for pat, key in [
        (r"(\d[\d,]*)\s*repl", "replies"), (r"(\d[\d,]*)\s*repost", "retweets"),
        (r"(\d[\d,]*)\s*like", "likes"), (r"(\d[\d,]*)\s*view", "views"),
        (r"(\d[\d,]*)\s*件の返信", "replies"), (r"(\d[\d,]*)\s*件のリポスト", "retweets"),
        (r"(\d[\d,]*)\s*件のいいね", "likes"), (r"(\d[\d,]*)\s*件の表示", "views"),
    ]:
        m = re.search(pat, label, re.IGNORECASE)
        if m:
            result[key] = int(m.group(1).replace(",", ""))
    return result


def extract_tweets(driver: webdriver.Chrome) -> list[dict]:
    tweets = []
    try:
        articles = driver.find_elements(By.CSS_SELECTOR, 'article[data-testid="tweet"]')
    except Exception:
        return tweets

    for article in articles:
        try:
            try:
                text = article.find_element(By.CSS_SELECTOR, 'div[data-testid="tweetText"]').text.strip()
            except NoSuchElementException:
                continue
            if not text:
                continue

            author_handle, author_name = "", ""
            try:
                links = article.find_elements(By.CSS_SELECTOR, 'div[data-testid="User-Name"] a')
                if links:
                    author_name = links[0].text.strip()
                    for lnk in links:
                        href = lnk.get_attribute("href") or ""
                        if href.startswith("https://x.com/") and "/status/" not in href:
                            author_handle = href.split("/")[-1]
                            break
            except (NoSuchElementException, StaleElementReferenceException):
                pass

            timestamp, tweet_url = "", ""
            try:
                time_el = article.find_element(By.CSS_SELECTOR, "time[datetime]")
                timestamp = time_el.get_attribute("datetime")
                tweet_url = time_el.find_element(By.XPATH, "./..").get_attribute("href") or ""
            except (NoSuchElementException, StaleElementReferenceException):
                pass

            engagement = {"replies": 0, "retweets": 0, "likes": 0, "views": 0}
            try:
                group = article.find_element(By.CSS_SELECTOR, 'div[role="group"]')
                group_label = group.get_attribute("aria-label") or ""
                if group_label:
                    engagement = parse_engagement(group_label)
                else:
                    for el in group.find_elements(By.CSS_SELECTOR, "button, a"):
                        eng = parse_engagement(el.get_attribute("aria-label") or "")
                        for k, v in eng.items():
                            if v > 0:
                                engagement[k] = v
            except (NoSuchElementException, StaleElementReferenceException):
                pass

            tweets.append({
                "tweet_text": text, "author_handle": author_handle, "author_name": author_name,
                "timestamp": timestamp, "tweet_url": tweet_url, **engagement,
            })
        except StaleElementReferenceException:
            continue
    return tweets


def scrape_query(driver: webdriver.Chrome, query: str, max_tweets: int) -> list[dict]:
    url = f"https://x.com/search?q={quote_plus(query)}&src=typed_query&f=live"
    print(f"    検索: {query}")
    driver.get(url)
    time.sleep(random.uniform(3, 5))

    all_tweets, seen = [], set()
    scroll_attempts = 0

    while len(all_tweets) < max_tweets and scroll_attempts < 10:
        new_count = 0
        for t in extract_tweets(driver):
            key = t["tweet_url"] or t["tweet_text"][:80]
            if key not in seen:
                seen.add(key)
                all_tweets.append(t)
                new_count += 1
        scroll_attempts = scroll_attempts + 1 if new_count == 0 else 0
        if len(all_tweets) >= max_tweets:
            break
        driver.execute_script("window.scrollTo(0, document.body.scrollHeight);")
        time.sleep(random.uniform(SCROLL_PAUSE_MIN, SCROLL_PAUSE_MAX))

    print(f"    → {len(all_tweets)}件")
    return all_tweets[:max_tweets]


def run_scraper(max_tweets: int = MAX_TWEETS_PER_QUERY, category_filter: str | None = None):
    topics = MEDICAL_TOPICS
    if category_filter:
        topics = [t for t in topics if t.category == category_filter]

    print("=" * 60)
    print("  X 医療業界ツイート スクレイパー")
    print(f"  トピック数: {len(topics)}")
    print(f"  最大ツイート/クエリ: {max_tweets}")
    if category_filter:
        print(f"  カテゴリ: {category_filter}")
    print("=" * 60)

    driver = create_driver()
    try:
        print("\n[1/3] ログイン...")
        if not is_logged_in(driver):
            inject_cookies(driver)
            if not is_logged_in(driver):
                print("  [ERROR] ログイン失敗")
                return
        print("  OK")

        print("\n[2/3] ツイート収集...")
        all_rows = []
        scraped_at = datetime.now(timezone.utc).isoformat()

        for i, topic in enumerate(topics):
            print(f"\n  [{i+1}/{len(topics)}] {topic.name} ({topic.category})")
            query = topic.search_queries[0]
            tweets = scrape_query(driver, query, max_tweets)
            for t in tweets:
                all_rows.append({
                    "topic_name": topic.name, "category": topic.category,
                    "search_query": query, "sentiment": classify_sentiment(t["tweet_text"]),
                    "scraped_at": scraped_at, **t,
                })
            if i < len(topics) - 1:
                pause = random.uniform(SEARCH_PAUSE_MIN, SEARCH_PAUSE_MAX)
                print(f"    ({pause:.1f}秒待機)")
                time.sleep(pause)

        print(f"\n[3/3] CSV保存...")
        if not all_rows:
            print("  ツイート取得ゼロ")
            return

        df = pd.DataFrame(all_rows, columns=CSV_COLUMNS)
        before = len(df)
        df = df.drop_duplicates(subset=["tweet_url"], keep="first")
        if before != len(df):
            print(f"  重複除去: {before} → {len(df)}件")

        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        csv_all = OUTPUT_DIR / f"medical_all_{ts}.csv"
        df.to_csv(csv_all, index=False, encoding="utf-8-sig")
        print(f"  保存: {csv_all} ({len(df)}件)")

        # カテゴリ別サマリー
        print("\n  --- カテゴリ別 ---")
        for cat, grp in df.groupby("category"):
            cat_csv = OUTPUT_DIR / f"medical_{cat}_{ts}.csv"
            grp.to_csv(cat_csv, index=False, encoding="utf-8-sig")
            pos = (grp["sentiment"] == "positive").sum()
            neg = (grp["sentiment"] == "negative").sum()
            neu = (grp["sentiment"] == "neutral").sum()
            print(f"  {cat}: {len(grp)}件 (pos:{pos} neg:{neg} neu:{neu}) → {cat_csv.name}")

        # トピック別サマリー
        print("\n  --- トピック別 ---")
        summary = df.groupby("topic_name").agg(
            count=("tweet_text", "count"),
            positive=("sentiment", lambda x: (x == "positive").sum()),
            negative=("sentiment", lambda x: (x == "negative").sum()),
            neutral=("sentiment", lambda x: (x == "neutral").sum()),
            avg_likes=("likes", "mean"),
        ).reset_index()
        print(summary.to_string(index=False))

    finally:
        driver.quit()

    print("\n" + "=" * 60)
    print("  完了!")
    print("=" * 60)


def main():
    parser = argparse.ArgumentParser(description="X 医療業界ツイートスクレイパー")
    parser.add_argument("--max-tweets", type=int, default=MAX_TWEETS_PER_QUERY)
    parser.add_argument("--category", choices=["news", "subsidy", "fee_revision", "medical_it"], default=None)
    args = parser.parse_args()
    run_scraper(max_tweets=args.max_tweets, category_filter=args.category)


if __name__ == "__main__":
    main()
