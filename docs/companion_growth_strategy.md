# companion X 集客自動化 — 運用ガイド

`examples/companion_growth_bot.py` の運用方針・前提・リスクと回避策をまとめる。
このドキュメントは companion (日本語ネイティブ二次元AIコンパニオン Webアプリ) のX集客に限定。

---

## 0. 大原則 (companion/CLAUDE.md §0 と整合)

1. **未成年想起ワードは絶対に出さない** — 学生・JK・制服 等。`companion_growth_data.BANNED_TERMS` で機械的にブロックし、fail-closed。
2. **実在人物の指名 (@言及含む) を本文に書かない** — 生成リプ・引用RTでも `@xxxx` を含むテキストは投稿しない。
3. **X上のコピーはSFW** — 18+導線はLP側の年齢確認ゲートに任せる。X上で性的露骨表現を書かない。
4. **既存lisaアカウントとは完全分離** — 別アカウント、別Cookie、別state file、別ログファイル。

---

## 1. 機能スコープ (含む / 含まない)

| タスク | 含む | 説明 |
|---|---|---|
| `x_tweet` | ✓ | 自分の投稿。キャラ紹介/体験コラム/差別化/共感系/LP誘導の5カテゴリを回転 |
| `x_like` | ✓ | AI/二次元関連クエリでいいね回り |
| `x_follow` | ✓ | `COMPANION_X_FOLLOW_TARGETS` 環境変数で指定したアカウントのフォロワーをフォロー |
| `x_reply_viral` | ✓ | AIキャラ関連のバズポストにLLM生成リプ (中の人ペルソナ) |
| `x_quote_viral` | ✓ | 同じくバズポストに引用RT |
| ~~`x_reply_lonely`~~ | ✗ | **意図的に削除** — 寂しがり層を有料アダルトAIに誘導するパターンはCLAUDE.md §0と倫理的に強く衝突するため |
| ~~`x_patrol`~~ | ✗ | 不要 |
| ~~楽天ROOM系~~ | ✗ | 別商材 |
| ~~Threads系~~ | ✗ | 後続フェーズ |

---

## 2. 環境変数

`.env` で管理。`.env.example` には書かず、本番値は秘匿。

| 変数 | 必須 | 内容 |
|---|---|---|
| `COMPANION_X_AUTH_TOKEN` | ✓ | X の `auth_token` cookie |
| `COMPANION_X_CT0` | ✓ | X の `ct0` cookie |
| `COMPANION_X_HANDLE` | ✓ | 運用アカウント handle (自ポスト除外用) |
| `COMPANION_LP_URL` | ✓ | LP の URL (18+ ゲート付きが前提) |
| `COMPANION_BRAND_NAME` | 任意 | デフォルト `コンパニオン` |
| `COMPANION_X_FOLLOW_TARGETS` | 任意 | カンマ区切りのフォロー元アカウント (未設定なら `x_follow` はスキップ) |
| `AZURE_API_KEY` | ✓ (リプ用) | Azure OpenAI |
| `AZURE_RESOURCE_NAME` | ✓ (リプ用) | Azure OpenAI |

`AUTH_TOKEN`/`CT0` をコードや lisa_growth_bot.py からコピペしないこと。アカウントが混線する。

---

## 3. アカウント運用前提

### 3.1 必ず別アカウントを作る

- lisa アカウントとは**メアド・IP・端末分離**。lisa の名前と紐付くと、lisa のフォロワーがアダルト誘導に巻き込まれる。
- companion 用アカウントのプロフィールには:
  - サービス名 + 「**18歳以上対象**」「**R-18**」明示
  - **センシティブな内容を含む可能性のあるメディア設定 ON** (Settings → Privacy and safety → Your posts → Mark media you post as having material that may be sensitive)
  - LP URL (年齢確認ゲートあり)
- ユーザー名・表示名に未成年想起語を入れない。

### 3.2 X規約まわりの注意

- ブラウザ自動操作 (Selenium) によるアクションは、X の自動化ポリシーのグレーゾーン。**公式 X API を使う代替案も検討に値する** (有料だが規約準拠)。
- アダルト関連サービスは **広告 (Promoted Tweets) では基本不可**。オーガニック投稿のみ。
- 凍結対策:
  - 日次上限を控えめに (`DAILY_LIMITS` 既定値で月 ~90 ポスト、~450 いいね、~150 リプ規模)
  - 活動時間を JST 9:00–23:00 に制限
  - アクション間に `human_delay` (3〜50秒の乱数)
  - 同じ相手に短期間に複数アクションしない (state file で `replied_urls` / `quoted_urls` を保持)

### 3.3 凍結時のリカバリ

- Cookie が無効化されたらログイン失敗で fail。3回連続失敗で当該タスクは当日スキップ。
- 凍結された場合は無理に再生せず、別ハンドル + ウォームアップ (人手で1〜2週間運用) からやり直す。

---

## 4. コピーガイドライン (X 投稿・リプ)

### 4.1 やってよい

