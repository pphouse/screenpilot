#!/usr/bin/env python3
"""
X (Twitter) zeta 探索クローラー — 興味の赴くままに深掘りする
==============================================================
検索結果を眺めて終わりにせず、人間のリサーチャーのように「伸びている投稿」から辿っていく。

  - 表示回数 (インプレッション) が大きい zeta 投稿ほど優先して開く
  - 投稿ページでは本文・リプライ・関連ポストをまとめて拾う
  - 伸びている投稿は引用ポストのページも開き、議論の広がりを見る
  - 伸びた投稿のハッシュタグから新しい検索を派生させる
  - 伸びた投稿の投稿者は「from:ID zeta」で他の zeta 投稿も見に行く

情報収集のみ。いいね・リプライ・フォロー等は一切行わない。
収集後は x_zeta_intel と同じ集計・プロフィール取得・ビューワー生成を行う。

Usage:
    python3 examples/x_zeta_explore.py --max-pages 150 --minutes 45
    python3 examples/x_zeta_explore.py --seed-tweets recordings/x_zeta_intel/zeta_tweets_xxx.json
"""

import argparse
import heapq
import itertools
import json
import random
import re
import sys
import time
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import quote_plus

sys.path.insert(0, str(Path(__file__).resolve().parent))
import x_zeta_intel as zi  # noqa: E402
from selenium.common.exceptions import TimeoutException  # noqa: E402
from selenium.webdriver.common.by import By  # noqa: E402
from selenium.webdriver.support import expected_conditions as EC  # noqa: E402,N812
from selenium.webdriver.support.ui import WebDriverWait  # noqa: E402

# 最初に投げる検索 (話題順を中心に。広告批判も入れる)
SEED_SEARCHES = [
    ("zeta AIチャット -DIVISION", "top"),
    ("#AIチャットzeta", "top"),
    ("#zeta民", "top"),
    ("zeta アプリ -DIVISION -Global", "top"),
    ("zeta 広告 -DIVISION", "top"),
    ("zeta 広告 -DIVISION", "live"),
    ("zeta 広告 (うざい OR 不快 OR 気持ち悪い OR きもい OR 多すぎ OR 通報 OR ひどい)", "live"),
    ("zeta 広告 (長い OR スキップ OR 消したい OR 見ないと OR 途中 OR 毎回 OR 動画)", "live"),
    ("zeta 広告 (漫画 OR 流れてくる OR 出てくる OR YouTube OR TL OR 宣伝)", "live"),
    ("zeta 広告 (漫画 OR 流れてくる OR 出てくる OR YouTube OR TL OR 宣伝)", "top"),
    ("zeta (削除 OR 規制 OR アンリミテッド)", "top"),
    ("zeta (課金 OR ピース OR pass)", "top"),
    ("zeta (バグ OR 不具合)", "top"),
    ("zeta min_faves:100 -DIVISION", "top"),
    # 乗り換え・離脱 (マーケ用の重点テーマ)
    ("zeta (乗り換え OR 乗りかえ OR 移行 OR 引っ越し)", "live"),
    ("zeta (乗り換え OR 乗りかえ OR 移行 OR 引っ越し)", "top"),
    ("zeta (代わり OR 代替 OR 似てる OR 似た) アプリ", "live"),
    ("zeta (やめた OR 辞めた OR 卒業 OR 難民 OR 退会 OR アンインストール)", "live"),
    ("zeta以外 (AIチャット OR アプリ)", "live"),
    ("zeta (MooX OR Talkie OR Tipsy OR PolyBuzz OR キャラクターAI OR SynClub)", "live"),
    ("zeta (MooX OR Talkie OR Tipsy OR PolyBuzz OR キャラクターAI OR SynClub)", "top"),
]

BUZZ_VIEWS = 10_000      # この表示回数以上を「伸びている」とみなす
OPEN_POST_VIEWS = 2_000  # この表示回数以上の zeta 投稿は個別ページを開く
GENERIC_TAGS = {"#zeta", "#ai", "#aiチャット", "#aiイラスト"}


