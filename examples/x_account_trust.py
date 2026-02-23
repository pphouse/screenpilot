#!/usr/bin/env python3
"""
X (Twitter) アカウント信頼度スコアリング — CLI
================================================
x_trust_lib.TrustScorer を使う薄いCLIラッパー。

Usage:
    # ハンドル直接指定
    python3 examples/x_account_trust.py @AnthropicAI @OpenAI --csv

    # テキストファイルから
    python3 examples/x_account_trust.py handles.txt --csv

    # CSVの author_handle 列から
    python3 examples/x_account_trust.py --from-csv recordings/x_medical_data/medical_all_*.csv

    # スクショ・アイコンDL省略 (高速モード)
    python3 examples/x_account_trust.py @user1 @user2 --fast
"""

import argparse
import glob
from pathlib import Path

from x_trust_lib import TrustScorer


def main():
    parser = argparse.ArgumentParser(description="X アカウント信頼度スコアリング")
    parser.add_argument("handles", nargs="*",
                        help="@handle, handles.txt, or omit with --from-csv")
    parser.add_argument("--from-csv", dest="from_csv", nargs="+", default=None,
                        help="CSVファイル (glob可) の author_handle 列からハンドル取得")
    parser.add_argument("--handle-col", default="author_handle",
                        help="--from-csv 時のカラム名 (default: author_handle)")
    parser.add_argument("--csv", action="store_true", help="結果をCSVに保存")
    parser.add_argument("--max-tweets", type=int, default=5)
    parser.add_argument("--fast", action="store_true",
                        help="スクショ・アイコンDLをスキップ")
    parser.add_argument("--quiet", action="store_true")
    args = parser.parse_args()

    # ハンドル収集
    handles = []

    # --from-csv
    if args.from_csv:
        import pandas as pd
        for pattern in args.from_csv:
            for f in sorted(glob.glob(pattern)):
                df = pd.read_csv(f)
                if args.handle_col in df.columns:
                    handles.extend(df[args.handle_col].dropna().unique().tolist())
        handles = list(dict.fromkeys(handles))  # 順序保持ユニーク

    # 位置引数
    for h in args.handles or []:
        if h.endswith(".txt") and Path(h).exists():
            handles.extend(line.strip() for line in Path(h).read_text().splitlines() if line.strip())
        else:
            handles.append(h.lstrip("@"))

    if not handles:
        parser.print_help()
        return

    handles = list(dict.fromkeys(handles))  # dedup

    print(f"対象: {len(handles)} アカウント\n")

    with TrustScorer(
        download_icons=not args.fast,
        take_screenshots=not args.fast,
        quiet=args.quiet,
    ) as scorer:
        results = scorer.score_many(handles, max_tweets=args.max_tweets)

        if args.csv:
            scorer.save_results(results, prefix="trust_report")

        scorer.print_summary(results)


if __name__ == "__main__":
    main()
