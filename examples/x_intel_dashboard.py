#!/usr/bin/env python3
"""
X (Twitter) マーケットインテリジェンス — 汎用Webダッシュボード
================================================================
任意のキーワード・戦略をUI上で設定してスクレイプ実行 → 結果閲覧。
Flask + Selenium + Chart.js。

Usage:
    python3 examples/x_intel_dashboard.py
    python3 examples/x_intel_dashboard.py --port 8080
"""

import os
import re
import json
import random
import time
import uuid
import threading
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import quote_plus

os.environ.setdefault("DISPLAY", ":99")

from flask import Flask, jsonify, request, render_template
from selenium import webdriver
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.common.exceptions import (
    TimeoutException, NoSuchElementException, StaleElementReferenceException,
)

from x_trust_lib import TrustScorer

# ============================================================================
# 定数
# ============================================================================

AUTH_TOKEN = os.environ.get("X_AUTH_TOKEN", "")
CT0 = os.environ.get("X_CT0", "")

RUNS_DIR = Path("recordings/x_intel_runs")
RUNS_DIR.mkdir(parents=True, exist_ok=True)

SCROLL_PAUSE = (2.0, 5.0)
SEARCH_PAUSE = (5.0, 10.0)

DEFAULT_PAIN_KEYWORDS = {
    "困った": 3, "困って": 3, "使いにくい": 3, "不満": 3, "つらい": 3,
    "やばい": 2, "限界": 3, "崩壊": 2, "ストレス": 2,
    "乗り換え": 5, "リプレイス": 5, "移行": 4, "検討中": 5, "導入検討": 5,
    "比較": 4, "見積": 5, "デモ": 5, "トライアル": 5, "無料体験": 4,
    "大変": 2, "負担": 2, "残業": 3, "時間かかる": 2, "間に合わない": 3,
    "手作業": 3, "手入力": 3, "二重入力": 4, "ミス": 2, "返戻": 2,
    "人手不足": 3, "担当者いない": 4, "一人で": 3, "属人化": 3,
    "高い": 2, "コスト": 2, "予算": 3, "費用": 2,
}

# ============================================================================
# ジョブ管理
# ============================================================================

_current_job = {
    "running": False,
    "run_id": None,
    "progress": "",
    "step": 0,
    "total_steps": 0,
    "error": None,
}
_job_lock = threading.Lock()


def _update_progress(msg: str, step: int = 0, total: int = 0):
    with _job_lock:
        _current_job["progress"] = msg
        if step:
            _current_job["step"] = step
        if total:
            _current_job["total_steps"] = total


# ============================================================================
# Selenium ユーティリティ
# ============================================================================

def create_driver() -> webdriver.Chrome:
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
    driver = webdriver.Chrome(options=opts)
    driver.execute_cdp_cmd("Page.addScriptToEvaluateOnNewDocument", {
        "source": "Object.defineProperty(navigator, 'webdriver', {get: () => undefined})"
    })
    return driver


def login(driver: webdriver.Chrome) -> bool:
    try:
        driver.get("https://x.com/home")
        time.sleep(3)
        WebDriverWait(driver, 10).until(
            EC.presence_of_element_located((By.CSS_SELECTOR, '[data-testid="primaryColumn"]'))
        )
        return True
    except TimeoutException:
        pass
    driver.get("https://x.com")
    time.sleep(2)
    for name, value in [("auth_token", AUTH_TOKEN), ("ct0", CT0)]:
        try:
            driver.add_cookie({"name": name, "value": value, "domain": ".x.com", "path": "/", "secure": True})
        except Exception:
            pass
    driver.refresh()
    time.sleep(3)
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
        (r"(\d[\d,]*)\s*(?:repl|件の返信)", "replies"),
        (r"(\d[\d,]*)\s*(?:repost|件のリポスト)", "retweets"),
        (r"(\d[\d,]*)\s*(?:like|件のいいね)", "likes"),
        (r"(\d[\d,]*)\s*(?:view|件の表示)", "views"),
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
        time.sleep(random.uniform(*SCROLL_PAUSE))

    return all_tweets[:max_tweets]


def compute_pain_score(text: str, pain_keywords: dict) -> int:
    score = 0
    for kw, weight in pain_keywords.items():
        if kw in text:
            score += weight
    return score


# ============================================================================
# スクレイプ実行 (バックグラウンドスレッド)
# ============================================================================