class Explorer:
    def __init__(self, driver, max_pages: int, minutes: float):
        self.d = driver
        self.max_pages = max_pages
        self.deadline = time.time() + minutes * 60
        self.heap: list = []
        self.counter = itertools.count()
        self.queued: set = set()
        self.tweets: dict[str, dict] = {}
        self.trail: list[dict] = []
        self.rejected = 0
        self.pages = 0

    # ---- frontier ----
    def push(self, kind: str, target: str, priority: float, reason: str):
        key = (kind, target)
        if key in self.queued:
            return
        self.queued.add(key)
        heapq.heappush(self.heap, (-priority, next(self.counter), kind, target, reason))

    # ---- page helpers ----
    def _load(self, url: str) -> bool:
        self.d.get(url)
        try:
            WebDriverWait(self.d, 15).until(
                EC.presence_of_element_located((By.CSS_SELECTOR, 'article[data-testid="tweet"]'))
            )
        except TimeoutException:
            return False
        time.sleep(random.uniform(1.5, 2.5))
        return True

    def _scroll_collect(self, rounds: int) -> list[dict]:
        got, seen, idle = [], set(), 0
        for _ in range(rounds):
            new = 0
            for t in zi.extract_tweets(self.d):
                if t["id"] not in seen:
                    seen.add(t["id"])
                    got.append(t)
                    new += 1
            idle = idle + 1 if new == 0 else 0
            if idle >= 3:
                break
            self.d.execute_script("window.scrollBy(0, window.innerHeight * 1.6);")
            time.sleep(random.uniform(*zi.SCROLL_PAUSE))
        return got

    def _main_views(self, tweet_id: str) -> int:
        """投稿詳細ページのメイン投稿の表示回数 (analytics リンクから)。"""
        try:
            a = self.d.find_element(By.CSS_SELECTOR, f'a[href*="/status/{tweet_id}/analytics"]')
            txt = (a.get_attribute("aria-label") or a.text or "").replace(",", "")
            m = re.search(r"([\d.]+)\s*(万|K|M)?", txt)
            if m:
                v = float(m.group(1))
                v *= {"万": 1e4, "K": 1e3, "M": 1e6}.get(m.group(2) or "", 1)
                return int(v)
        except Exception:
            pass
        return 0

    # ---- ingest ----
    def ingest(self, found: list[dict], via: str) -> int:
        new_rel = 0
        for t in found:
            if not zi.is_about_zeta(t, ""):
                self.rejected += 1
                continue
            if t["id"] in self.tweets:
                old = self.tweets[t["id"]]
                for k in ("views", "likes", "retweets", "replies"):
                    old[k] = max(old[k], t[k])
                if via not in old["queries"]:
                    old["queries"].append(via)
                continue
            self.tweets[t["id"]] = {**t, "queries": [via]}
            new_rel += 1
            self.react(self.tweets[t["id"]])
        return new_rel

    def react(self, t: dict):
        """気になる投稿を見つけたら、次に何を見るか決める。"""
        views = t.get("views") or t.get("likes", 0) * 40
        rivals = zi.competitors_in(t["text"])
        switching = "乗り換え" in zi.topics_of(t["text"])
        if (rivals or switching) and views >= 300:
            # 乗り換えの話題も重点テーマ。リプライに「自分は○○に移った」が集まりやすい
            self.push("post", t["url"], views * 3, f"乗り換えの話題{('(' + '/'.join(rivals) + ')') if rivals else ''} ({views:,} 表示)")
        for r in rivals:
            self.push("search", f"zeta {r}\tlive", views * 0.5 + 5000, f"乗り換え先候補 {r} が登場")
        if zi.ad_types(t["text"]) and views >= 500:
            # 広告への反応は重点テーマなので、小さめの投稿でもリプライ・関連ポストを見に行く
            self.push("post", t["url"], views * 3, f"広告の話題 ({views:,} 表示)")
        if views >= OPEN_POST_VIEWS or t.get("replies", 0) >= 10:
            self.push("post", t["url"], views, f"@{t['handle']} の投稿が {views:,} 表示")
        if views >= BUZZ_VIEWS:
            self.push("quotes", t["url"], views * 0.6, f"{views:,} 表示の投稿の引用を見る")
            self.push("user", t["handle"], views * 0.4, f"@{t['handle']} がバズ投稿 ({views:,} 表示)")
            for tag in set(re.findall(r"#[^\s#、。!！?？]+", t["text"])):
                if tag.lower() in GENERIC_TAGS:
                    continue
                q = tag if zi.ZETA_RE.search(tag) else f"zeta {tag}"
                self.push("search", f"{q}\ttop", views * 0.3, f"バズ投稿のタグ {tag}")

    # ---- visits ----
    def visit(self, kind: str, target: str) -> tuple[int, int]:
        if kind == "search":
            q, mode = target.split("\t")
            url = f"https://x.com/search?q={quote_plus(q)}&src=typed_query" + ("&f=live" if mode == "live" else "")
            if not self._load(url):
                return 0, 0
            found = self._scroll_collect(10)
            return len(found), self.ingest(found, f"検索: {q} ({mode})")
        if kind == "user":
            url = f"https://x.com/search?q={quote_plus(f'from:{target} zeta')}&src=typed_query&f=live"
            if not self._load(url):
                return 0, 0
            found = self._scroll_collect(8)
            return len(found), self.ingest(found, f"@{target} の zeta 投稿")
        if kind == "post":
            if not self._load(target):
                return 0, 0
            found = self._scroll_collect(6)
            m = re.search(r"/status/(\d+)", target)
            if m and m.group(1) in self.tweets:
                v = self._main_views(m.group(1))
                if v:
                    self.tweets[m.group(1)]["views"] = max(self.tweets[m.group(1)]["views"], v)
            return len(found), self.ingest(found, "投稿ページ (リプライ・関連ポスト)")
        if kind == "quotes":
            if not self._load(target.rstrip("/") + "/quotes"):
                return 0, 0
            found = self._scroll_collect(6)
            return len(found), self.ingest(found, "引用ポスト")
        return 0, 0

    def run(self):
        while self.heap and self.pages < self.max_pages and time.time() < self.deadline:
            neg, _, kind, target, reason = heapq.heappop(self.heap)
            self.pages += 1
            label = target.replace("\t", " / ")
            print(f"  [{self.pages:>3}] {kind:<6} {label[:60]}  ← {reason}", flush=True)
            try:
                found, new = self.visit(kind, target)
            except Exception as e:  # 1ページの失敗で全体を止めない
                print(f"        ERROR {type(e).__name__}: {e}"[:200], flush=True)
                found, new = 0, 0
            print(f"        {found}件表示 / zeta新規 {new}件 (累計 {len(self.tweets)})", flush=True)
            self.trail.append({
                "step": self.pages, "kind": kind, "target": label, "reason": reason,
                "seen": found, "new": new, "at": datetime.now(timezone.utc).isoformat(),
            })
            time.sleep(random.uniform(*zi.SEARCH_PAUSE))


