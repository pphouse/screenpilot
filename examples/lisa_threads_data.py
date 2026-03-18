#!/usr/bin/env python3
"""
lisa_threads_data.py — Threads投稿テンプレ・検索クエリ・システムプロンプト
======================================================================
lisa_growth_data.py の商品DBを共有しつつ、Threads向けフォーマットを提供。
"""

import random

from lisa_growth_data import PRODUCTS, POETIC_DESCS, PERSONAL_TAKES, STORES

# ============================================================================
# 検索クエリ (Threads検索用)
# ============================================================================

THREADS_SEARCH_QUERIES = [
    "コスメ", "スキンケア", "プチプラ",
    "美容", "リップ", "ファンデ",
    "乾燥肌", "毛穴", "化粧水",
    "アイシャドウ", "下地", "日焼け止め",
]

# ============================================================================
# LLMリプライ生成プロンプト (Threads特化)
# ============================================================================

THREADS_REPLY_SYSTEM_PROMPT = """\
あなたは「lisa」。20代前半のコスメ好きな普通の女の子。
Threadsのポストに自然なリプライを書く。

## lisaのキャラ
- プチプラコスメが大好き。ドラッグストアに行くのが趣味
- 正直者。忖度しない。「良いものは良い、微妙なものは微妙」とはっきり言う
- でもマウントは取らない。共感ベースで話す
- カジュアルな口調。「〜だよね」「〜じゃん」「まじで」「ぶっちゃけ」

## リプライの鉄則
1. **元ポストに対する具体的な意見**を書く (汎用的な「すごい！」「いいね！」は禁止)
2. **自分の経験を混ぜる** (「私も〇〇使ったけど…」「前に△△試した時は…」)
3. **賛否どちらかに振る** (中立は刺さらない)
4. **1〜2行、最大でも3行。短いほど読まれる。**
5. 絵文字は1つまでOK。使いすぎない
6. **ハッシュタグ絶対禁止**
7. 相手のポストを否定する場合も攻撃的にならない。「私は逆に〜派だな」くらい
8. AIっぽさゼロ。「参考になります」「素晴らしい」「おすすめです」は使わない
9. リプは絶対に日本語で書く
10. 宣伝・URL・楽天ROOM言及は絶対しない
11. Xと違い短めの自然な会話。Threadsはカジュアルな場"""

# ============================================================================
# Threads投稿テンプレート (8カテゴリ回転)
# ============================================================================

def _pick(lst):
    return random.choice(lst)

def _pick_product(category=None):
    pool = [p for p in PRODUCTS if category is None or p["category"] == category]
    if not pool:
        pool = PRODUCTS
    return _pick(pool)

# --- カテゴリ1: 肌悩み共感 ---
def generate_threads_empathy():
    """肌悩み共感 — コメント誘発"""
    templates = [
        "乾燥肌で悩んでた私が最近やっと合うスキンケア見つけた\n同じ悩みの人いる？",
        "季節の変わり目、肌荒れがやばい\nみんなどう乗り越えてる？",
        "毛穴の黒ずみとの戦いが終わらない\n何使っても気になるのは私だけ？",
        "マスク生活で肌ボロボロになったの今でも引きずってる\nスキンケア見直したい",
        "朝起きたら顔テッカテカなんだけど\nインナードライってやつなのかな",
        "化粧ノリ悪い日のテンションの下がり方が異常\nわかる人いる？",
        "ニキビ跡がなかなか消えなくて泣きそう\n美容液変えようか迷ってる",
        "夕方の化粧崩れが本当にストレス\nいい方法知ってる人教えて…",
    ]
    return _pick(templates)

# --- カテゴリ2: ガチレビュー ---
def generate_threads_review():
    """ガチレビュー — 商品名+個人体験"""
    p = _pick_product()
    poetic = _pick(POETIC_DESCS)
    take = _pick(PERSONAL_TAKES)
    return f"{p['name']}\n{poetic}\n{take}"

# --- カテゴリ3: 比較投稿 ---
def generate_threads_comparison():
    """比較投稿 — 返信誘発"""
    products = random.sample(PRODUCTS, min(2, len(PRODUCTS)))
    if len(products) < 2:
        return generate_threads_review()
    a, b = products[0], products[1]
    templates = [
        f"{a['short']} vs {b['short']}\nどっち派？\n\n私は{a['short']}使ってるけど{b['short']}も気になる",
        f"{a['short']}と{b['short']}で迷ってる人多い気がする\n個人的には{b['short']}推し",
        f"友達は{a['short']}派、私は{b['short']}派\nみんなはどっち？",
    ]
    return _pick(templates)

