# morita-finance スクリーニング

このリポジトリは Yahoo Finance (yfinance) を使って日本株のスクリーニングを行うスクリプト `morita_screening_final.py` を含みます。

使い方（仮想環境を有効にした状態で）:

```bash
# 依存インストール
D:/Python/morita-finance/.venv/Scripts/python.exe -m pip install -r requirements.txt

# 最初の100件のみ処理（検証用）
D:/Python/morita-finance/.venv/Scripts/python.exe morita_screening_final.py --limit 100 --sleep 0.2

# 全件処理
D:/Python/morita-finance/.venv/Scripts/python.exe morita_screening_final.py
```

出力:

- `screening_results_YYYYMMDD_HHMMSS.csv` : 最終ヒット銘柄一覧
- `results_partial.csv` : 中間保存（500件ごと）
- `column_missing.csv` : 欠損カラムの報告
- `errors.log` : 詳細ログ（ダウンロード失敗や例外のスタックトレース）

備考:
- スクリプトは `--limit` オプションで検証を行えるようにしています。大規模実行時は `--sleep` を増やすか、バッチ化してください。
- 閾値ロジックは `THRESHOLD_RATIO` と `TOP_NEAR_RATIO` で調整できます。必要なら要件に合わせて私が調整します。
