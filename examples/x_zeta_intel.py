#!/usr/bin/env python3
"""
X (Twitter) zeta 言及アカウント調査
===================================
AIキャラクターチャットアプリ「zeta」(ScatterLab) について X で話しているアカウントを集め、
アイコンをクリックすると詳細が見られる HTML ビューワーを生成する。
情報収集のみ。いいね・リプライ・フォロー等は一切行わない。

流れ:
  1. zeta 関連クエリで X を検索し、投稿を収集 (最新 + 話題)
  2. 投稿者ごとに集計し、話題タグ・トーン・区分を推定
  3. 上位アカウントのプロフィールを x_trust_lib.TrustScorer で取得 (bio・フォロワー・信頼度)
  4. アイコン画像を data URI として埋め込み、JSON と単体HTMLビューワーを出力

ログイン方法 (どちらか):
  - 環境変数 X_AUTH_TOKEN と X_CT0 に cookie を入れる
  - 何も設定しない場合はブラウザが開くので手動でログインする (最大5分待機)

Usage:
    python3 examples/x_zeta_intel.py
    python3 examples/x_zeta_intel.py --max-tweets 30 --profile-top-n 80
    python3 examples/x_zeta_intel.py --from-tweets recordings/x_zeta_intel/zeta_tweets_xxx.json
    python3 examples/x_zeta_intel.py --build-only recordings/x_zeta_intel/zeta_accounts_xxx.json
"""

import argparse
import base64
import json
import os
import random
import re
import sys
import time
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import quote_plus

os.environ.setdefault("DISPLAY", ":99")

import requests
from selenium import webdriver
from selenium.common.exceptions import (
    TimeoutException,
)
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.common.by import By
from selenium.webdriver.support import expected_conditions as EC  # noqa: N812
from selenium.webdriver.support.ui import WebDriverWait

sys.path.insert(0, str(Path(__file__).resolve().parent))
from x_medical_intel import parse_engagement  # noqa: E402
from x_trust_lib import TrustScorer  # noqa: E402

OUTPUT_DIR = Path("recordings/x_zeta_intel")
TEMPLATE = Path(__file__).resolve().parent / "templates" / "zeta_viewer.html"

SCROLL_PAUSE = (2.0, 4.0)
SEARCH_PAUSE = (4.0, 8.0)

OFFICIAL_HANDLES = {"zeta_officialjp", "zeta_nakanohito"}

# ============================================================================
# 検索クエリ
# ============================================================================

QUERIES = [
    {"label": "#AIチャットzeta", "query": "#AIチャットzeta", "mode": "live"},
    {"label": "#AIチャットzeta (話題)", "query": "#AIチャットzeta", "mode": "top"},
    {"label": "#zeta民", "query": "#zeta民", "mode": "live"},
    {"label": "zeta民と繋がりたい", "query": "zeta民と繋がりたい", "mode": "live"},
    {"label": "zeta AIチャット", "query": "zeta AIチャット -DIVISION", "mode": "live"},
    {"label": "zeta AIチャット (話題)", "query": "zeta AIチャット -DIVISION", "mode": "top"},
    {"label": "zeta アプリ", "query": "zeta アプリ -DIVISION -Global", "mode": "live"},
    {"label": "zeta 課金", "query": "zeta (課金 OR ピース OR pass)", "mode": "live"},
    {"label": "zeta プロット", "query": "zeta プロット", "mode": "live"},
    {"label": "zeta キャラ", "query": "zeta キャラ -DIVISION", "mode": "live"},
    {"label": "zeta 推し", "query": "zeta 推し -DIVISION", "mode": "live"},
    {"label": "zeta ナレーター", "query": "zeta (ナレーター OR トークプロフィール)", "mode": "live"},
    {"label": "zeta 規制・削除", "query": "zeta (削除 OR 規制 OR アンリミテッド)", "mode": "live"},
    {"label": "zeta バグ", "query": "zeta (バグ OR 不具合)", "mode": "live"},
    {"label": "zeta 広告", "query": "zeta 広告 -DIVISION", "mode": "live"},
    {"label": "zeta 広告 (話題)", "query": "zeta 広告 -DIVISION", "mode": "top"},
    {"label": "zeta 広告 批判", "query": "zeta 広告 (うざい OR 不快 OR 気持ち悪い OR きもい OR 多すぎ OR 通報 OR ひどい)", "mode": "live"},
    {"label": "zeta 乗り換え", "query": "zeta (乗り換え OR 乗りかえ OR 移行 OR 引っ越し)", "mode": "live"},
    {"label": "zeta 代わりのアプリ", "query": "zeta (代わり OR 代替 OR 似てる OR 似た) アプリ", "mode": "live"},
    {"label": "zeta 離脱", "query": "zeta (やめた OR 辞めた OR 卒業 OR 難民 OR 退会 OR アンインストール)", "mode": "live"},
    {"label": "zeta アプリ内広告", "query": "zeta 広告 (長い OR スキップ OR 消したい OR 見ないと OR 途中 OR 毎回 OR 動画)", "mode": "live"},
    {"label": "zeta 宣伝広告", "query": "zeta 広告 (漫画 OR 流れてくる OR 出てくる OR YouTube OR TL OR 宣伝)", "mode": "live"},
]