def _run_scrape_job(run_id: str, name: str, queries: list[dict],
                    pain_keywords: dict, max_tweets: int, run_trust: bool):
    run_dir = RUNS_DIR / run_id
    run_dir.mkdir(parents=True, exist_ok=True)

    total_queries = len(queries)
    total_steps = total_queries + (1 if run_trust else 0) + 1  # queries + trust + save
    _update_progress("ドライバー起動中...", step=0, total=total_steps)

    driver = None
    try:
        driver = create_driver()
        _update_progress("ログイン中...")

        if not login(driver):
            with _job_lock:
                _current_job["error"] = "ログイン失敗"
                _current_job["running"] = False
            return

        # Scrape queries
        all_tweets = []
        scraped_at = datetime.now(timezone.utc).isoformat()

        for i, q in enumerate(queries):
            label = q.get("label", f"Query {i+1}")
            query = q.get("query", "")
            _update_progress(f"スクレイプ中: {label} ({i+1}/{total_queries})", step=i+1, total=total_steps)

            tweets = scrape_query(driver, query, max_tweets)
            for t in tweets:
                ps = compute_pain_score(t["tweet_text"], pain_keywords)
                all_tweets.append({
                    "query_label": label,
                    "search_query": query,
                    "pain_score": ps,
                    "scraped_at": scraped_at,
                    **t,
                })

            if i < total_queries - 1:
                time.sleep(random.uniform(*SEARCH_PAUSE))

        # Dedup
        seen = set()
        deduped = []
        for t in all_tweets:
            key = t.get("tweet_url") or t["tweet_text"][:80]
            if key not in seen:
                seen.add(key)
                deduped.append(t)
        all_tweets = deduped

        # Save tweets
        tweets_path = run_dir / "tweets.json"
        with open(tweets_path, "w") as f:
            json.dump(all_tweets, f, indent=2, ensure_ascii=False, default=str)

        # Trust analysis
        trust_results = []
        if run_trust and all_tweets:
            _update_progress("Trust分析中...", step=total_queries + 1, total=total_steps)

            handles = list({t["author_handle"] for t in all_tweets if t.get("author_handle")})
            handles = handles[:30]

            if handles:
                scorer = TrustScorer(
                    driver=driver,
                    output_dir=run_dir / "trust",
                    download_icons=False,
                    take_screenshots=False,
                    quiet=True,
                )
                raw_results = scorer.score_many(handles, max_tweets=3, pause_range=(2.0, 4.0))
                trust_results = [{
                    "handle": r.get("handle"),
                    "display_name": r.get("display_name"),
                    "bio": (r.get("bio") or "")[:150],
                    "followers": r.get("followers_count", 0),
                    "is_verified": r.get("is_verified"),
                    "trust_score": r.get("total_score", 0),
                    "trust_rank": r.get("rank", "?"),
                    "engagement_rate": r.get("engagement_rate", 0),
                } for r in raw_results]

        trust_path = run_dir / "trust.json"
        with open(trust_path, "w") as f:
            json.dump(trust_results, f, indent=2, ensure_ascii=False, default=str)

        # Pain leads
        leads = sorted(
            [t for t in all_tweets if t["pain_score"] > 0],
            key=lambda x: x["pain_score"], reverse=True,
        )
        leads_path = run_dir / "leads.json"
        with open(leads_path, "w") as f:
            json.dump(leads, f, indent=2, ensure_ascii=False, default=str)

        # Summary
        unique_authors = len({t["author_handle"] for t in all_tweets if t.get("author_handle")})
        total_views = sum(t.get("views", 0) for t in all_tweets)
        avg_views = round(total_views / len(all_tweets), 1) if all_tweets else 0

        query_counts = {}
        for t in all_tweets:
            ql = t["query_label"]
            query_counts[ql] = query_counts.get(ql, 0) + 1

        views_distribution = {}
        for t in all_tweets:
            v = t.get("views", 0)
            if v == 0:
                bucket = "0"
            elif v < 100:
                bucket = "1-99"
            elif v < 1000:
                bucket = "100-999"
            elif v < 10000:
                bucket = "1K-9.9K"
            elif v < 100000:
                bucket = "10K-99K"
            else:
                bucket = "100K+"
            views_distribution[bucket] = views_distribution.get(bucket, 0) + 1

        pain_distribution = {"0": 0, "1-3": 0, "4-6": 0, "7-10": 0, "11+": 0}
        for t in all_tweets:
            ps = t.get("pain_score", 0)
            if ps == 0:
                pain_distribution["0"] += 1
            elif ps <= 3:
                pain_distribution["1-3"] += 1
            elif ps <= 6:
                pain_distribution["4-6"] += 1
            elif ps <= 10:
                pain_distribution["7-10"] += 1
            else:
                pain_distribution["11+"] += 1

        summary = {
            "run_id": run_id,
            "name": name,
            "created_at": datetime.now(timezone.utc).isoformat(),
            "queries": queries,
            "pain_keywords": pain_keywords,
            "max_tweets": max_tweets,
            "run_trust": run_trust,
            "total_tweets": len(all_tweets),
            "unique_authors": unique_authors,
            "pain_leads_count": len(leads),
            "avg_views": avg_views,
            "trust_analyzed": len(trust_results),
            "query_counts": query_counts,
            "views_distribution": views_distribution,
            "pain_distribution": pain_distribution,
        }
        summary_path = run_dir / "summary.json"
        with open(summary_path, "w") as f:
            json.dump(summary, f, indent=2, ensure_ascii=False, default=str)

        _update_progress("完了!", step=total_steps, total=total_steps)

    except Exception as e:
        with _job_lock:
            _current_job["error"] = str(e)
    finally:
        if driver:
            try:
                driver.quit()
            except Exception:
                pass
        with _job_lock:
            _current_job["running"] = False


