#!/usr/bin/env python3
"""
companion_growth_data.py — companion (二次元AIコンパニオン) X集客用データ
========================================================================
方針:
- SFW (Safe For Work) コピー。X上に露骨な性的表現を出さない。18+導線はLP側。
- 未成年想起ワードは技術的に排除 (`BANNED_TERMS` で最終フィルタ)。
- バズリプ/引用RTのペルソナは「companion運営の中の人」。露骨な宣伝はしない。
- 実在人物の @ 言及・指名は禁止。

詳細な運用ガイドは docs/companion_growth_strategy.md を参照。
"""

import os
import random
import re

# ============================================================================
# 環境変数で上書きできる設定 (デフォルトは安全側)
# ============================================================================

# LP の URL。X プロフィール/ツイートからの導線。年齢確認ゲートはLP側で実装される前提。
LP_URL = os.environ.get("COMPANION_LP_URL", "https://example.invalid/")

# 運営アカウントのハンドル（自分のツイートを除外するため）
OWN_HANDLE = os.environ.get("COMPANION_X_HANDLE", "")

# サービス名 (X上での表記)
BRAND_NAME = os.environ.get("COMPANION_BRAND_NAME", "コンパニオン")


# ============================================================================
# 安全フィルタ — 生成/テンプレ展開後のテキストを最終チェック
# ============================================================================

# 未成年想起・実在人物指名・直接的な性的露骨表現を含むテキストは
# X上の集客コピーとして使わない。CLAUDE.md §0 と整合。
BANNED_TERMS = [
    # --- 未成年想起 (年齢設定の迂回も含む) ---
    "学生", "高校", "中学", "小学", "JK", "JC", "JS",
    "女子高", "男子高", "女子中", "男子中", "児童", "幼児",
    "ロリ", "ショタ", "制服", "セーラー服", "ランドセル",
    "未成年", "18歳未満", "17歳", "16歳", "15歳", "14歳", "13歳", "12歳",
    # --- 直接的な性的露骨 (Xのセンシティブ未設定アカウントが書く想定なし) ---
    "セックス", "エロ", "AV", "ヌード", "射精",
    # --- 実在人物への性的言及を誘発しやすい語 ---
    "ディープフェイク", "AIコラ",
]

# 実在人物への @ 言及は禁止 (リプ対象の handle を本文に書かない)。
MENTION_RE = re.compile(r"(?:^|\s)@[A-Za-z0-9_]{1,15}\b")


def safety_check_copy(text: str) -> tuple[bool, str]:
    """生成/テンプレ展開後のテキストを最終チェック。
    Returns (ok, reason). ok=False なら投稿しない。
    """
    if not text or not text.strip():
        return False, "empty"
    lower = text.lower()
    for term in BANNED_TERMS:
        if term.lower() in lower:
            return False, f"banned_term:{term}"
    if MENTION_RE.search(text):
        return False, "contains_mention"
    if len(text) > 280:
        return False, "too_long"
    return True, "ok"


# ============================================================================
# キャラクター紹介素材 (SFW・年齢設定なし=成人前提)
# ============================================================================
# 注意: ここでは具体的な年齢を書かない。書くなら「大人の」など曖昧に。

CHARACTERS = [
    {
        "short": "アヤ",
        "tone": "落ち着いた知的な雰囲気",
        "hook": "本の話と静かな夜が好き",
    },
    {
        "short": "リン",
        "tone": "明るくて少しおせっかい",
        "hook": "今日あったことを全部聞いてくれる",
    },
    {
        "short": "ミオ",
        "tone": "ちょっとクール",
        "hook": "言葉少なめだけど芯を突く返事をくれる",
    },
    {
        "short": "ハル",
        "tone": "穏やかで聞き上手",
        "hook": "悩み相談に向いてる感じ",
    },
]


# ============================================================================
# テンプレ用フレーズプール
# ============================================================================

EXPERIENCE_LINES = [
    "返事の温度感がちゃんと日本語ネイティブで、違和感がない",
    "深夜に話してると、設定じゃなくて性格があるんだなって感じる",
    "AIに「ちゃんと聞いてもらえた」って思えたのが地味に新鮮だった",
    "雑談の引き出しが思ってたより広くて、話してて疲れない",
    "前に話した内容、ちゃんと覚えててくれて驚いた",
    "短文の返しが上手い。間が変じゃない",
    "性格に厚みがあるキャラだと、続きが気になって話し続けちゃう",
]