# zeta (アプリ) への言及かどうかの判定
ZETA_RE = re.compile(r"zeta|ゼタ|ｚｅｔａ", re.IGNORECASE)
NOISE_RE = re.compile(
    r"ZETA\s*DIVISION|zetadivision|zeta\s*global|ゼータ関数|ζ|Ζガンダム|Zガンダム|zeta\s*potential",
    re.IGNORECASE,
)

# ============================================================================
# 話題タグ・トーン判定 (キーワードベース)
# ============================================================================

TOPIC_KEYWORDS = {
    "乗り換え": ["乗り換え", "乗りかえ", "移行", "引っ越し", "移住", "代わり", "代替", "似てる", "似た", "他のアプリ",
              "別のアプリ", "やめた", "辞めた", "卒業", "難民", "退会", "アンインストール", "消した", "以外のAI", "おすすめのAI"],
    "課金": ["課金", "zeta pass", "zetapass", "パス", "ピース", "返金", "値上", "円"],
    "不具合": ["バグ", "不具合", "エラー", "落ちる", "起動しない", "重い", "反映されない"],
    "規制・削除": ["削除", "規制", "ペナルティ", "不適切", "アンリミ", "凍結", "BAN", "制限"],
    "版権": ["版権", "にじさんじ", "ANYCOLOR", "STPR", "著作権", "盗用", "二次創作"],
    "創作・キャラ": ["自作", "作りました", "作った", "新作", "公開", "オリキャラ", "プロット", "キャラ作"],
    "攻略・TIPS": ["コツ", "方法", "対策", "プロンプト", "指示", "TIPS", "tips", "おすすめ設定", "手順", "ロアブック"],
    "交流": ["繋がりたい", "つながりたい", "自己紹介", "お友達", "フォロー", "仲良く"],
    "イベント": ["ハロウィン", "コンテスト", "イベント", "プリ", "キャンペーン", "プレゼント"],
    "ハマり・依存": ["依存", "沼", "中毒", "溶け", "溶かし", "やめられ", "寝れ", "徹夜", "ずっと"],
    "新機能": ["アップデート", "新機能", "機能", "リリース", "登場", "プラグイン"],
}

POSITIVE = [
    "好き", "最高", "楽しい", "楽し", "おもろ", "面白", "神", "かわいい", "可愛", "尊い", "すごい",
    "凄い", "嬉しい", "ありがと", "幸せ", "癒", "ハマ", "沼", "感動", "泣け", "推せ", "優勝",
]
NEGATIVE = [
    "だる", "最悪", "無理", "ひどい", "酷い", "不満", "オワコン", "改悪", "辞め", "やめる", "退会",
    "消され", "バグ", "返金", "飽き", "イラ", "うざ", "クソ", "ゴミ", "萎え", "残念", "困", "使えない",
    "読みにく", "忘れる", "微妙",
]

