#!/usr/bin/env python3
"""
x_trust_lib — X (Twitter) アカウント信頼度スコアリング ライブラリ
==================================================================
他のスクリプトから import して使う再利用可能モジュール。

API:
    from x_trust_lib import TrustScorer

    scorer = TrustScorer()                    # driver自動作成+ログイン
    scorer = TrustScorer(driver=my_driver)     # 既存driver再利用

    result = scorer.score("@AnthropicAI")     # 1アカウント分析
    results = scorer.score_many(["@A", "@B"]) # 複数分析 → list[dict]
    df = scorer.score_from_csv("tweets.csv", handle_col="author_handle")

    scorer.close()                            # driver終了

Result dict:
    {
      "handle", "display_name", "bio", "location", "website",
      "join_date_raw", "join_date",
      "following_count", "followers_count", "is_verified",
      "avatar_url", "icon_path", "screenshot_path",
      "tweet_sample", "avg_likes", "avg_retweets", "avg_views", "engagement_rate",
      "total_score", "rank", "breakdown", "details",
      "analyzed_at", "error",
    }
"""

import os
import re
import json
import random
import time
import requests
from datetime import datetime, timezone
from pathlib import Path

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

# ============================================================================
# 定数
# ============================================================================

AUTH_TOKEN = "9d093cbffdc2ffcf8652c9b7bd34f4862b0351fb"
CT0 = (
    "9146228da1e4fb4e13a55406c15a8e3ef3c69ec9b1f7b301e24a65e5e0db654a"
    "b5e4c2c073e3f8a3e50ec61f3e87aa9b43a8fdfef57f9ad0fb8fd3c5a2f3e8c0"
    "fa60ad618c41553c3a775ff02b4af08b80d5e0fdd28b2d29d7a6ba02f8e4db3e2"
    "8cc9c7e"
)

DEFAULT_OUTPUT_DIR = Path("recordings/x_account_trust")


# ============================================================================
# ユーティリティ
# ============================================================================

def parse_count(text: str) -> int:
    """'1.2K' → 1200, '3.5M' → 3500000, '1,234' → 1234"""
    if not text:
        return 0
    text = text.strip().replace(",", "")
    for suffix, mult in {"K": 1e3, "M": 1e6, "B": 1e9, "万": 1e4, "億": 1e8}.items():
        if suffix in text:
            try:
                return int(float(text.replace(suffix, "").strip()) * mult)
            except ValueError:
                return 0
    try:
        return int(float(text))
    except ValueError:
        return 0


def parse_join_date(text: str) -> datetime | None:
    """'Joined March 2020' or '2020年3月からXを利用' → datetime"""
    m = re.search(r"Joined\s+(\w+)\s+(\d{4})", text)
    if m:
        try:
            return datetime.strptime(f"{m.group(1)} {m.group(2)}", "%B %Y").replace(tzinfo=timezone.utc)
        except ValueError:
            pass
    m = re.search(r"(\d{4})年(\d{1,2})月", text)
    if m:
        return datetime(int(m.group(1)), int(m.group(2)), 1, tzinfo=timezone.utc)
    return None


def _result_to_row(r: dict) -> dict:
    """result dict → flat CSV row"""
    return {
        "handle": r.get("handle"),
        "display_name": r.get("display_name"),
        "bio": (r.get("bio") or "")[:200],
        "location": r.get("location"),
        "website": r.get("website"),
        "join_date": r.get("join_date_raw"),
        "following": r.get("following_count"),
        "followers": r.get("followers_count"),
        "ff_ratio": r.get("details", {}).get("ff_ratio"),
        "is_verified": r.get("is_verified"),
        "tweet_sample": r.get("tweet_sample"),
        "avg_likes": r.get("avg_likes"),
        "avg_retweets": r.get("avg_retweets"),
        "avg_views": r.get("avg_views"),
        "engagement_rate": r.get("engagement_rate"),
        "trust_score": r.get("total_score"),
        "trust_rank": r.get("rank"),
        "avatar_url": r.get("avatar_url"),
        "icon_path": r.get("icon_path"),
        "screenshot_path": r.get("screenshot_path"),
        "error": r.get("error"),
        "analyzed_at": r.get("analyzed_at"),
    }


