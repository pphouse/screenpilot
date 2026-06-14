#!/usr/bin/env python3
"""
X (Twitter) 医療マーケットインテリジェンス — GENSHI AI向け
==========================================================
情報収集のみ。リプライ・いいね等のエンゲージメントは一切行わない。

3つの戦略:
  1. Pain Point Detection — 医療現場の課題・不満ツイートを検出 → リード候補リスト
  2. Influencer Mapping   — 医療IT分野の高信頼アカウントを特定・ランキング
  3. Competitor Monitoring — 医療AI競合・市場トレンドを監視

Usage:
    python3 examples/x_medical_intel.py                    # 全戦略実行
    python3 examples/x_medical_intel.py --strategy pain    # Pain Point のみ
    python3 examples/x_medical_intel.py --strategy influencer
    python3 examples/x_medical_intel.py --strategy competitor
    python3 examples/x_medical_intel.py --max-tweets 10    # クエリ毎の最大件数
    python3 examples/x_medical_intel.py --skip-trust       # Trust分析スキップ (高速)
"""

import argparse
import os
import re
import random
import time
import json
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

from x_trust_lib import TrustScorer

# ============================================================================
# 定数
# ============================================================================

AUTH_TOKEN = os.environ.get("X_AUTH_TOKEN", "")
CT0 = os.environ.get("X_CT0", "")

OUTPUT_DIR = Path("recordings/x_medical_intel")

SCROLL_PAUSE = (2.0, 5.0)
SEARCH_PAUSE = (5.0, 10.0)

# ============================================================================
# 戦略別 検索クエリ定義
# ============================================================================

# 戦略1: Pain Point Detection — 課題・不満・困りごとの検出
PAIN_POINT_QUERIES = [
    # 電子カルテの不満
    {"label": "電子カルテ 不満", "query": "電子カルテ 使いにくい OR 不満 OR 困った"},
    {"label": "電子カルテ 乗り換え", "query": "電子カルテ 乗り換え OR 移行 OR リプレイス"},
    {"label": "ベンダーロック 不満", "query": "ベンダーロック 医療 OR 電子カルテ"},
    # 医療DXの障壁
    {"label": "医療DX 課題", "query": "医療DX 課題 OR 進まない OR 障壁"},
    {"label": "医療IT 人手不足", "query": "医療 IT 人手不足 OR 担当者いない"},
    # 業務負担
    {"label": "退院サマリー 負担", "query": "退院サマリー 大変 OR 負担 OR 時間かかる"},
    {"label": "レセプト 負担", "query": "レセプト 大変 OR 返戻 OR ミス"},
    {"label": "診療報酬改定 対応", "query": "診療報酬改定 対応 大変 OR 間に合わない"},
    # AI導入の壁
    {"label": "AI導入 病院課題", "query": "AI 導入 病院 課題 OR 難しい OR 失敗"},
    {"label": "医療AI 不安", "query": "医療AI 不安 OR 心配 OR 信頼"},
]

# 戦略2: Influencer Mapping — 医療IT関連の高信頼アカウント発見
INFLUENCER_QUERIES = [
    {"label": "医療DX 発信者", "query": "医療DX"},
    {"label": "医療情報技師", "query": "医療情報技師"},
    {"label": "電子カルテ 専門家", "query": "電子カルテ 標準化 OR HL7 OR FHIR"},
    {"label": "病院CIO", "query": "病院 CIO OR 情報システム部"},
    {"label": "医療AI 有識者", "query": "医療AI 活用 OR 導入事例"},
    {"label": "厚労省 医療IT", "query": "厚労省 医療DX OR 電子カルテ標準化"},
]

# 戦略3: Competitor / Market Monitoring — 競合と市場動向
COMPETITOR_QUERIES = [
    # 競合サービス
    {"label": "メドレー", "query": "メドレー 電子カルテ OR CLINICS"},
    {"label": "エムスリー", "query": "エムスリー 医療AI OR m3"},
    {"label": "PHC (メディコム)", "query": "メディコム 電子カルテ OR PHC"},
    {"label": "富士通 医療", "query": "富士通 電子カルテ OR HOPE"},
    {"label": "NEC 医療", "query": "NEC 電子カルテ OR MegaOak"},
    # 市場トレンド
    {"label": "医療AI 市場", "query": "医療AI 市場 OR 成長 OR 売上"},
    {"label": "診療報酬 AI加算", "query": "診療報酬 AI OR 情報通信機器"},
    {"label": "医療DX 補助金", "query": "医療DX 補助金 2026 OR 2025"},
    {"label": "電子カルテ シェア", "query": "電子カルテ シェア OR 導入率"},
]