# ============================================================================
# Flask アプリ
# ============================================================================

app = Flask(__name__)


@app.route("/")
def index():
    return render_template("dashboard.html")


@app.route("/api/runs")
def api_runs():
    runs = []
    if RUNS_DIR.exists():
        for d in sorted(RUNS_DIR.iterdir(), reverse=True):
            if d.is_dir():
                summary_path = d / "summary.json"
                if summary_path.exists():
                    with open(summary_path) as f:
                        s = json.load(f)
                    runs.append({
                        "run_id": s.get("run_id", d.name),
                        "name": s.get("name", d.name),
                        "created_at": s.get("created_at", ""),
                        "total_tweets": s.get("total_tweets", 0),
                        "unique_authors": s.get("unique_authors", 0),
                        "pain_leads_count": s.get("pain_leads_count", 0),
                        "trust_analyzed": s.get("trust_analyzed", 0),
                    })
    return jsonify(runs)


@app.route("/api/runs/<run_id>/tweets")
def api_tweets(run_id):
    path = RUNS_DIR / run_id / "tweets.json"
    if not path.exists():
        return jsonify({"error": "not found"}), 404
    with open(path) as f:
        tweets = json.load(f)

    # Filters
    query_label = request.args.get("query_label")
    min_pain = request.args.get("min_pain", type=int)
    if query_label:
        tweets = [t for t in tweets if t.get("query_label") == query_label]
    if min_pain is not None:
        tweets = [t for t in tweets if t.get("pain_score", 0) >= min_pain]

    return jsonify(tweets)


@app.route("/api/runs/<run_id>/leads")
def api_leads(run_id):
    path = RUNS_DIR / run_id / "leads.json"
    if not path.exists():
        return jsonify({"error": "not found"}), 404
    with open(path) as f:
        return jsonify(json.load(f))


@app.route("/api/runs/<run_id>/influencers")
def api_influencers(run_id):
    path = RUNS_DIR / run_id / "trust.json"
    if not path.exists():
        return jsonify({"error": "not found"}), 404
    with open(path) as f:
        return jsonify(json.load(f))


@app.route("/api/runs/<run_id>/summary")
def api_summary(run_id):
    path = RUNS_DIR / run_id / "summary.json"
    if not path.exists():
        return jsonify({"error": "not found"}), 404
    with open(path) as f:
        return jsonify(json.load(f))


@app.route("/api/scrape", methods=["POST"])
def api_scrape():
    with _job_lock:
        if _current_job["running"]:
            return jsonify({"error": "既にジョブが実行中です"}), 409

    data = request.get_json(force=True)
    name = data.get("name", "Untitled")
    queries = data.get("queries", [])
    pain_keywords = data.get("pain_keywords", DEFAULT_PAIN_KEYWORDS)
    max_tweets = min(data.get("max_tweets", 10), 30)
    run_trust = data.get("run_trust", False)

    if not queries:
        return jsonify({"error": "queries が空です"}), 400

    run_id = datetime.now().strftime("%Y%m%d_%H%M%S") + "_" + uuid.uuid4().hex[:6]

    with _job_lock:
        _current_job["running"] = True
        _current_job["run_id"] = run_id
        _current_job["progress"] = "開始準備中..."
        _current_job["step"] = 0
        _current_job["total_steps"] = 0
        _current_job["error"] = None

    thread = threading.Thread(
        target=_run_scrape_job,
        args=(run_id, name, queries, pain_keywords, max_tweets, run_trust),
        daemon=True,
    )
    thread.start()

    return jsonify({"run_id": run_id, "status": "started"})