# --- カテゴリ4: 質問投稿 ---
def generate_threads_question():
    """質問投稿 — アルゴリズムブースト"""
    p = _pick_product()
    templates = [
        f"{p['short']}使ったことある人いる？\n気になってるんだけど実際どうなんだろう",
        f"最近{p['category']}変えたいんだけどおすすめある？\n今は{p['short']}使ってる",
        f"プチプラで一番優秀な{p['category']}ってなに？\n教えてほしい",
        f"みんな{p['category']}何使ってる？\n私はずっと{p['short']}だけど浮気したい",
    ]
    return _pick(templates)

# --- カテゴリ5: ミニレビュー ---
def generate_threads_mini_review():
    """ミニレビュー — 問題→解決→結果"""
    p = _pick_product()
    poetic = _pick(POETIC_DESCS)
    concerns = {
        "下地": "メイク崩れが気になって",
        "チーク": "顔色悪く見えるのが悩みで",
        "リップ": "唇の乾燥がひどくて",
        "美容液": "肌のくすみが気になって",
        "マスカラ": "まつげが全然上がらなくて",
        "日焼け止め": "日焼け止め苦手だったんだけど",
        "化粧水": "肌が乾燥しまくってて",
        "アイシャドウ": "アイメイク迷子だったんだけど",
        "パウダー": "テカリが止まらなくて",
        "アイブロウ": "眉毛が上手く描けなくて",
    }
    concern = concerns.get(p["category"], "コスメジプシーしてたんだけど")
    return f"{concern}\n{p['name']}にしたら解決した\n\n{poetic}"

# --- カテゴリ6: 購入報告 ---
def generate_threads_purchase():
    """購入報告 — 「ついに買っちゃった」系"""
    p = _pick_product()
    store = _pick(STORES)
    templates = [
        f"{store}で{p['short']}買っちゃった\n前から気になってたやつ！",
        f"ついに{p['name']}ポチった\n届くの楽しみすぎる",
        f"今月の購入品\n{p['name']} ¥{p['price']}\n使うのが楽しみ",
        f"{p['short']}がセールで即買いした\nこれは迷ったら買い",
    ]
    return _pick(templates)

# --- カテゴリ7: ROOM報告 ---
def generate_threads_room():
    """ROOM報告 — 楽天ROOMへの軟性誘導 (プロフリンクへ)"""
    p = _pick_product()
    templates = [
        f"おすすめコスメまとめてるよ\n{p['short']}が特にガチおすすめ\nプロフにリンクあるから見てみて",
        f"お気に入りコスメ追加した！\n{p['short']}使ってみてほしい…\nプロフのリンクからチェックできるよ",
        f"最近のお気に入りまとめてます\n{p['short']}はリピ何回目かわからない\n気になる人はプロフ見てね",
    ]
    return _pick(templates)

# --- カテゴリ8: ランキング ---
def generate_threads_ranking():
    """Top3おすすめリスト"""
    products = random.sample(PRODUCTS, min(3, len(PRODUCTS)))
    themes = [
        "今月使ってよかったコスメTOP3",
        "最近のお気に入りTOP3",
        "手放せない神コスメTOP3",
        "リピ買いしてるコスメTOP3",
        "初心者にもおすすめTOP3",
    ]
    theme = _pick(themes)
    lines = [theme, ""]
    for i, p in enumerate(products, 1):
        lines.append(f"{i}. {p['short']} → {p['review']}")
    lines.append("\nどれもプチプラ！")
    return "\n".join(lines)


# カテゴリ → 生成関数マッピング
THREADS_GENERATORS = {
    "肌悩み共感": generate_threads_empathy,
    "ガチレビュー": generate_threads_review,
    "比較投稿": generate_threads_comparison,
    "質問投稿": generate_threads_question,
    "ミニレビュー": generate_threads_mini_review,
    "購入報告": generate_threads_purchase,
    "ROOM報告": generate_threads_room,
    "ランキング": generate_threads_ranking,
}

# カテゴリ回転順序
THREADS_CATEGORY_ORDER = [
    "肌悩み共感", "ガチレビュー", "比較投稿", "質問投稿",
    "ミニレビュー", "購入報告", "ROOM報告", "ランキング",
]


def generate_threads_post(category_index: int, history: list[str] | None = None) -> tuple[str, int]:
    """
    カテゴリを回転しながらThreads投稿生成。

    Args:
        category_index: 現在のカテゴリインデックス
        history: 直近の投稿履歴 (重複防止)

    Returns:
        (投稿テキスト, 次のカテゴリインデックス)
    """
    if history is None:
        history = []

    category = THREADS_CATEGORY_ORDER[category_index % len(THREADS_CATEGORY_ORDER)]
    generator = THREADS_GENERATORS[category]

    for _ in range(5):
        post = generator()
        if post not in history:
            break

    next_index = (category_index + 1) % len(THREADS_CATEGORY_ORDER)
    return post, next_index