# ============================================================================
# TrustScorer クラス
# ============================================================================

class TrustScorer:
    """Xアカウントの信頼度を定量化するスコアラー。

    Args:
        driver: 既存の Selenium WebDriver (省略時は自動作成)
        output_dir: アイコン・スクショの保存先
        download_icons: アイコン画像をダウンロードするか
        take_screenshots: プロフィールスクショを取るか
        quiet: ログ出力を抑制するか
    """

    def __init__(
        self,
        driver: webdriver.Chrome | None = None,
        output_dir: Path | str = DEFAULT_OUTPUT_DIR,
        download_icons: bool = True,
        take_screenshots: bool = True,
        quiet: bool = False,
    ):
        self.output_dir = Path(output_dir)
        self.output_dir.mkdir(parents=True, exist_ok=True)
        self.download_icons = download_icons
        self.take_screenshots = take_screenshots
        self.quiet = quiet
        self._owns_driver = driver is None
        self.driver = driver or self._create_driver()
        self._logged_in = False

    # --- driver管理 ---

    @staticmethod
    def _create_driver() -> webdriver.Chrome:
        opts = Options()
        opts.add_argument("--no-sandbox")
        opts.add_argument("--disable-dev-shm-usage")
        opts.add_argument("--disable-gpu")
        opts.add_argument("--window-size=1920,1080")
        opts.add_argument("--lang=ja-JP")
        opts.add_argument("--disable-blink-features=AutomationControlled")
        opts.add_experimental_option("excludeSwitches", ["enable-automation"])
        opts.add_experimental_option("useAutomationExtension", False)
        d = webdriver.Chrome(options=opts)
        d.execute_cdp_cmd("Page.addScriptToEvaluateOnNewDocument", {
            "source": "Object.defineProperty(navigator, 'webdriver', {get: () => undefined})"
        })
        return d

    def _ensure_login(self):
        if self._logged_in:
            return
        d = self.driver
        try:
            d.get("https://x.com/home")
            time.sleep(3)
            WebDriverWait(d, 10).until(
                EC.presence_of_element_located((By.CSS_SELECTOR, '[data-testid="primaryColumn"]'))
            )
            self._logged_in = True
            return
        except TimeoutException:
            pass
        # cookie注入
        d.get("https://x.com")
        time.sleep(2)
        for name, value in [("auth_token", AUTH_TOKEN), ("ct0", CT0)]:
            try:
                d.add_cookie({"name": name, "value": value, "domain": ".x.com", "path": "/", "secure": True})
            except Exception:
                pass
        d.refresh()
        time.sleep(3)
        try:
            d.get("https://x.com/home")
            time.sleep(3)
            WebDriverWait(d, 10).until(
                EC.presence_of_element_located((By.CSS_SELECTOR, '[data-testid="primaryColumn"]'))
            )
            self._logged_in = True
        except TimeoutException:
            raise RuntimeError("Xログイン失敗: Cookie有効期限を確認してください")

    def close(self):
        """driverを終了 (自動作成時のみ)"""
        if self._owns_driver and self.driver:
            self.driver.quit()
            self.driver = None

    def __enter__(self):
        return self

    def __exit__(self, *args):
        self.close()

    # --- ログ ---

    def _log(self, msg: str):
        if not self.quiet:
            print(msg)

    # --- プロフィール抽出 ---

    def _extract_profile(self, handle: str) -> dict:
        d = self.driver
        handle = handle.lstrip("@")
        url = f"https://x.com/{handle}"
        self._log(f"  [{handle}] アクセス中...")
        d.get(url)
        time.sleep(3)

        try:
            WebDriverWait(d, 10).until(
                EC.presence_of_element_located((By.CSS_SELECTOR, '[data-testid="primaryColumn"]'))
            )
        except TimeoutException:
            return {"handle": handle, "url": url, "error": "page_timeout"}

        p = {"handle": handle, "url": url, "error": None}

        # アイコン画像
        try:
            av = d.find_element(By.CSS_SELECTOR, 'img[alt*="Opens profile photo"]')
            src = av.get_attribute("src") or ""
            p["avatar_url"] = re.sub(r"_\w+(\.\w+)$", r"_400x400\1", src)
        except NoSuchElementException:
            p["avatar_url"] = None
            try:
                for img in d.find_elements(By.CSS_SELECTOR, "img"):
                    src = img.get_attribute("src") or ""
                    if "profile_images" in src and ("_200x200" in src or "_normal" in src):
                        p["avatar_url"] = re.sub(r"_\w+(\.\w+)$", r"_400x400\1", src)
                        break
            except Exception:
                pass

        # 表示名
        try:
            h2 = d.find_element(By.CSS_SELECTOR, '[data-testid="primaryColumn"] h2')
            p["display_name"] = h2.text.strip().split("\n")[0]
        except NoSuchElementException:
            p["display_name"] = None

        # Bio
        try:
            p["bio"] = d.find_element(By.CSS_SELECTOR, 'div[data-testid="UserDescription"]').text.strip()
        except NoSuchElementException:
            p["bio"] = None

        # 場所
        try:
            p["location"] = d.find_element(By.CSS_SELECTOR, 'span[data-testid="UserLocation"]').text.strip()
        except NoSuchElementException:
            p["location"] = None

        # ウェブサイト
        try:
            p["website"] = d.find_element(By.CSS_SELECTOR, 'a[data-testid="UserUrl"]').get_attribute("href")
        except NoSuchElementException:
            p["website"] = None

        # 加入日
        p["join_date_raw"], p["join_date"] = None, None
        try:
            for span in d.find_elements(By.CSS_SELECTOR, '[data-testid="primaryColumn"] span'):
                txt = span.text.strip()
                if txt.startswith("Joined ") or ("年" in txt and "月" in txt and "から" in txt):
                    p["join_date_raw"] = txt
                    p["join_date"] = parse_join_date(txt)
                    break
        except Exception:
            pass

        # フォロー / フォロワー
        try:
            fl = d.find_element(By.CSS_SELECTOR, f'a[href="/{handle}/following"]')
            p["following_count"] = parse_count(fl.text.split()[0] if fl.text else "0")
        except NoSuchElementException:
            p["following_count"] = 0

        try:
            fl = d.find_element(By.CSS_SELECTOR, f'a[href="/{handle}/verified_followers"]')
            p["followers_count"] = parse_count(fl.text.split()[0] if fl.text else "0")
        except NoSuchElementException:
            try:
                fl = d.find_element(By.CSS_SELECTOR, f'a[href="/{handle}/followers"]')
                p["followers_count"] = parse_count(fl.text.split()[0] if fl.text else "0")
            except NoSuchElementException:
                p["followers_count"] = 0

        # 認証バッジ
        p["is_verified"] = False
        for label in ["Verified account", "認証済みアカウント"]:
            try:
                d.find_element(By.CSS_SELECTOR, f'[data-testid="primaryColumn"] svg[aria-label="{label}"]')
                p["is_verified"] = True
                break
            except NoSuchElementException:
                pass

        # スクリーンショット
        if self.take_screenshots:
            ss = self.output_dir / f"{handle}_profile.png"
            try:
                d.save_screenshot(str(ss))
                p["screenshot_path"] = str(ss)
            except Exception:
                p["screenshot_path"] = None
        else:
            p["screenshot_path"] = None

        # アイコンダウンロード
        if self.download_icons and p.get("avatar_url"):
            icon = self.output_dir / f"{handle}_icon.jpg"
            try:
                resp = requests.get(p["avatar_url"], timeout=10)
                if resp.status_code == 200:
                    icon.write_bytes(resp.content)
                    p["icon_path"] = str(icon)
                else:
                    p["icon_path"] = None
            except Exception:
                p["icon_path"] = None
        else:
            p["icon_path"] = None

        return p

    # --- エンゲージメント ---

    def _extract_engagement(self, max_tweets: int = 5) -> dict:
        d = self.driver
        time.sleep(1)
        d.execute_script("window.scrollTo(0, 600);")
        time.sleep(2)

        totals = {"likes": 0, "retweets": 0, "replies": 0, "views": 0}
        count = 0

        try:
            articles = d.find_elements(By.CSS_SELECTOR, 'article[data-testid="tweet"]')
        except Exception:
            articles = []

        for art in articles[:max_tweets]:
            try:
                group = art.find_element(By.CSS_SELECTOR, 'div[role="group"]')
                # group の aria-label に全メトリクスが入っている
                group_label = group.get_attribute("aria-label") or ""
                source = group_label if group_label else ""
                if not source:
                    # フォールバック: button + a の aria-label を結合
                    labels = []
                    for el in group.find_elements(By.CSS_SELECTOR, "button, a"):
                        labels.append(el.get_attribute("aria-label") or "")
                    source = ", ".join(labels)
                for pat, key in [
                    (r"(\d[\d,]*)\s*(?:repl|件の返信)", "replies"),
                    (r"(\d[\d,]*)\s*(?:repost|件のリポスト)", "retweets"),
                    (r"(\d[\d,]*)\s*(?:like|件のいいね)", "likes"),
                    (r"(\d[\d,]*)\s*(?:view|件の表示)", "views"),
                ]:
                    m = re.search(pat, source, re.IGNORECASE)
                    if m:
                        totals[key] += int(m.group(1).replace(",", ""))
                count += 1
            except (NoSuchElementException, StaleElementReferenceException):
                continue

        if count == 0:
            return {"tweet_sample": 0, "avg_likes": 0, "avg_retweets": 0, "avg_views": 0, "engagement_rate": 0}

        avg_l = totals["likes"] / count
        avg_rt = totals["retweets"] / count
        avg_v = totals["views"] / count

        if totals["views"] > 0:
            er = (totals["likes"] + totals["retweets"] + totals["replies"]) / totals["views"] * 100
        elif totals["likes"] > 0:
            er = min(5.0, avg_l / max(avg_l * 50, 1) * 100)
        else:
            er = 0

        return {
            "tweet_sample": count,
            "avg_likes": round(avg_l, 1),
            "avg_retweets": round(avg_rt, 1),
            "avg_views": round(avg_v, 1),
            "engagement_rate": round(er, 3),
        }

    # --- スコア算出 ---

    @staticmethod
    def compute_trust_score(profile: dict, engagement: dict) -> dict:
        """信頼度スコア (0-100) を算出。staticmethod なのでオフラインでも使える。"""
        scores, details = {}, {}

        # 1. アカウント年齢 (max 15)
        if profile.get("join_date"):
            years = (datetime.now(timezone.utc) - profile["join_date"]).days / 365.25
            scores["account_age"] = round(min(15, years * 3), 1)
            details["account_age_years"] = round(years, 1)
        else:
            scores["account_age"] = 0
            details["account_age_years"] = None

        # 2. フォロワー数 (max 20)
        fol = profile.get("followers_count", 0)
        scores["followers"] = (
            20 if fol >= 1_000_000 else
            17 if fol >= 100_000 else
            14 if fol >= 10_000 else
            10 if fol >= 1_000 else
            6 if fol >= 100 else
            3 if fol >= 10 else 1
        )
        details["followers_count"] = fol

        # 3. FF比率 (max 15)
        fing = profile.get("following_count", 0)
        if fol > 0 and fing > 0:
            ratio = fol / fing
            scores["ff_ratio"] = (
                15 if ratio >= 10 else
                12 if ratio >= 5 else
                10 if ratio >= 2 else
                7 if ratio >= 1 else
                4 if ratio >= 0.5 else 2
            )
        elif fol > 0:
            scores["ff_ratio"] = 12
        else:
            scores["ff_ratio"] = 1
        details["ff_ratio"] = round(fol / max(fing, 1), 2)

        # 4. 認証バッジ (max 10)
        scores["verified"] = 10 if profile.get("is_verified") else 0

        # 5. bio充実度 (max 10)
        bs = min(5, len(profile.get("bio") or "") / 20)
        if profile.get("location"):
            bs += 2
        if profile.get("website"):
            bs += 3
        scores["bio_completeness"] = round(min(10, bs), 1)

        # 6. エンゲージメント率 (max 15)
        er = engagement.get("engagement_rate", 0)
        scores["engagement"] = (
            15 if er >= 5 else
            12 if er >= 2 else
            9 if er >= 1 else
            6 if er >= 0.5 else
            3 if er > 0 else 0
        )
        details["engagement_rate_pct"] = er

        # 7. アイコン (max 5)
        ic = 0
        if profile.get("avatar_url") and "default_profile" not in (profile["avatar_url"] or ""):
            ic += 3
        if profile.get("screenshot_path"):
            ic += 2
        scores["icon"] = min(5, ic)

        # 8. 投稿活動 (max 10)
        scores["activity"] = min(10, engagement.get("tweet_sample", 0) * 2)

        total = min(100, round(sum(scores.values()), 1))
        rank = (
            "A" if total >= 80 else
            "B" if total >= 60 else
            "C" if total >= 40 else
            "D" if total >= 20 else "E"
        )

        return {"total_score": total, "rank": rank, "breakdown": scores, "details": details}

    # === 公開API ===

    def score(self, handle: str, max_tweets: int = 5) -> dict:
        """1アカウントを分析してスコアを返す。"""
        self._ensure_login()
        handle = handle.lstrip("@")

        profile = self._extract_profile(handle)
        if profile.get("error"):
            self._log(f"  [{handle}] ERROR: {profile['error']}")
            return {**profile, "total_score": 0, "rank": "E",
                    "breakdown": {}, "details": {}, "analyzed_at": datetime.now(timezone.utc).isoformat()}

        eng = self._extract_engagement(max_tweets)
        trust = self.compute_trust_score(profile, eng)

        result = {**profile, **eng, **trust, "analyzed_at": datetime.now(timezone.utc).isoformat()}
        self._log(f"  [{handle}] {trust['total_score']}/100 (rank {trust['rank']}) "
                  f"| followers={profile.get('followers_count',0):,} verified={profile.get('is_verified')}")
        return result

    def score_many(
        self,
        handles: list[str],
        max_tweets: int = 5,
        pause_range: tuple[float, float] = (3.0, 6.0),
    ) -> list[dict]:
        """複数アカウントを順番に分析。"""
        results = []
        total = len(handles)
        for i, h in enumerate(handles):
            self._log(f"\n  [{i+1}/{total}] @{h.lstrip('@')}")
            results.append(self.score(h, max_tweets))
            if i < total - 1:
                time.sleep(random.uniform(*pause_range))
        return results

    def score_from_csv(
        self,
        csv_path: str | Path,
        handle_col: str = "author_handle",
        max_tweets: int = 5,
    ) -> pd.DataFrame:
        """CSVからハンドルを読み取り、全アカウントを分析してDataFrameで返す。"""
        df = pd.read_csv(csv_path)
        handles = df[handle_col].dropna().unique().tolist()
        self._log(f"  CSV: {csv_path} → {len(handles)} unique handles")
        results = self.score_many(handles, max_tweets)
        return pd.DataFrame([_result_to_row(r) for r in results])

    def save_results(self, results: list[dict], prefix: str = "trust") -> tuple[Path, Path]:
        """JSON + CSV で保存して (json_path, csv_path) を返す。"""
        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        jp = self.output_dir / f"{prefix}_{ts}.json"
        cp = self.output_dir / f"{prefix}_{ts}.csv"

        with open(jp, "w") as f:
            json.dump(results, f, indent=2, ensure_ascii=False, default=str)

        pd.DataFrame([_result_to_row(r) for r in results]).to_csv(cp, index=False, encoding="utf-8-sig")
        self._log(f"  保存: {jp}")
        self._log(f"  保存: {cp}")
        return jp, cp

    def print_summary(self, results: list[dict]):
        """結果のサマリーテーブルを表示。"""
        print(f"\n{'='*60}")
        print(f"  {'Score':>5}  {'Rank':<2}  {'Handle':<20} {'Name':<20} {'Followers':>10}")
        print(f"{'='*60}")
        for r in sorted(results, key=lambda x: x.get("total_score", 0), reverse=True):
            s = r.get("total_score", 0)
            rk = r.get("rank", "?")
            h = f"@{r.get('handle', '?')}"
            n = (r.get("display_name") or "?")[:18]
            fol = r.get("followers_count", 0)
            print(f"  {s:>5}  {rk:<2}   {h:<20} {n:<20} {fol:>10,}")
        print(f"{'='*60}")