STRATEGY_MAP = {
    "pain": ("Pain Point Detection", PAIN_POINT_QUERIES),
    "influencer": ("Influencer Mapping", INFLUENCER_QUERIES),
    "competitor": ("Competitor / Market Monitoring", COMPETITOR_QUERIES),
}

# ============================================================================
# Pain Point キーワード重み付け (リード優先度判定用)
# ============================================================================

PAIN_KEYWORDS = {
    # 不満・困り (高優先度)
    "困った": 3, "困って": 3, "使いにくい": 3, "不満": 3, "つらい": 3,
    "やばい": 2, "限界": 3, "崩壊": 2, "ストレス": 2,
    # 移行・検討 (最高優先度 = 購買意向)
    "乗り換え": 5, "リプレイス": 5, "移行": 4, "検討中": 5, "導入検討": 5,
    "比較": 4, "見積": 5, "デモ": 5, "トライアル": 5, "無料体験": 4,
    # 業務負担
    "大変": 2, "負担": 2, "残業": 3, "時間かかる": 2, "間に合わない": 3,
    "手作業": 3, "手入力": 3, "二重入力": 4, "ミス": 2, "返戻": 2,
    # 人材不足
    "人手不足": 3, "担当者いない": 4, "一人で": 3, "属人化": 3,
    # コスト
    "高い": 2, "コスト": 2, "予算": 3, "費用": 2,
}


def compute_pain_score(text: str) -> int:
    """ツイートテキストからペインスコアを算出 (0〜)"""
    score = 0
    for kw, weight in PAIN_KEYWORDS.items():
        if kw in text:
            score += weight
    return score


# ============================================================================
# Selenium ユーティリティ (既存スクレイパーと同じパターン)
# ============================================================================

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


# ============================================================================
# 戦略実行
# ============================================================================

def run_strategy(
    driver: webdriver.Chrome,
    strategy_name: str,
    queries: list[dict],
    max_tweets: int,
) -> pd.DataFrame:
    """1つの戦略を実行し、全ツイートをDataFrameで返す"""
    print(f"\n{'─'*60}")
    print(f"  戦略: {strategy_name}")
    print(f"  クエリ数: {len(queries)}, 最大{max_tweets}件/クエリ")
    print(f"{'─'*60}")

    all_rows = []
    scraped_at = datetime.now(timezone.utc).isoformat()

    for i, q in enumerate(queries):
        label = q["label"]
        query = q["query"]
        print(f"  [{i+1}/{len(queries)}] {label}: \"{query}\"")

        tweets = scrape_query(driver, query, max_tweets)
        print(f"        → {len(tweets)}件")

        for t in tweets:
            all_rows.append({
                "strategy": strategy_name,
                "query_label": label,
                "search_query": query,
                "pain_score": compute_pain_score(t["tweet_text"]),
                "scraped_at": scraped_at,
                **t,
            })

        if i < len(queries) - 1:
            pause = random.uniform(*SEARCH_PAUSE)
            time.sleep(pause)

    df = pd.DataFrame(all_rows)
    if len(df) > 0:
        before = len(df)
        df = df.drop_duplicates(subset=["tweet_url"], keep="first")
        if before != len(df):
            print(f"  重複除去: {before} → {len(df)}件")
    print(f"  合計: {len(df)}件")
    return df


def run_trust_analysis(
    driver: webdriver.Chrome,
    df: pd.DataFrame,
    top_n: int = 30,
) -> pd.DataFrame:
    """収集したツイートの著者をTrust分析する。上位top_n件のみ。"""
    if df.empty:
        return pd.DataFrame()

    # ユニークハンドルを取得し、ツイート数・平均painスコアで優先度付け
    handle_stats = df.groupby("author_handle").agg(
        tweet_count=("tweet_text", "count"),
        total_likes=("likes", "sum"),
        total_views=("views", "sum"),
        avg_pain=("pain_score", "mean"),
        max_pain=("pain_score", "max"),
    ).reset_index()
    handle_stats = handle_stats.sort_values(
        ["max_pain", "tweet_count", "total_views"], ascending=False
    )

    handles = handle_stats["author_handle"].tolist()[:top_n]
    handles = [h for h in handles if h]  # 空文字除去

    if not handles:
        return pd.DataFrame()

    print(f"\n  Trust分析: {len(handles)}アカウント")

    scorer = TrustScorer(
        driver=driver,
        output_dir=OUTPUT_DIR / "trust",
        download_icons=False,
        take_screenshots=False,
        quiet=True,
    )

    results = scorer.score_many(handles, max_tweets=3, pause_range=(2.0, 4.0))

    trust_df = pd.DataFrame([{
        "handle": r.get("handle"),
        "display_name": r.get("display_name"),
        "bio": (r.get("bio") or "")[:150],
        "followers": r.get("followers_count", 0),
        "is_verified": r.get("is_verified"),
        "trust_score": r.get("total_score", 0),
        "trust_rank": r.get("rank", "?"),
        "engagement_rate": r.get("engagement_rate", 0),
    } for r in results])

    # handle_statsとマージ
    merged = trust_df.merge(handle_stats, left_on="handle", right_on="author_handle", how="left")
    merged = merged.drop(columns=["author_handle"], errors="ignore")
    merged = merged.sort_values("trust_score", ascending=False)

    return merged