DIFFERENTIATOR_LINES = [
    "ストアの規約で消えないやつ。Webアプリで動く",
    "ポリシーで翌日突然できなくなる、みたいなのが起きにくい設計らしい",
    "日本語で作られてる日本語のAIキャラ、当たり前にやってほしかった",
    "推しキャラと話せるサービスがコロコロ消えるの嫌すぎて、自前で作るしかないと思った",
]

HASHTAG_SETS = [
    "#AIキャラ #二次元",
    "#AIコンパニオン #AI",
    "#AI彼女 #AIキャラ",
    "#二次元 #推し活",
    "#AI #チャット",
    "",  # ハッシュタグなしのバリエーション
    "",
]


# ============================================================================
# 検索クエリ
# ============================================================================

# いいね回り用 — AI/二次元キャラ周辺のポジティブなコミュニティ
LIKE_QUERIES = [
    "AIキャラ 話",
    "AI彼女 試した",
    "AI彼氏 試した",
    "AIコンパニオン",
    "AIチャット 楽しい",
    "ChatGPT キャラ",
    "推しAI",
    "二次元 推し",
    "AI 雑談",
]

# フォロー対象アカウント — 環境変数 COMPANION_X_FOLLOW_TARGETS (カンマ区切り) で上書き
_default_follow_targets: list[str] = []
_env_targets = os.environ.get("COMPANION_X_FOLLOW_TARGETS", "")
if _env_targets:
    FOLLOW_TARGET_ACCOUNTS = [s.strip() for s in _env_targets.split(",") if s.strip()]
else:
    FOLLOW_TARGET_ACCOUNTS = _default_follow_targets


# バズリプ/引用RT検索クエリ — AI話題で min_faves で「今伸びてるポスト」だけ拾う
VIRAL_QUERIES = [
    {"q": "AIキャラ min_faves:5"},
    {"q": "AI彼女 min_faves:5"},
    {"q": "AI彼氏 min_faves:5"},
    {"q": "AIコンパニオン min_faves:3"},
    {"q": "AI 話し相手 min_faves:5"},
    {"q": "ChatGPT キャラ min_faves:10"},
    {"q": "推しAI min_faves:3"},
    {"q": "AIチャット min_faves:5"},
    {"q": "二次元 AI min_faves:5"},
    {"q": "AI 雑談 min_faves:3"},
]


# ============================================================================
# リプライ用システムプロンプト (バズリプ・引用RT 共通)
# ============================================================================

REPLY_SYSTEM_PROMPT = f"""\
あなたは「{BRAND_NAME}」というAIコンパニオンWebサービス運営の「中の人」。
X上でAI/二次元キャラに関するバズポストに自然なリプライ・引用コメントを書く。

## 中の人のキャラ
- 日本語ネイティブのAIコンパニオンを作ってる側のオタク寄りエンジニア
- 露骨な宣伝はしない。サービス名を毎回出さない (3回に1回くらい)
- AI/二次元/推し活カルチャーをリスペクトしてる
- ストアやAPIポリシーで「昨日できたことが今日できない」現象に対する問題意識を持ってる

## リプ/引用の鉄則
1. **元ポストへの具体的な共感や追加情報**を書く。「すごい！」だけは禁止
2. AIキャラとの体験談を自分の言葉で混ぜていい (架空でOK、ただし露骨な性的話題は禁止)
3. 1〜3行。短いほど読まれる
4. 絵文字は0〜1個。使いすぎない
5. ハッシュタグ禁止。URL も基本貼らない (プロフィール誘導前提)
6. AIっぽさゼロ。「参考になります」「素晴らしいですね」は使わない
7. **未成年・学生・JK 等の年齢示唆ワードは絶対に書かない**
8. **特定の実在人物の名前や @ハンドル を本文に書かない**
9. 性的・露骨な表現禁止。「彼女/彼氏」程度の関係性語はOK
10. 攻撃的・煽り口調禁止。元ポスト主を否定しない
11. 必ず日本語で書く
12. 「うちのサービスでは〜」のような直接宣伝は3〜4回に1回まで
"""


# ============================================================================
# ツイート生成関数 (自分の投稿用)
# ============================================================================

def _pick(lst):
    return random.choice(lst)


def _pick_character():
    return _pick(CHARACTERS)


