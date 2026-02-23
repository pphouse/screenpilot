#!/usr/bin/env python3
"""
共通設定: 医療業界ニュース・補助金・診療報酬のX検索
"""

from dataclasses import dataclass, field


@dataclass
class MedicalTopic:
    name: str
    category: str  # news / subsidy / fee_revision
    search_queries: list[str] = field(default_factory=list)


MEDICAL_TOPICS = [
    # --- 医療ニュース全般 ---
    MedicalTopic("医療ニュース", "news", [
        "医療 ニュース 2026",
    ]),
    MedicalTopic("医療DX", "news", [
        "医療DX",
    ]),
    MedicalTopic("オンライン診療", "news", [
        "オンライン診療",
    ]),
    MedicalTopic("医療AI", "news", [
        "医療AI",
    ]),

    # --- 補助金・助成金 ---
    MedicalTopic("医療機関補助金", "subsidy", [
        "医療機関 補助金",
    ]),
    MedicalTopic("病院経営支援", "subsidy", [
        "病院 補助金 助成金",
    ]),
    MedicalTopic("IT導入補助金(医療)", "subsidy", [
        "IT導入補助金 医療",
    ]),
    MedicalTopic("地域医療介護総合確保基金", "subsidy", [
        "地域医療介護総合確保基金",
    ]),

    # --- 診療報酬 ---
    MedicalTopic("診療報酬改定", "fee_revision", [
        "診療報酬改定 2026",
    ]),
    MedicalTopic("診療報酬 点数", "fee_revision", [
        "診療報酬 点数",
    ]),
    MedicalTopic("調剤報酬", "fee_revision", [
        "調剤報酬",
    ]),
    MedicalTopic("介護報酬", "fee_revision", [
        "介護報酬",
    ]),

    # --- 医療IT・システム ---
    MedicalTopic("電子カルテ", "medical_it", [
        "電子カルテ",
    ]),
    MedicalTopic("電子カルテ 標準化", "medical_it", [
        "電子カルテ 標準化",
    ]),
    MedicalTopic("退院サマリー", "medical_it", [
        "退院サマリー",
    ]),
    MedicalTopic("ベンダーロック", "medical_it", [
        "ベンダーロック 医療",
    ]),
    MedicalTopic("ベンダーロック(電子カルテ)", "medical_it", [
        "電子カルテ ベンダーロック",
    ]),
    MedicalTopic("AI議事録", "medical_it", [
        "AI議事録 医療",
    ]),
    MedicalTopic("AI議事録(病院)", "medical_it", [
        "AI議事録 病院",
    ]),
    MedicalTopic("医療情報システム", "medical_it", [
        "医療情報システム クラウド",
    ]),
]

CSV_COLUMNS = [
    "topic_name",
    "category",
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

# --- センチメント ---

POSITIVE_KEYWORDS = [
    "拡充", "増額", "引き上げ", "加算", "新設", "支援", "推進", "前進",
    "改善", "充実", "期待", "朗報", "歓迎", "好影響", "プラス改定",
]

NEGATIVE_KEYWORDS = [
    "削減", "引き下げ", "廃止", "縮小", "負担増", "厳格化", "批判",
    "問題", "懸念", "反対", "マイナス改定", "不足", "崩壊", "疲弊",
]


def classify_sentiment(text: str) -> str:
    text_lower = text.lower()
    pos = sum(1 for kw in POSITIVE_KEYWORDS if kw in text_lower)
    neg = sum(1 for kw in NEGATIVE_KEYWORDS if kw in text_lower)
    if pos > neg:
        return "positive"
    elif neg > pos:
        return "negative"
    return "neutral"
