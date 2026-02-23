#!/usr/bin/env python3
"""
共通設定: AI関連日本株の銘柄リスト・CSV定義・センチメント判定
"""

from dataclasses import dataclass, field

# ============================================================================
# 銘柄定義
# ============================================================================

@dataclass
class AIStock:
    name: str
    ticker: str
    search_queries: list[str] = field(default_factory=list)


AI_STOCKS = [
    AIStock("さくらインターネット", "3778", [
        "さくらインターネット 株", "3778 株価", "さくらインターネット AI",
    ]),
    AIStock("PKSHA Technology", "3993", [
        "PKSHA 株", "3993 株価", "PKSHA Technology AI",
    ]),
    AIStock("Appier Group", "4180", [
        "Appier 株", "4180 株価", "Appier Group AI",
    ]),
    AIStock("AI inside", "4488", [
        "AI inside 株", "4488 株価", "AI inside 決算",
    ]),
    AIStock("HEROZ", "4382", [
        "HEROZ 株", "4382 株価", "HEROZ AI",
    ]),
    AIStock("ブレインパッド", "3655", [
        "ブレインパッド 株", "3655 株価", "ブレインパッド AI",
    ]),
    AIStock("Preferred Networks", "", [
        "Preferred Networks", "PFN AI", "プリファードネットワークス",
    ]),
]

# ============================================================================
# CSVカラム定義
# ============================================================================

CSV_COLUMNS = [
    "stock_name",
    "ticker",
    "search_query",
    "tweet_text",
    "author_handle",
    "author_name",
    "timestamp",
    "likes",
    "retweets",
    "replies",
    "views",
    "tweet_url",
    "sentiment",
    "scraped_at",
]

# ============================================================================
# センチメント判定
# ============================================================================

BULLISH_KEYWORDS = [
    "上昇", "急騰", "高値", "買い", "ストップ高", "好決算", "増収", "増益",
    "最高値", "強い", "期待", "成長", "上方修正", "好材料", "爆上げ",
    "bullish", "buy", "surge", "breakout", "moon",
]

BEARISH_KEYWORDS = [
    "下落", "急落", "安値", "売り", "ストップ安", "赤字", "減収", "減益",
    "暴落", "弱い", "懸念", "下方修正", "悪材料", "損切り",
    "bearish", "sell", "crash", "dump", "short",
]


def classify_sentiment(text: str) -> str:
    """ツイートテキストからbullish/bearish/neutralを判定"""
    text_lower = text.lower()
    bull = sum(1 for kw in BULLISH_KEYWORDS if kw in text_lower)
    bear = sum(1 for kw in BEARISH_KEYWORDS if kw in text_lower)
    if bull > bear:
        return "bullish"
    elif bear > bull:
        return "bearish"
    return "neutral"
