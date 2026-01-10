# coding: utf-8
import yfinance as yf
import pandas as pd
import datetime
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from collections import Counter

# =====================
# 設定
# =====================
TARGET_CODES_FILE = "tse_prime_codes.csv"  # ヘッダーなしCSV
MAX_WORKERS = 5
PRICE_LIMIT = 2000  # 株価上限
PERIOD = "6mo"

# =====================
# 安全なダウンロード（リトライ付き）
# =====================
def safe_download(ticker):
    for _ in range(2):
        try:
            df = yf.download(
                ticker,
                period=PERIOD,
                progress=False,
                threads=False
            )
            return df
        except Exception:
            time.sleep(1)
    return None

# =====================
# 個別銘柄チェック
# =====================
def check_stock(code):
    try:
        df = safe_download(f"{code}.T")

        if df is None or df.empty:
            return None, "データ空（非上場・廃止・停止）"

        required_cols = {"Open", "High", "Low", "Close", "Volume"}
        if not required_cols.issubset(df.columns):
            return None, "カラム不足"

        if len(df) < 25:
            return None, "データ不足"

        df = df.dropna()
        if len(df) < 25:
            return None, "NaN除外後不足"

        close_today = float(df["Close"].iloc[-1])
        if close_today > PRICE_LIMIT:
            return None, "株価2000円超"

        low_25 = df["Low"].iloc[-25:].min()

        # 25日終値が底値±10%以内
        close_25 = df["Close"].iloc[-25:]
        if not close_25.between(low_25 * 0.9, low_25 * 1.1).all():
            return None, None

        # 底値から10%以上上昇
        if close_today < low_25 * 1.1:
            return None, None

        # 出来高条件
        vol_avg = df["Volume"].iloc[-25:].mean()
        if not (
            df["Volume"].iloc[-1] >= vol_avg * 2 and
            df["Volume"].iloc[-2] >= vol_avg * 2
        ):
            return None, None

        return code, None

    except Exception:
        return None, "通信・APIエラー"

# =====================
# メイン処理
# =====================
def main():
    start_time = datetime.datetime.now()
    print(f"▶ 開始: {start_time.strftime('%Y-%m-%d %H:%M:%S')}")

    # --- CSV前処理（対策②） ---
    codes = (
        pd.read_csv(TARGET_CODES_FILE, header=None)
          .iloc[:, 0]
          .astype(str)
          .str.strip()
    )

    codes = codes[
        codes.str.fullmatch(r"\d{4}")
    ].unique().tolist()

    results = []
    error_counter = Counter()

    with ThreadPoolExecutor(max_workers=MAX_WORKERS) as executor:
        futures = {executor.submit(check_stock, code): code for code in codes}

        for future in as_completed(futures):
            result, error = future.result()

            if error:
                error_counter[error] += 1
            elif result:
                results.append(result)

    end_time = datetime.datetime.now()

    # =====================
    # 結果表示
    # =====================
    print(f"\n▶ スクリーニング終了: {end_time.strftime('%Y-%m-%d %H:%M:%S')}")
    print(f"⏱ 処理時間: {end_time - start_time}")

    print("\n--- 取得失敗・除外 内訳 ---")
    for k, v in error_counter.items():
        print(f"{k}: {v}")

    print(f"\n✅ ヒット銘柄数: {len(results)}")
    if results:
        print("ヒット銘柄:", ", ".join(results))

# =====================
if __name__ == "__main__":
    main()