def main():
    ap = argparse.ArgumentParser(description="zeta について X を探索的に深掘りする")
    ap.add_argument("--max-pages", type=int, default=150)
    ap.add_argument("--minutes", type=float, default=45)
    ap.add_argument("--profile-top-n", type=int, default=60)
    ap.add_argument("--seed-tweets", help="以前の収集結果 (zeta_tweets_*.json) を出発点に加える")
    ap.add_argument("--headless", action="store_true")
    ap.add_argument("--out", default="recordings/x_zeta_explore")
    args = ap.parse_args()

    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")

    d = zi.create_driver(headless=args.headless)
    try:
        print("[1] ログイン...")
        if not zi.login(d):
            print("  [ERROR] ログインできませんでした")
            return
        ex = Explorer(d, args.max_pages, args.minutes)
        for i, (q, mode) in enumerate(SEED_SEARCHES):
            ex.push("search", f"{q}\t{mode}", 1e9 - i, "起点の検索")
        for i, q in enumerate(zi.QUERIES):
            ex.push("search", f"{q['query']}\t{q['mode']}", 1e8 - i, "基本の検索")
        if args.seed_tweets:
            seed = json.loads(Path(args.seed_tweets).read_text(encoding="utf-8"))
            n = ex.ingest(seed, "前回の検索収集")
            print(f"  前回の収集から {n}件を起点に追加")

        print("[2] 探索...")
        ex.run()
        print(f"  探索終了: {ex.pages}ページ / zeta投稿 {len(ex.tweets)}件 / 無関係で除外 {ex.rejected}件")
        tweets = list(ex.tweets.values())
        (out / f"zeta_explore_tweets_{ts}.json").write_text(
            json.dumps(tweets, ensure_ascii=False, indent=1), encoding="utf-8")
        (out / f"zeta_explore_trail_{ts}.json").write_text(
            json.dumps(ex.trail, ensure_ascii=False, indent=1), encoding="utf-8")

        print("[3] 集計・プロフィール取得...")
        accounts = zi.aggregate(tweets)
        accounts.sort(key=lambda a: a["total_views"], reverse=True)
        zi.enrich_profiles(d, accounts, args.profile_top_n)
    finally:
        d.quit()

    print("[4] アイコン取得・分類...")
    zi.finalize(accounts)
    data = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "source": "screenpilot examples/x_zeta_explore.py",
        "queries": [t["target"] for t in ex.trail if t["kind"] == "search"],
        "categories": zi.CATEGORY_ORDER,
        "total_posts": len(tweets),
        "total_views": sum(t.get("views", 0) for t in tweets),
        "default_sort": "views",
        "competitor_patterns": zi.COMPETITORS,
        "trail": ex.trail,
        "accounts": accounts,
    }
    jp = out / f"zeta_explore_accounts_{ts}.json"
    jp.write_text(json.dumps(data, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"  データ: {jp}")
    zi.build_viewer(data, out / f"zeta_explore_viewer_{ts}.html")
    tc = Counter(tp for a in accounts for tp in a["topics"])
    print("  話題:", ", ".join(f"{k} {v}" for k, v in tc.most_common(8)))
    print("  完了")


if __name__ == "__main__":
    main()