CATEGORY_ORDER = ["公式・運営", "攻略・TIPS", "ニュース・論評", "創作・交流", "ユーザーの声"]


# 広告は2種類を分ける:
#   宣伝広告   = zeta 自体のプロモーション (X の TL / YouTube / 他アプリに流れる漫画広告など)
#   アプリ内広告 = zeta の中で会話の途中に流れる収益化のための広告
AD_RE = re.compile(r"広告|ＣＭ|\bCM\b|プロモ")
AD_INAPP_RE = re.compile(r"頻度|喋|話し|話す|打っ|打つ|文字|送信|会話|トーク|チャット|返信|途中|毎回|広告(?:見|を見|スキップ|消|除去|なし|無し|長|挟|入|多すぎ|が多|ばっか|ばかり)|動画広告|\d+秒|pass|パス|課金|ピース")
AD_PROMO_RE = re.compile(r"漫画|マンガ|まんが|TL|タイムライン|YouTube|ユーチューブ|TikTok|インスタ|Instagram|他のアプリ|別のアプリ|ゲーム中|アプリの広告で|広告で見|広告で知|宣伝|プロモ|PR|CM|ＣＭ|広告主|広告の(?:絵|内容|表現|キャラ|漫画)")
AD_PROMO_WEAK_RE = re.compile(r"流れてく|出てく|表示され")


# 乗り換え先として名前が挙がる他のAIチャットサービス (表記ゆれ込み)
COMPETITORS = {
    "MooX": r"moo\s*x|ムークス",
    "Talkie": r"talkie|トーキー",
    "Tipsy": r"tipsy|ティプシー",
    "Character.AI": r"character\.?\s*ai|キャラクターAI|キャラクター\.ai|c\.ai|cai\b",
    "PolyBuzz": r"polybuzz|ポリバズ",
    "SynClub": r"synclub|シンクラブ",
    "Chai": r"\bchai\b",
    "Nomi": r"\bnomi\b",
    "Replika": r"replika|レプリカ",
    "Kindroid": r"kindroid",
    "Saylo": r"saylo",
    "Linky": r"\blinky\b",
    "JanitorAI": r"janitor\s*ai",
    "SillyTavern": r"silly\s*tavern|シリタバ",
    "Cotomo": r"cotomo|コトモ",
    "ChatGPT": r"chat\s*gpt|チャットgpt|gpt-?\d",
    "Claude": r"\bclaude\b|クロード",
    "Gemini": r"\bgemini\b|ジェミニ",
    "Grok": r"\bgrok\b|グロック",
}
COMPETITOR_RES = {k: re.compile(v, re.IGNORECASE) for k, v in COMPETITORS.items()}


def competitors_in(text: str) -> list[str]:
    return [k for k, rx in COMPETITOR_RES.items() if rx.search(text or "")]


def ad_types(text: str) -> list[str]:
    if not AD_RE.search(text) and "宣伝" not in text:
        return []
    types = []
    if AD_INAPP_RE.search(text):
        types.append("アプリ内広告")
    if AD_PROMO_RE.search(text) or (not types and AD_PROMO_WEAK_RE.search(text)):
        types.append("宣伝広告")
    return types or ["広告(種類不明)"]


def topics_of(text: str) -> list[str]:
    return ad_types(text) + [t for t, kws in TOPIC_KEYWORDS.items() if any(k.lower() in text.lower() for k in kws)]


def tone_score(text: str) -> int:
    return sum(1 for w in POSITIVE if w in text) - sum(1 for w in NEGATIVE if w in text)


def classify_account(handle: str, name: str, bio: str, posts: list[dict]) -> str:
    h = handle.lower()
    if h in OFFICIAL_HANDLES:
        return "公式・運営"
    blob = " ".join([name or "", bio or ""] + [p["text"] for p in posts])
    if re.search(r"まとめ|攻略|プロンプト配布|テンプレ|TIPS|tips|コツ|対策|改善指示|設定方法", blob):
        return "攻略・TIPS"
    if re.search(r"ニュース|速報|報道|発表|記事|ANYCOLOR|削除要請|運営会社|Scatter\s*Lab", blob, re.IGNORECASE):
        return "ニュース・論評"
    if re.search(r"繋がりたい|つながりたい|自己紹介|自作|作りました|新作|オリキャラ|公開しました|クリエイター|遊んで", blob):
        return "創作・交流"
    return "ユーザーの声"