@app.route("/api/scrape/status")
def api_scrape_status():
    with _job_lock:
        return jsonify({
            "running": _current_job["running"],
            "run_id": _current_job["run_id"],
            "progress": _current_job["progress"],
            "step": _current_job["step"],
            "total_steps": _current_job["total_steps"],
            "error": _current_job["error"],
        })


# ============================================================================
# Google Trends API
# ============================================================================

TRENDS_DIR = Path("recordings/google_trends")


@app.route("/api/trends/latest")
def api_trends_latest():
    """最新のトレンドデータ (trending_full_JP_*.json) を返す。"""
    if not TRENDS_DIR.exists():
        return jsonify({"error": "no trends data"}), 404
    json_files = sorted(TRENDS_DIR.glob("trending_full_JP_*.json"), reverse=True)
    if not json_files:
        # Fall back to CSV
        csv_files = sorted(TRENDS_DIR.glob("trending_*JP_*.csv"), reverse=True)
        if not csv_files:
            return jsonify({"error": "no trends data"}), 404
        import csv as csv_mod
        with open(csv_files[0], encoding="utf-8-sig") as f:
            reader = csv_mod.DictReader(f)
            rows = list(reader)
        return jsonify({"file": csv_files[0].name, "count": len(rows), "data": rows[:100]})
    with open(json_files[0], encoding="utf-8") as f:
        data = json.load(f)
    return jsonify({"file": json_files[0].name, "count": len(data), "data": data[:200]})


@app.route("/api/trends/refresh", methods=["POST"])
def api_trends_refresh():
    """trendspy で最新トレンドデータを再取得。"""
    try:
        from trendspy import Trends as TrendSpy
        import csv as csv_mod

        tr = TrendSpy()
        keywords = tr.trending_now(geo="JP")
        rows = []
        for kw in keywords:
            topic_names = []
            try:
                topics = kw.topic_names or []
                topic_names = topics if isinstance(topics, list) else [str(topics)]
            except Exception:
                pass
            related_kws = []
            try:
                for tk in (kw.trend_keywords or []):
                    related_kws.append(tk.keyword if hasattr(tk, "keyword") else str(tk))
            except Exception:
                pass
            # Parse started_timestamp from epoch list
            started_iso = ""
            try:
                ts_val = kw.started_timestamp
                if isinstance(ts_val, (list, tuple)) and ts_val:
                    started_iso = datetime.fromtimestamp(ts_val[0], tz=timezone.utc).isoformat()
                elif isinstance(ts_val, (int, float)):
                    started_iso = datetime.fromtimestamp(ts_val, tz=timezone.utc).isoformat()
            except Exception:
                pass

            rows.append({
                "keyword": kw.keyword,
                "volume": kw.volume,
                "volume_growth_pct": kw.volume_growth_pct,
                "started_timestamp": started_iso,
                "is_finished": kw.is_trend_finished,
                "topic_names": "; ".join(topic_names),
                "related_keywords": "; ".join(related_kws[:10]),
                "geo": "JP",
                "scraped_at": datetime.now().isoformat(),
            })
        # Save
        TRENDS_DIR.mkdir(parents=True, exist_ok=True)
        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        json_path = TRENDS_DIR / f"trending_full_JP_{ts}.json"
        with open(json_path, "w", encoding="utf-8") as f:
            json.dump(rows, f, ensure_ascii=False, indent=2)
        return jsonify({"count": len(rows), "file": json_path.name})
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route("/api/trends/files")
def api_trends_files():
    """保存済みトレンドファイル一覧。"""
    if not TRENDS_DIR.exists():
        return jsonify([])
    files = []
    for p in sorted(TRENDS_DIR.iterdir(), reverse=True):
        if p.suffix in (".csv", ".json") and "trending" in p.name:
            files.append({"name": p.name, "size": p.stat().st_size, "modified": p.stat().st_mtime})
    return jsonify(files[:20])


# ============================================================================
# メイン
# ============================================================================

if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description="X マーケットインテリジェンス ダッシュボード")
    parser.add_argument("--port", type=int, default=5000)
    parser.add_argument("--host", default="0.0.0.0")
    args = parser.parse_args()

    print("=" * 60)
    print("  X マーケットインテリジェンス ダッシュボード")
    print(f"  http://localhost:{args.port}")
    print("=" * 60)

    app.run(host=args.host, port=args.port, debug=False)