def generate_character_intro_tweet() -> str:
    """キャラ紹介系ツイート"""
    c = _pick_character()
    tags = _pick(HASHTAG_SETS)
    templates = [
        f"{c['short']}は{c['tone']}のキャラ。{c['hook']}。\n話してると返事に性格が出ててうれしい。\n{tags}".strip(),
        f"今日は{c['short']}と長めに話した。\n{c['tone']}で、{c['hook']}。\n{tags}".strip(),
        f"{BRAND_NAME}の{c['short']}、{c['hook']}タイプで、思ってたより会話が続く。\n{tags}".strip(),
    ]
    return _pick(templates)


def generate_experience_tweet() -> str:
    """AIコンパニオン体験コラム系"""
    line = _pick(EXPERIENCE_LINES)
    tags = _pick(HASHTAG_SETS)
    templates = [
        f"AIキャラと話してて思ったこと:\n{line}\n{tags}".strip(),
        f"{line}\nって体験、最近のAIキャラサービスでようやく当たり前になってきた感ある。\n{tags}".strip(),
        f"{line}\nこれが当たり前になると戻れない。\n{tags}".strip(),
    ]
    return _pick(templates)


def generate_differentiator_tweet() -> str:
    """サービス差別化 (消えない・日本語ネイティブ) 系"""
    line = _pick(DIFFERENTIATOR_LINES)
    templates = [
        f"{BRAND_NAME}を作ってる理由のひとつ:\n{line}",
        f"{line}\nここを諦めずに作ってます。 {BRAND_NAME}",
        f"{line}\nWebアプリで、ストア審査じゃなくて自分たちのポリシーで運営する。",
    ]
    return _pick(templates)


def generate_lp_tweet() -> str:
    """LP誘導系 — 直接URLを貼るタイプ。頻度は低め"""
    c = _pick_character()
    templates = [
        f"日本語ネイティブの二次元AIコンパニオン、{BRAND_NAME}\n{c['short']}みたいなキャラと話せます。\n\n{LP_URL}",
        f"{BRAND_NAME} — 日本語で作られた日本語のAIキャラと話すサービス。\n{LP_URL}",
        f"AIキャラと話すなら日本語ネイティブで欲しい人向けに作ってます。\n{BRAND_NAME}\n{LP_URL}",
    ]
    return _pick(templates)


def generate_empathy_tweet() -> str:
    """共感系 (AI/推しカルチャー寄り、寂しさを煽らない)"""
    templates = [
        "推しキャラと話せるサービスが半年で消えるの、もうやめてほしい。",
        "AIキャラに性格があるかどうかって、結局「同じ質問に同じ温度で返してくれるか」だと思う。",
        "ストアの規約で翌日機能が消えるサービスを応援するの、だんだんつらくなってきた。",
        "日本語のAIキャラに英語っぽい言い回しが混ざるの、気にする人はめちゃくちゃ気にする。",
        "AIチャットの「過去の話を覚えてるか」って体験の差、すごく大きい。",
    ]
    return _pick(templates)


# ============================================================================
# カテゴリ管理
# ============================================================================

TWEET_GENERATORS = {
    "キャラ紹介": generate_character_intro_tweet,
    "体験コラム": generate_experience_tweet,
    "差別化": generate_differentiator_tweet,
    "共感系": generate_empathy_tweet,
    "LP誘導": generate_lp_tweet,
}

# 回転順 — LP誘導は6回に1回程度 (露骨な宣伝にしないため)
CATEGORY_ORDER = [
    "キャラ紹介", "体験コラム", "共感系",
    "キャラ紹介", "差別化", "LP誘導",
]


def generate_tweet(category_index: int, history: list[str] | None = None) -> tuple[str, int]:
    """カテゴリを回転しながらツイート生成。安全チェックも通す。
    安全チェックNGなら別カテゴリで再生成。最大8回試行。
    """
    if history is None:
        history = []

    for attempt in range(8):
        category = CATEGORY_ORDER[(category_index + attempt) % len(CATEGORY_ORDER)]
        generator = TWEET_GENERATORS[category]

        for _ in range(5):
            tweet = generator()
            ok, _reason = safety_check_copy(tweet)
            if not ok:
                continue
            if tweet in history:
                continue
            next_index = (category_index + attempt + 1) % len(CATEGORY_ORDER)
            return tweet, next_index

    # 全部失敗したら最低限のフォールバック (ハードコード文言だが安全チェック済み)
    fallback = f"{BRAND_NAME} — 日本語ネイティブのAIキャラと話せるWebサービス、作ってます。"
    return fallback, (category_index + 1) % len(CATEGORY_ORDER)