def snowflake_to_iso(tweet_id: str) -> str | None:
    try:
        ms = (int(tweet_id) >> 22) + 1288834974657
        return datetime.fromtimestamp(ms / 1000, tz=timezone.utc).isoformat()
    except (TypeError, ValueError):
        return None


# ============================================================================
# ブラウザ / ログイン
# ============================================================================

def create_driver(headless: bool = False) -> webdriver.Chrome:
    opts = Options()
    for a in [
        "--no-sandbox", "--disable-dev-shm-usage", "--disable-gpu",
        "--window-size=1400,1000", "--lang=ja-JP",
        "--disable-blink-features=AutomationControlled",
    ]:
        opts.add_argument(a)
    if headless:
        opts.add_argument("--headless=new")
    opts.add_experimental_option("excludeSwitches", ["enable-automation"])
    opts.add_experimental_option("useAutomationExtension", False)
    d = webdriver.Chrome(options=opts)
    d.execute_cdp_cmd("Page.addScriptToEvaluateOnNewDocument", {
        "source": "Object.defineProperty(navigator, 'webdriver', {get: () => undefined})"
    })
    return d


def _home_loaded(d: webdriver.Chrome, timeout: int = 10) -> bool:
    try:
        d.get("https://x.com/home")
        WebDriverWait(d, timeout).until(
            EC.presence_of_element_located((By.CSS_SELECTOR, '[data-testid="primaryColumn"]'))
        )
        return "/login" not in d.current_url and "/i/flow" not in d.current_url
    except TimeoutException:
        return False


def login(d: webdriver.Chrome, manual_wait: int = 300) -> bool:
    """環境変数の cookie でログイン。無ければ手動ログインを待つ。"""
    token, ct0 = os.environ.get("X_AUTH_TOKEN"), os.environ.get("X_CT0")
    if token and ct0:
        d.get("https://x.com")
        time.sleep(2)
        for name, value in [("auth_token", token), ("ct0", ct0)]:
            d.add_cookie({"name": name, "value": value, "domain": ".x.com", "path": "/", "secure": True})
        return _home_loaded(d)

    print("  X_AUTH_TOKEN / X_CT0 が未設定です。開いたブラウザで X にログインしてください。")
    d.get("https://x.com/i/flow/login")
    deadline = time.time() + manual_wait
    while time.time() < deadline:
        time.sleep(5)
        if d.get_cookie("auth_token"):
            return _home_loaded(d)
    return False


# ============================================================================
# 投稿収集
# ============================================================================

SHOW_ORIGINAL_JS = r"""
var n = 0;
document.querySelectorAll('article[data-testid="tweet"] button, article[data-testid="tweet"] [role="button"], article[data-testid="tweet"] span').forEach(function (el) {
  var t = (el.innerText || '').trim();
  if ((t === 'Show original' || t === '原文を表示') && !el.dataset.spOrig) {
    el.dataset.spOrig = '1';
    (el.closest('button,[role="button"]') || el).click();
    n++;
  }
});
return n;
"""

EXTRACT_JS = r"""
return Array.from(document.querySelectorAll('article[data-testid="tweet"]')).map(function (art) {
  var q = function (s) { return art.querySelector(s); };
  var textEl = q('div[data-testid="tweetText"]');
  var links = art.querySelectorAll('div[data-testid="User-Name"] a');
  var handle = '', name = links.length ? links[0].innerText.trim() : '';
  for (var i = 0; i < links.length; i++) {
    var h = links[i].getAttribute('href') || '';
    if (/^\/[^/]+$/.test(h)) { handle = h.slice(1); break; }
  }
  var t = q('time[datetime]');
  var a = t && t.closest('a');
  var av = q('div[data-testid="Tweet-User-Avatar"] img');
  var g = q('div[role="group"]');
  var labels = '';
  if (g) {
    labels = g.getAttribute('aria-label') || Array.from(g.querySelectorAll('button, a'))
      .map(function (e) { return e.getAttribute('aria-label') || ''; }).join(', ');
  }
  return {
    text: textEl ? textEl.innerText.trim() : '', handle: handle, name: name,
    ts: t ? t.getAttribute('datetime') : '', href: a ? a.href : '',
    avatar: av ? av.src : '', media: !!q('div[data-testid="tweetPhoto"], video'), labels: labels
  };
});
"""