# ============================================================================
# レポート生成
# ============================================================================

def generate_reports(
    tweets_df: pd.DataFrame,
    trust_df: pd.DataFrame,
    strategies_run: list[str],
    output_dir: Path,
) -> dict[str, Path]:
    """CSV/JSONレポートを生成して保存"""
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    paths = {}

    # 全ツイートCSV
    if not tweets_df.empty:
        p = output_dir / f"intel_tweets_{ts}.csv"
        tweets_df.to_csv(p, index=False, encoding="utf-8-sig")
        paths["tweets_csv"] = p
        print(f"  保存: {p} ({len(tweets_df)}件)")

    # Trust分析CSV
    if not trust_df.empty:
        p = output_dir / f"intel_trust_{ts}.csv"
        trust_df.to_csv(p, index=False, encoding="utf-8-sig")
        paths["trust_csv"] = p
        print(f"  保存: {p} ({len(trust_df)}件)")

    # Pain Point ランキング (pain_score > 0 のツイートを優先度順に)
    if not tweets_df.empty and "pain_score" in tweets_df.columns:
        pain_df = tweets_df[tweets_df["pain_score"] > 0].sort_values("pain_score", ascending=False)
        if len(pain_df) > 0:
            p = output_dir / f"intel_pain_leads_{ts}.csv"
            pain_df.to_csv(p, index=False, encoding="utf-8-sig")
            paths["pain_leads_csv"] = p
            print(f"  保存: {p} ({len(pain_df)}件, ペインスコア付きリード)")

    # サマリーJSON
    summary = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "strategies_run": strategies_run,
        "total_tweets": len(tweets_df),
        "unique_authors": tweets_df["author_handle"].nunique() if not tweets_df.empty else 0,
        "trust_analyzed": len(trust_df),
        "pain_leads": int((tweets_df["pain_score"] > 0).sum()) if not tweets_df.empty and "pain_score" in tweets_df.columns else 0,
    }

    if not tweets_df.empty:
        # 戦略別サマリー
        summary["by_strategy"] = {}
        for strat, grp in tweets_df.groupby("strategy"):
            summary["by_strategy"][strat] = {
                "tweets": len(grp),
                "authors": grp["author_handle"].nunique(),
                "avg_likes": round(grp["likes"].mean(), 1),
                "avg_views": round(grp["views"].mean(), 1),
                "top_queries": grp.groupby("query_label").size().sort_values(ascending=False).head(5).to_dict(),
            }

        # トップリード (pain_score順)
        if "pain_score" in tweets_df.columns:
            top_leads = tweets_df.nlargest(10, "pain_score")
            summary["top_pain_leads"] = [
                {
                    "author": row["author_handle"],
                    "pain_score": int(row["pain_score"]),
                    "text_preview": row["tweet_text"][:100],
                    "tweet_url": row["tweet_url"],
                    "views": int(row["views"]),
                }
                for _, row in top_leads.iterrows()
            ]

    if not trust_df.empty:
        summary["top_influencers"] = [
            {
                "handle": row["handle"],
                "trust_score": float(row["trust_score"]),
                "trust_rank": row["trust_rank"],
                "followers": int(row.get("followers", 0)),
                "bio": row.get("bio", ""),
            }
            for _, row in trust_df.nlargest(10, "trust_score").iterrows()
        ]

    p = output_dir / f"intel_summary_{ts}.json"
    with open(p, "w") as f:
        json.dump(summary, f, indent=2, ensure_ascii=False, default=str)
    paths["summary_json"] = p
    print(f"  保存: {p}")

    return paths


