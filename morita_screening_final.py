import yfinance as yf
import pandas as pd
from datetime import datetime
import time

# ========= 設定 =========
TARGET_CODES_FILE = "tse_prime_codes.csv"
DAYS = 25
PRICE_LIMIT = 2000
SLEEP_SEC = 0.1   # Yahoo負荷対策

# ========= ログ =========
error_counts = {
    "データ空（非上場・廃止・停止）": 0,
    "カラム不足": 0,
    "データ不足": 0,
}

column_missing_records = []

# ========= 判定関数 =========
def check_stock(code):
    try:
        df = yf.download(
            code,
            period="3mo",
            interval="1d",
            progress=False,
            auto_adjust=False,
            threads=False
        )

        if df is None or df.empty:
            error_counts["データ空（非上場・廃止・停止）"] += 1
            return None

        required_cols = {"Close", "Volume"}
        if not required_cols.issubset(df.columns):
            error_counts["カラム不足"] += 1
            column_missing_records.append({
                "code": code,
                "missing_columns": list(required_cols - set(df.columns)),
                "available_columns": list(df.columns)
            })
            return None

        df = df.tail(DAYS)
        if len(df) < DAYS:
            error_counts["データ不足"] += 1
            return None

        close_today = float(df["Close"].iloc[-1])
        if close_today > PRICE_LIMIT:
            return None

        low_25 = float(df["Close"].min())
        max_25 = float(df["Close"].max())

        if not (low_25 * 0.9 <= max_25 <= low_25 * 1.1):
            return None

        if close_today < low_25 * 1.1:
            return None

        vol_avg = float(df["Volume"].mean())
        vol_last2 = df["Volume"].iloc[-2:]

        if not (
            float(vol_last2.iloc[0]) >= vol_avg * 2 and
            float(vol_last2.iloc[1]) >= vol_avg * 2
        ):
            return None

        return {
            "code": code,
            "close": round(close_today, 2),
            "volume": int(vol_last2.iloc[-1])
        }

    except Exception:
        error_counts["データ空（非上場・廃止・停止）"] += 1
        return None

# ========= メイン =========
def main():
    start = datetime.now()
    print(f"▶ 開始: {start.strftime('%Y-%m-%d %H:%M:%S')}")

    codes = pd.read_csv(TARGET_CODES_FILE, header=None)[0].astype(str).tolist()
    codes = [c + ".T" if not c.endswith(".T") else c for c in codes]

    total = len(codes)
    results = []

    for i, code in enumerate(codes, 1):
        r = check_stock(code)
        if r:
            print(f"\nHIT: {r['code']}  終値={r['close']}")
            results.append(r)

        # ---- 進捗表示 ----
        elapsed = datetime.now() - start
        percent = (i / total) * 100
        print(
            f"\r進捗: {i} / {total} ({percent:5.1f}%)  経過: {elapsed}",
            end=""
        )

        time.sleep(SLEEP_SEC)

    print()  # 改行

    if column_missing_records:
        pd.DataFrame(column_missing_records).to_csv(
            "column_missing.csv",
            index=False,
            encoding="utf-8-sig"
        )

    end = datetime.now()
    print(f"\n▶ スクリーニング終了: {end.strftime('%Y-%m-%d %H:%M:%S')}")
    print(f"⏱ 処理時間: {end - start}")

    print("\n--- 取得失敗・除外 内訳 ---")
    for k, v in error_counts.items():
        print(f"{k}: {v}")

    print(f"\n✅ ヒット銘柄数: {len(results)}")

if __name__ == "__main__":
    main()