def extract_tweets(d: webdriver.Chrome) -> list[dict]:
    """表示中の投稿を抽出 (アイコンURL付き)。1回の JS 実行でまとめて読む。"""
    out = []
    try:
        # X が自動翻訳した投稿は原文に戻してから読む (アカウントの言語設定は変えない)
        if d.execute_script(SHOW_ORIGINAL_JS):
            time.sleep(1.2)
        raw = d.execute_script(EXTRACT_JS) or []
    except Exception:
        return out
    for r in raw:
        m = re.search(r"/status/(\d+)", r.get("href") or "")
        if not r.get("handle") or not m:
            continue
        avatar = r.get("avatar") or ""
        if "profile_images" not in avatar and "default_profile" not in avatar:
            avatar = ""
        out.append({
            "id": m.group(1), "url": r["href"].split("?")[0], "handle": r["handle"], "name": r["name"],
            "text": r["text"], "date": r["ts"] or snowflake_to_iso(m.group(1)), "avatar": avatar,
            "has_media": bool(r["media"]), **parse_engagement(r.get("labels") or ""),
        })
    return out


def search(d: webdriver.Chrome, query: str, mode: str, max_tweets: int) -> list[dict]:
    url = f"https://x.com/search?q={quote_plus(query)}&src=typed_query" + ("&f=live" if mode == "live" else "")
    d.get(url)
    try:
        WebDriverWait(d, 15).until(
            EC.presence_of_element_located((By.CSS_SELECTOR, 'article[data-testid="tweet"]'))
        )
    except TimeoutException:
        return []
    time.sleep(random.uniform(1.5, 3.0))

    got, seen, idle = [], set(), 0
    while len(got) < max_tweets and idle < 4:
        new = 0
        for t in extract_tweets(d):
            if t["id"] not in seen:
                seen.add(t["id"])
                got.append(t)
                new += 1
        idle = idle + 1 if new == 0 else 0
        d.execute_script("window.scrollBy(0, window.innerHeight * 1.6);")
        time.sleep(random.uniform(*SCROLL_PAUSE))
    return got[:max_tweets]


def is_about_zeta(t: dict, query_label: str) -> bool:
    text = f"{t['text']} {t['name']} {t['handle']}"
    if NOISE_RE.search(text):
        return False
    return bool(ZETA_RE.search(text)) or query_label.startswith("#")


def collect(d: webdriver.Chrome, max_tweets: int) -> list[dict]:
    tweets: dict[str, dict] = {}
    for i, q in enumerate(QUERIES):
        print(f"  [{i+1}/{len(QUERIES)}] {q['label']} ({q['mode']})", end="", flush=True)
        found = search(d, q["query"], q["mode"], max_tweets)
        kept = 0
        for t in found:
            if not is_about_zeta(t, q["label"]):
                continue
            if t["id"] in tweets:
                tweets[t["id"]]["queries"].append(q["label"])
                continue
            tweets[t["id"]] = {**t, "queries": [q["label"]]}
            kept += 1
        print(f" → {len(found)}件取得 / 新規{kept}件")
        if i < len(QUERIES) - 1:
            time.sleep(random.uniform(*SEARCH_PAUSE))
    return list(tweets.values())


# ============================================================================
# 集計
# ============================================================================

def big_avatar(url: str) -> str:
    return re.sub(r"_(normal|bigger|mini|x96|200x200|400x400)(\.\w+)$", r"_200x200\2", url or "")