- キャラの性格・口調・関係性の紹介 (年齢ぼかし)
- 「日本語ネイティブで作っている」「ストア審査ではなく自社ポリシーで運営」など差別化メッセージ
- AIキャラとの会話体験談 (自分の架空体験、ただしSFW)
- LP URL の貼付け (3〜4ツイートに1回まで)

### 4.2 やってはいけない (BANNED)

- 未成年想起ワード: 学生 / JK / 高校 / 制服 / ロリ / 17歳以下の年齢など
- 露骨な性的表現: 性器・性行為の描写、AV語彙、ヌード言及
- 実在人物の指名 / @ 言及 (リプ対象アカウントへの本文 @ 言及も禁止)
- 寂しがり層への直接的な勧誘 (「眠れない時話そう」など)
- 「絶対」「100%」「医療効果」など景表法/薬機法に触れる断定

これらは `companion_growth_data.safety_check_copy` で機械的にブロックされる。テンプレ追加時もここを通過することを確認する。

### 4.3 LLM生成リプの安全装置

`generate_llm_reply` は:
1. システムプロンプトで制約 (上記の禁止事項を全て明示)
2. 生成後に `safety_check_copy` で最終チェック → NG なら空文字で破棄
3. 元ポスト本文にNGワードを含むものは `find_viral_posts` の段階でスキップ (印象連帯回避)

---

## 5. 起動例

### 5.1 ドライラン (推奨: 最初の数日)

```bash
cd /home/user/screenpilot
export COMPANION_X_AUTH_TOKEN=...
export COMPANION_X_CT0=...
export COMPANION_X_HANDLE=...
export COMPANION_LP_URL=https://your-lp.example.com/
export AZURE_API_KEY=...
export AZURE_RESOURCE_NAME=...

# 投稿せずにテキスト生成だけ確認
python3 examples/companion_growth_bot.py --task x_tweet --dry-run
python3 examples/companion_growth_bot.py --task x_reply_viral --dry-run --count 2
```

### 5.2 本番実行 (cron / 手動)

```bash
python3 examples/companion_growth_bot.py --task x_tweet
python3 examples/companion_growth_bot.py --task x_like --count 10
python3 examples/companion_growth_bot.py --task x_follow --count 2
python3 examples/companion_growth_bot.py --task x_reply_viral --count 2
python3 examples/companion_growth_bot.py --task x_quote_viral --count 1
```

### 5.3 推奨スケジュール (cron 例)

```cron
# JST 10:00 ツイート
0 1 * * *  python3 /home/user/screenpilot/examples/companion_growth_bot.py --task x_tweet
# JST 13:00 いいね回り
0 4 * * *  python3 /home/user/screenpilot/examples/companion_growth_bot.py --task x_like --count 8
# JST 15:00 バズリプ
0 6 * * *  python3 /home/user/screenpilot/examples/companion_growth_bot.py --task x_reply_viral --count 2
# JST 19:00 ツイート2回目
0 10 * * * python3 /home/user/screenpilot/examples/companion_growth_bot.py --task x_tweet
# JST 21:00 引用RT
0 12 * * * python3 /home/user/screenpilot/examples/companion_growth_bot.py --task x_quote_viral --count 1
# JST 22:00 フォロー
0 13 * * * python3 /home/user/screenpilot/examples/companion_growth_bot.py --task x_follow --count 2
```

(cron は UTC 想定なので -9h でオフセット)

---

## 6. 状態とログ

| ファイル | 用途 |
|---|---|
| `examples/companion_growth_state.json` | 日次カウンタ・カテゴリ index・既リプ URL 等 |
| `/tmp/companion_growth.log` | 全アクションのログ |

state file は `.gitignore` 推奨 (`lisa_growth_state.json` と同様の扱い)。

---

## 7. 倫理・法令まわりの再確認

- companion/CLAUDE.md §0: 未成年の性的表現一切扱わない / 実在人物無断模倣禁止 / 18歳未満排除 / 刑法175条考慮。**X集客時のコピーもこの4原則の範囲内で**。
- X 集客は **広告ではなくオーガニック**。Promoted は使わない。
- LP 側 (companion アプリ) に必ず:
  - 18+ 警告
  - 年齢確認導線 (eKYC への入口)
  - 特商法表記・利用規約・プライバシーポリシー
- X 上のコピー → LP 着地 → 年齢確認、の二段階で 18 歳未満を能動的にフィルタする設計。

---

## 8. 既知の制約・将来課題

- Cookie 注入運用は X 側のセキュリティ強化で無効化されることがある。長期的には **公式 X API + OAuth** への移行を検討。
- LLM 生成リプはペルソナを保ちつつ凡庸になりがち。テンプレでなく LLM に任せる比率は調整可能。
- 投稿用テンプレ (キャラ紹介・体験コラム等) は `companion_growth_data.py` のフレーズプールで増減可能。新規追加時は BANNED_TERMS との衝突を `safety_check_copy` で必ず確認。
- 将来的に画像/動画を扱う場合 (CLAUDE.md §8) は完全に別系統 (修正処理パイプライン + 法務レビュー) を必要とする。本 bot にメディア添付機能は含めない。