def print_report(tweets_df: pd.DataFrame, trust_df: pd.DataFrame):
    """コンソールにサマリーを表示"""
    print(f"\n{'='*60}")
    print("  医療マーケットインテリジェンス レポート")
    print(f"{'='*60}")

    if not tweets_df.empty:
        print(f"\n  総ツイート数: {len(tweets_df)}")
        print(f"  ユニーク著者数: {tweets_df['author_handle'].nunique()}")

        # 戦略別
        print(f"\n  --- 戦略別 ---")
        for strat, grp in tweets_df.groupby("strategy"):
            print(f"  {strat}: {len(grp)}件 / {grp['author_handle'].nunique()}著者")

        # Pain leads
        if "pain_score" in tweets_df.columns:
            pain_leads = tweets_df[tweets_df["pain_score"] > 0]
            print(f"\n  --- Pain Point リード ({len(pain_leads)}件) ---")
            if len(pain_leads) > 0:
                top5 = pain_leads.nlargest(5, "pain_score")
                for _, row in top5.iterrows():
                    ps = row["pain_score"]
                    handle = row["author_handle"]
                    preview = row["tweet_text"][:60].replace("\n", " ")
                    print(f"  [{ps:>2}点] @{handle}: {preview}...")

    if not trust_df.empty:
        print(f"\n  --- インフルエンサー TOP10 ---")
        top10 = trust_df.nlargest(10, "trust_score")
        print(f"  {'Score':>5}  {'Rank':<4} {'Handle':<22} {'Followers':>10}  Bio")
        for _, row in top10.iterrows():
            s = row["trust_score"]
            rk = row["trust_rank"]
            h = f"@{row['handle']}"
            fol = int(row.get("followers", 0))
            bio = (row.get("bio") or "")[:30]
            print(f"  {s:>5}  {rk:<4} {h:<22} {fol:>10,}  {bio}")

    print(f"\n{'='*60}")


# ============================================================================
# メイン
# ============================================================================

def main():
    parser = argparse.ArgumentParser(description="X 医療マーケットインテリジェンス (GENSHI AI)")
    parser.add_argument("--strategy", choices=["pain", "influencer", "competitor"], default=None,
                        help="実行する戦略 (省略で全戦略)")
    parser.add_argument("--max-tweets", type=int, default=15, help="クエリ毎の最大ツイート数")
    parser.add_argument("--skip-trust", action="store_true", help="Trust分析をスキップ")
    parser.add_argument("--trust-top-n", type=int, default=30, help="Trust分析する上位アカウント数")
    args = parser.parse_args()

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    (OUTPUT_DIR / "trust").mkdir(parents=True, exist_ok=True)

    # 実行する戦略を決定
    if args.strategy:
        strategies = [args.strategy]
    else:
        strategies = ["pain", "influencer", "competitor"]

    print("=" * 60)
    print("  X 医療マーケットインテリジェンス — GENSHI AI")
    print(f"  戦略: {', '.join(strategies)}")
    print(f"  最大ツイート/クエリ: {args.max_tweets}")
    print(f"  Trust分析: {'OFF' if args.skip_trust else f'ON (上位{args.trust_top_n})'}")
    print(f"  モード: 情報収集のみ (エンゲージメントなし)")
    print("=" * 60)

    driver = create_driver()
    try:
        # ログイン
        print("\n[1] ログイン...")
        if not login(driver):
            print("  [ERROR] ログイン失敗")
            return
        print("  OK")

        # 各戦略のツイート収集
        print("\n[2] ツイート収集...")
        all_dfs = []
        strategies_run = []

        for strat_key in strategies:
            strat_name, queries = STRATEGY_MAP[strat_key]
            strategies_run.append(strat_name)
            df = run_strategy(driver, strat_name, queries, args.max_tweets)
            all_dfs.append(df)

        tweets_df = pd.concat(all_dfs, ignore_index=True) if all_dfs else pd.DataFrame()

        # 全体の重複除去
        if not tweets_df.empty:
            before = len(tweets_df)
            tweets_df = tweets_df.drop_duplicates(subset=["tweet_url"], keep="first")
            if before != len(tweets_df):
                print(f"\n  全体重複除去: {before} → {len(tweets_df)}件")

        # Trust分析
        trust_df = pd.DataFrame()
        if not args.skip_trust and not tweets_df.empty:
            print("\n[3] Trust分析...")
            trust_df = run_trust_analysis(driver, tweets_df, top_n=args.trust_top_n)
        else:
            print("\n[3] Trust分析: スキップ")

        # レポート
        print("\n[4] レポート生成...")
        paths = generate_reports(tweets_df, trust_df, strategies_run, OUTPUT_DIR)

        # コンソール出力
        print_report(tweets_df, trust_df)

        print(f"\n  出力先: {OUTPUT_DIR}/")
        for name, p in paths.items():
            print(f"    {name}: {p.name}")

    finally:
        driver.quit()

    print("\n  完了!")


if __name__ == "__main__":
    main()