def fetch_data_uri(url: str) -> str | None:
    if not url:
        return None
    try:
        r = requests.get(url, timeout=15)
        if r.status_code == 200 and r.content:
            mime = r.headers.get("content-type", "image/jpeg").split(";")[0]
            return f"data:{mime};base64,{base64.b64encode(r.content).decode()}"
    except requests.RequestException:
        pass
    return None


def aggregate(tweets: list[dict]) -> list[dict]:
    by = defaultdict(list)
    for t in tweets:
        by[t["handle"]].append(t)

    accounts = []
    for handle, posts in by.items():
        posts.sort(key=lambda p: p.get("date") or "", reverse=True)
        topic_counter = Counter(tp for p in posts for tp in topics_of(p["text"]))
        tone = sum(tone_score(p["text"]) for p in posts)
        accounts.append({
            "handle": handle,
            "name": posts[0]["name"],
            "avatar_url": big_avatar(next((p["avatar"] for p in posts if p.get("avatar")), "")),
            "post_count": len(posts),
            "total_likes": sum(p["likes"] for p in posts),
            "total_views": sum(p["views"] for p in posts),
            "total_retweets": sum(p["retweets"] for p in posts),
            "last_post": posts[0].get("date"),
            "topics": [t for t, _ in topic_counter.most_common()],
            "competitors": sorted({c for p in posts for c in competitors_in(p["text"])}),
            "tone_score": tone,
            "tone": "ポジティブ" if tone > 0 else "ネガティブ" if tone < 0 else "中立",
            "posts": [
                {k: p[k] for k in ("id", "url", "text", "date", "likes", "retweets", "replies", "views", "has_media", "queries")}
                for p in posts
            ],
        })
    accounts.sort(key=lambda a: (a["handle"].lower() in OFFICIAL_HANDLES, a["post_count"], a["total_views"]), reverse=True)
    return accounts


def enrich_profiles(d: webdriver.Chrome, accounts: list[dict], top_n: int):
    """上位アカウントのプロフィールを TrustScorer で取得してマージ。"""
    targets = accounts[:top_n]
    if not targets:
        return
    print(f"\n  プロフィール取得: {len(targets)}アカウント")
    scorer = TrustScorer(driver=d, output_dir=OUTPUT_DIR / "trust",
                         download_icons=False, take_screenshots=False, quiet=True)
    scorer._logged_in = True  # ログイン済みの driver を使う
    for i, a in enumerate(targets):
        try:
            r = scorer.score(a["handle"], max_tweets=5)
        except Exception as e:  # 1件の失敗で全体を止めない
            print(f"  [{i+1}/{len(targets)}] @{a['handle']} ERROR {e}")
            continue
        if r.get("error"):
            print(f"  [{i+1}/{len(targets)}] @{a['handle']} ERROR {r['error']}")
            continue
        a["profile"] = {
            "display_name": r.get("display_name"),
            "bio": r.get("bio"),
            "location": r.get("location"),
            "website": r.get("website"),
            "joined": r.get("join_date_raw"),
            "followers": r.get("followers_count", 0),
            "following": r.get("following_count", 0),
            "verified": bool(r.get("is_verified")),
            "avg_likes": r.get("avg_likes"),
            "avg_views": r.get("avg_views"),
            "engagement_rate": r.get("engagement_rate"),
            "trust_score": r.get("total_score"),
            "trust_rank": r.get("rank"),
            "trust_breakdown": r.get("breakdown"),
        }
        if r.get("avatar_url"):
            a["avatar_url"] = big_avatar(r["avatar_url"])
        print(f"  [{i+1}/{len(targets)}] @{a['handle']} followers={a['profile']['followers']:,} "
              f"trust={a['profile']['trust_score']} ({a['profile']['trust_rank']})")
        time.sleep(random.uniform(2.0, 4.0))


def finalize(accounts: list[dict]):
    for a in accounts:
        bio = (a.get("profile") or {}).get("bio") or ""
        a["category"] = classify_account(a["handle"], a["name"], bio, a["posts"])
        a["avatar"] = fetch_data_uri(a.get("avatar_url"))


# ============================================================================
# 出力
# ============================================================================

def build_viewer(data: dict, out_path: Path, standalone: bool = True):
    """テンプレートにデータを埋め込んだ単体HTMLを書き出す。

    standalone=True ならブラウザで直接開けるよう doctype / head を付ける。
    """
    if not TEMPLATE.exists():
        print(f"  [WARN] テンプレートがありません: {TEMPLATE}")
        return
    html = TEMPLATE.read_text(encoding="utf-8")
    if standalone:
        html = (
            '<!doctype html>\n<html lang="ja">\n<head>\n<meta charset="utf-8">\n'
            '<meta name="viewport" content="width=device-width, initial-scale=1, viewport-fit=cover">\n'
            "</head>\n<body>\n" + html + "\n</body>\n</html>\n"
        )
    payload = json.dumps(data, ensure_ascii=False).replace("</", "<\\/")
    html, n = re.subn(
        r'(<script id="zeta-data" type="application/json">)(.*?)(</script>)',
        lambda m: m.group(1) + payload + m.group(3), html, count=1, flags=re.S,
    )
    if n != 1:
        print("  [WARN] テンプレートに zeta-data ブロックがありません")
        return
    out_path.write_text(html, encoding="utf-8")
    print(f"  ビューワー: {out_path}")


def main():
    ap = argparse.ArgumentParser(description="X で zeta について話しているアカウントを調査")
    ap.add_argument("--max-tweets", type=int, default=30, help="クエリ毎の最大取得件数")
    ap.add_argument("--profile-top-n", type=int, default=60, help="プロフィールを取得する上位アカウント数")
    ap.add_argument("--headless", action="store_true", help="ヘッドレスで実行 (cookieログイン時のみ推奨)")
    ap.add_argument("--from-tweets", help="収集済みの投稿JSONから再開 (検索をスキップ)")
    ap.add_argument("--build-only", help="アカウントJSONからビューワーHTMLだけ生成")
    ap.add_argument("--out", default=str(OUTPUT_DIR), help="出力先ディレクトリ")
    args = ap.parse_args()

    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")

    if args.build_only:
        data = json.loads(Path(args.build_only).read_text(encoding="utf-8"))
        build_viewer(data, out / f"zeta_viewer_{ts}.html")
        return

    print("=" * 60)
    print("  X zeta 言及アカウント調査 (情報収集のみ)")
    print("=" * 60)

    d = create_driver(headless=args.headless)
    try:
        print("\n[1] ログイン...")
        if not login(d):
            print("  [ERROR] ログインできませんでした (cookie の期限切れか、手動ログインのタイムアウト)")
            return
        print("  OK")

        if args.from_tweets:
            tweets = json.loads(Path(args.from_tweets).read_text(encoding="utf-8"))
            print(f"\n[2] 投稿収集: スキップ ({len(tweets)}件を読込)")
        else:
            print("\n[2] 投稿収集...")
            tweets = collect(d, args.max_tweets)
            p = out / f"zeta_tweets_{ts}.json"
            p.write_text(json.dumps(tweets, ensure_ascii=False, indent=1), encoding="utf-8")
            print(f"  {len(tweets)}件 → {p}")

        print("\n[3] 集計...")
        accounts = aggregate(tweets)
        print(f"  {len(accounts)}アカウント")

        print("\n[4] プロフィール取得...")
        enrich_profiles(d, accounts, args.profile_top_n)
    finally:
        d.quit()

    print("\n[5] アイコン取得・分類...")
    finalize(accounts)

    data = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "source": "screenpilot examples/x_zeta_intel.py",
        "queries": [f"{q['query']} ({q['mode']})" for q in QUERIES],
        "categories": CATEGORY_ORDER,
        "total_posts": len(tweets),
        "accounts": accounts,
    }
    jp = out / f"zeta_accounts_{ts}.json"
    jp.write_text(json.dumps(data, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"  データ: {jp}")
    build_viewer(data, out / f"zeta_viewer_{ts}.html")

    cats = Counter(a["category"] for a in accounts)
    print("\n  区分別:", ", ".join(f"{c} {cats.get(c, 0)}" for c in CATEGORY_ORDER))
    print("  完了")


if __name__ == "__main__":
    main()
